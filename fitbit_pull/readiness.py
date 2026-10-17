"""Summarize last night's sleep, HRV and resting heart rate into an energy level.

Reads data already pulled to <out>/raw (run `fitbit-pull pull` first) and
compares the target day against the person's own recent baseline. The output
is meant for a planning agent: a coarse level ("low", "normal", "high") plus
the numbers and reasons behind it.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from .client import payload
from .datatypes import DATA_TYPES

READINESS_TYPES = ["sleep", "daily-heart-rate-variability", "daily-resting-heart-rate"]
BASELINE_DAYS = 30


def _date(d: dict[str, Any]) -> date | None:
    try:
        return date(d["year"], d["month"], d["day"])
    except (KeyError, TypeError, ValueError):
        return None


def load_points(raw_dir: Path, key: str, day: date) -> list[dict[str, Any]]:
    """Payloads of `key` from the month files covering the baseline window."""
    dt = DATA_TYPES[key]
    start = day - timedelta(days=BASELINE_DAYS)
    months = {f"{start:%Y-%m}", f"{day:%Y-%m}"}
    points = []
    for month in sorted(months):
        path = raw_dir / key / f"{month}.jsonl"
        if path.exists():
            with path.open() as fh:
                points.extend(payload(json.loads(line), dt) for line in fh if line.strip())
    return points


def sleep_by_wake_date(points: list[dict[str, Any]]) -> dict[date, int]:
    """Minutes asleep in the main sleep of each night, keyed by local wake date."""
    out: dict[date, int] = {}
    for p in points:
        meta = p.get("metadata", {})
        if meta.get("nap") or meta.get("mainSleep") is False:
            continue
        wake = _date(p.get("interval", {}).get("civilEndTime", {}).get("date", {}))
        minutes = p.get("summary", {}).get("minutesAsleep")
        if wake and minutes is not None:
            out[wake] = max(out.get(wake, 0), int(minutes))
    return out


def daily_values(points: list[dict[str, Any]], field: str) -> dict[date, float]:
    out: dict[date, float] = {}
    for p in points:
        day = _date(p.get("date", {}))
        if day and p.get(field) is not None:
            out[day] = float(p[field])
    return out


def _baseline(values: dict[date, float], day: date) -> float | None:
    window = [v for d, v in values.items() if day - timedelta(days=BASELINE_DAYS) <= d < day]
    return median(window) if len(window) >= 5 else None


def assess(
    sleep: dict[date, int],
    hrv: dict[date, float],
    rhr: dict[date, float],
    day: date,
) -> dict[str, Any]:
    """Score `day` against the preceding baseline window."""
    reasons: list[str] = []
    low = high = 0

    sleep_min = sleep.get(day)
    sleep_base = _baseline(sleep, day)
    if sleep_min is not None:
        if sleep_min < 300:
            low += 2
            reasons.append(f"slept {sleep_min / 60:.1f}h (under 5h)")
        elif sleep_min < 360 or (sleep_base and sleep_min < sleep_base - 60):
            low += 1
            reasons.append(f"slept {sleep_min / 60:.1f}h, short for you")
        elif sleep_base and sleep_min >= sleep_base:
            high += 1
            reasons.append(f"slept {sleep_min / 60:.1f}h, at or above your usual")

    hrv_val, hrv_base = hrv.get(day), _baseline(hrv, day)
    if hrv_val is not None and hrv_base:
        ratio = hrv_val / hrv_base
        if ratio < 0.85:
            low += 1
            reasons.append(f"HRV {hrv_val:.0f}ms, {1 - ratio:.0%} below your baseline")
        elif ratio > 1.10:
            high += 1
            reasons.append(f"HRV {hrv_val:.0f}ms, {ratio - 1:.0%} above your baseline")

    rhr_val, rhr_base = rhr.get(day), _baseline(rhr, day)
    if rhr_val is not None and rhr_base and rhr_val >= rhr_base + 5:
        low += 1
        reasons.append(f"resting HR {rhr_val:.0f}bpm, {rhr_val - rhr_base:.0f} above usual")

    if sleep_min is None and hrv_val is None and rhr_val is None:
        level = "unknown"
        reasons.append(f"no sleep, HRV or resting HR data for {day}")
    elif low >= 2:
        level = "low"
    elif high >= 2 and low == 0:
        level = "high"
    else:
        level = "normal"

    return {
        "date": day.isoformat(),
        "level": level,
        "reasons": reasons,
        "sleep_minutes": sleep_min,
        "sleep_baseline_minutes": round(sleep_base) if sleep_base else None,
        "hrv_ms": hrv_val,
        "hrv_baseline_ms": round(hrv_base, 1) if hrv_base else None,
        "resting_hr_bpm": rhr_val,
        "resting_hr_baseline_bpm": rhr_base,
    }


def readiness(raw_dir: Path, day: date) -> dict[str, Any]:
    return assess(
        sleep_by_wake_date(load_points(raw_dir, "sleep", day)),
        daily_values(
            load_points(raw_dir, "daily-heart-rate-variability", day),
            "averageHeartRateVariabilityMilliseconds",
        ),
        daily_values(load_points(raw_dir, "daily-resting-heart-rate", day), "beatsPerMinute"),
        day,
    )
