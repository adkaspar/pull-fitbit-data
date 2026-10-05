"""Roll raw data points up into one summary row per local calendar day.

Matches the Notion Health Log: sleep is filed under the date you woke up,
activity is summed per local day, and resting heart rate is Fitbit's daily value.
"""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

COLUMNS = [
    "date",
    "sleep_hours",
    "time_in_bed_hours",
    "bedtime",
    "wake_time",
    "deep_sleep_min",
    "rem_sleep_min",
    "steps",
    "distance_km",
    "active_zone_minutes",
    "resting_heart_rate",
]


def _points(raw_dir: Path, key: str):
    for f in sorted((raw_dir / key).glob("*.jsonl")):
        with f.open() as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def _local(ts: str, offset: str) -> datetime:
    """UTC RFC-3339 timestamp + offset like "-10800s" -> naive local datetime."""
    utc = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
    return utc + timedelta(seconds=int(offset.rstrip("s") or 0))


def _civil_date(interval: dict[str, Any]) -> date:
    civil = interval.get("civilStartTime", {}).get("date")
    if civil:
        return date(civil["year"], civil["month"], civil["day"])
    return _local(interval["startTime"], interval.get("startUtcOffset", "0s")).date()


def summarize(raw_dir: Path) -> list[dict[str, Any]]:
    days: dict[date, dict[str, Any]] = defaultdict(dict)

    def add(day: date, col: str, value: float) -> None:
        days[day][col] = days[day].get(col, 0) + value

    for p in _points(raw_dir, "steps"):
        add(_civil_date(p["steps"]["interval"]), "steps", int(p["steps"]["count"]))
    for p in _points(raw_dir, "distance"):
        d = p["distance"]
        add(_civil_date(d["interval"]), "distance_km", int(d["millimeters"]) / 1e6)
    for p in _points(raw_dir, "active-zone-minutes"):
        a = p["activeZoneMinutes"]
        add(_civil_date(a["interval"]), "active_zone_minutes", int(a["activeZoneMinutes"]))
    for p in _points(raw_dir, "daily-resting-heart-rate"):
        r = p["dailyRestingHeartRate"]
        d = r["date"]
        days[date(d["year"], d["month"], d["day"])]["resting_heart_rate"] = int(
            r["beatsPerMinute"]
        )

    # Main sleep per wake-up date; if several are flagged, keep the longest.
    best: dict[date, tuple[int, dict]] = {}
    for p in _points(raw_dir, "sleep"):
        s = p["sleep"]
        if not s.get("metadata", {}).get("mainSleep"):
            continue
        iv = s["interval"]
        start = _local(iv["startTime"], iv.get("startUtcOffset", "0s"))
        end = _local(iv["endTime"], iv.get("endUtcOffset", "0s"))
        in_bed = int((end - start).total_seconds() // 60)
        if end.date() not in best or in_bed > best[end.date()][0]:
            best[end.date()] = (in_bed, {"s": s, "start": start, "end": end})
    for day, (in_bed, rec) in best.items():
        summary = rec["s"].get("summary", {})
        stages = {x["type"]: int(x["minutes"]) for x in summary.get("stagesSummary", [])}
        asleep = int(summary.get("minutesAsleep") or in_bed - stages.get("AWAKE", 0))
        days[day].update(
            sleep_hours=round(asleep / 60, 2),
            time_in_bed_hours=round(in_bed / 60, 2),
            bedtime=rec["start"].strftime("%H:%M"),
            wake_time=rec["end"].strftime("%H:%M"),
            deep_sleep_min=stages.get("DEEP"),
            rem_sleep_min=stages.get("REM"),
        )

    rows = []
    for day in sorted(days):
        row = {"date": day.isoformat(), **days[day]}
        if row.get("steps") is not None:
            row.setdefault("active_zone_minutes", 0)
        if "distance_km" in row:
            row["distance_km"] = round(row["distance_km"], 2)
        rows.append({c: row.get(c) for c in COLUMNS})
    return rows
