import json
from datetime import date, timedelta

from fitbit_pull.readiness import assess, readiness, sleep_by_wake_date

DAY = date(2026, 10, 17)


def _d(day: date) -> dict:
    return {"year": day.year, "month": day.month, "day": day.day}


def sleep_point(wake: date, minutes: int, nap: bool = False) -> dict:
    return {
        "sleep": {
            "interval": {"civilEndTime": {"date": _d(wake), "time": {"hours": 7}}},
            "metadata": {"nap": nap, "mainSleep": not nap},
            "summary": {"minutesAsleep": str(minutes)},
        }
    }


def daily_point(field: str, key: str, day: date, value) -> dict:
    return {field: {"date": _d(day), key: value}}


def baseline(value: float, days: int = 14) -> dict[date, float]:
    return {DAY - timedelta(days=i): value for i in range(1, days + 1)}


def test_sleep_ignores_naps_and_keys_by_wake_date():
    points = [p["sleep"] for p in (sleep_point(DAY, 420), sleep_point(DAY, 40, nap=True))]
    assert sleep_by_wake_date(points) == {DAY: 420}


def test_short_sleep_and_low_hrv_is_low():
    sleep = {**baseline(450), DAY: 330}
    hrv = {**baseline(50), DAY: 38}
    result = assess(sleep, hrv, {}, DAY)
    assert result["level"] == "low"
    assert len(result["reasons"]) == 2


def test_under_five_hours_alone_is_low():
    assert assess({DAY: 280}, {}, {}, DAY)["level"] == "low"


def test_good_sleep_and_high_hrv_is_high():
    result = assess({**baseline(420), DAY: 450}, {**baseline(50), DAY: 60}, {}, DAY)
    assert result["level"] == "high"


def test_elevated_resting_hr_counts_against():
    result = assess({**baseline(420), DAY: 340}, {}, {**baseline(58), DAY: 65}, DAY)
    assert result["level"] == "low"


def test_no_baseline_and_ok_sleep_is_normal():
    assert assess({DAY: 420}, {}, {}, DAY)["level"] == "normal"


def test_no_data_is_unknown():
    assert assess({}, {}, {}, DAY)["level"] == "unknown"


def test_readiness_reads_raw_files(tmp_path):
    raw = tmp_path / "raw"

    def write(key: str, day: date, point: dict) -> None:
        path = raw / key / f"{day:%Y-%m}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(point) + "\n")

    hrv_field = ("dailyHeartRateVariability", "averageHeartRateVariabilityMilliseconds")
    for i in range(1, 15):
        day = DAY - timedelta(days=i)
        write("sleep", day, sleep_point(day, 450))
        write("daily-heart-rate-variability", day, daily_point(*hrv_field, day, 50.0))
    write("sleep", DAY, sleep_point(DAY, 300))
    write("daily-heart-rate-variability", DAY, daily_point(*hrv_field, DAY, 40.0))

    result = readiness(raw, DAY)
    assert result["sleep_minutes"] == 300
    assert result["hrv_ms"] == 40.0
    assert result["level"] == "low"
