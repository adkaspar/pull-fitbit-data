import json
from datetime import date

import pytest

from fitbit_pull.client import ApiError, HealthClient, build_filter
from fitbit_pull.datatypes import DATA_TYPES, resolve
from fitbit_pull.export import export_csv
from fitbit_pull.pull import month_chunks, pull


class FakeResponse:
    def __init__(self, status: int, body: dict, headers: dict | None = None) -> None:
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body)

    def json(self) -> dict:
        return self._body


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)


def steps_point(n: int, start: str) -> dict:
    return {
        "name": f"users/me/dataTypes/steps/dataPoints/{n}",
        "dataSource": {"platform": "FITBIT", "device": {"manufacturer": "Fitbit"}},
        "steps": {"interval": {"startTime": start, "endTime": start}, "count": str(n)},
    }


def test_build_filter_formats_per_kind():
    d0, d1 = date(2026, 1, 1), date(2026, 2, 1)
    assert build_filter(DATA_TYPES["steps"], d0, d1) == (
        'steps.interval.start_time >= "2026-01-01T00:00:00Z" AND '
        'steps.interval.start_time < "2026-02-01T00:00:00Z"'
    )
    assert build_filter(DATA_TYPES["exercise"], d0, d1) == (
        'exercise.interval.civil_start_time >= "2026-01-01T00:00:00" AND '
        'exercise.interval.civil_start_time < "2026-02-01T00:00:00"'
    )
    assert build_filter(DATA_TYPES["daily-resting-heart-rate"], d0, d1) == (
        'daily_resting_heart_rate.date >= "2026-01-01" AND '
        'daily_resting_heart_rate.date < "2026-02-01"'
    )
    assert build_filter(DATA_TYPES["sleep"], d0, d1).startswith("sleep.interval.end_time >=")
    assert "<" not in build_filter(DATA_TYPES["electrocardiogram"], d0, d1)


def test_month_chunks_align_to_month_start():
    assert list(month_chunks(date(2025, 12, 15), date(2026, 2, 10))) == [
        (date(2025, 12, 1), date(2026, 1, 1)),
        (date(2026, 1, 1), date(2026, 2, 1)),
        (date(2026, 2, 1), date(2026, 2, 10)),
    ]
    assert list(month_chunks(date(2026, 3, 1), date(2026, 3, 1))) == []


def test_list_points_paginates_and_sets_page_size():
    session = FakeSession([
        FakeResponse(200, {"dataPoints": [steps_point(1, "a")], "nextPageToken": "t"}),
        FakeResponse(200, {"dataPoints": [steps_point(2, "b")]}),
    ])
    client = HealthClient(session, base_url="https://x/v4")
    points = list(client.list_points(DATA_TYPES["steps"], date(2026, 1, 1), date(2026, 2, 1)))
    assert [p["steps"]["count"] for p in points] == ["1", "2"]
    assert session.calls[0][0] == "https://x/v4/users/me/dataTypes/steps/dataPoints"
    assert session.calls[0][1]["pageSize"] == 10000
    assert "pageToken" not in session.calls[0][1]
    assert session.calls[1][1]["pageToken"] == "t"

    session = FakeSession([FakeResponse(200, {})])
    list(HealthClient(session).list_points(DATA_TYPES["sleep"], date(2026, 1, 1), date(2026, 2, 1)))
    assert session.calls[0][1]["pageSize"] == 25


def test_retries_on_429_then_raises_on_4xx():
    slept = []
    session = FakeSession([
        FakeResponse(429, {}, {"Retry-After": "3"}),
        FakeResponse(503, {}),
        FakeResponse(200, {"dataPoints": []}),
    ])
    client = HealthClient(session, sleep=slept.append)
    assert list(client.list_points(DATA_TYPES["steps"], date(2026, 1, 1), date(2026, 1, 2))) == []
    assert slept == [3.0, 2]

    session = FakeSession([
        FakeResponse(403, {"error": {"status": "PERMISSION_DENIED", "message": "no scope"}})
    ])
    with pytest.raises(ApiError, match="PERMISSION_DENIED no scope"):
        list(HealthClient(session).list_points(DATA_TYPES["steps"], date(2026, 1, 1), date(2026, 1, 2)))


def test_ecg_filters_end_client_side():
    ecg = lambda start: {"name": start, "electrocardiogram": {"interval": {"startTime": start}}}
    session = FakeSession([FakeResponse(200, {"dataPoints": [
        ecg("2026-02-03T10:00:00Z"), ecg("2026-01-20T10:00:00Z"),
    ]})])
    points = list(HealthClient(session).list_points(
        DATA_TYPES["electrocardiogram"], date(2026, 1, 1), date(2026, 2, 1)))
    assert [p["name"] for p in points] == ["2026-01-20T10:00:00Z"]


def test_pull_writes_month_files_resumes_and_exports(tmp_path):
    steps = [DATA_TYPES["steps"]]
    session = FakeSession([
        FakeResponse(200, {"dataPoints": [steps_point(1, "2026-01-05T00:00:00Z")]}),
        FakeResponse(200, {"dataPoints": [steps_point(2, "2026-02-03T00:00:00Z")] * 2}),
    ])
    counts = pull(HealthClient(session), steps, tmp_path, date(2026, 1, 10), date(2026, 2, 15))
    assert counts == {"steps": 2}  # duplicate point in Feb deduped
    assert sorted(p.name for p in (tmp_path / "raw/steps").iterdir()) == ["2026-01.jsonl", "2026-02.jsonl"]
    assert json.loads((tmp_path / "state.json").read_text()) == {"steps": "2026-02-15"}

    # Resume: no --start, re-pulls February (the partially completed month) only.
    session = FakeSession([FakeResponse(200, {"dataPoints": [
        steps_point(2, "2026-02-03T00:00:00Z"), steps_point(3, "2026-02-20T00:00:00Z"),
    ]})])
    pull(HealthClient(session), steps, tmp_path, None, date(2026, 3, 1))
    assert len(session.calls) == 1
    assert '>= "2026-02-01T00:00:00Z"' in session.calls[0][1]["filter"]
    assert len((tmp_path / "raw/steps/2026-02.jsonl").read_text().splitlines()) == 2

    n = export_csv(DATA_TYPES["steps"], tmp_path / "raw", tmp_path / "csv/steps.csv")
    assert n == 3
    header = (tmp_path / "csv/steps.csv").read_text().splitlines()[0].split(",")
    assert header[:4] == ["name", "interval.startTime", "interval.endTime", "count"]
    assert "dataSource.device.manufacturer" in header


def test_pull_requires_start_on_first_run(tmp_path):
    with pytest.raises(ValueError, match="--start"):
        pull(HealthClient(FakeSession([])), resolve(["steps"]), tmp_path, None, date(2026, 1, 1))


def test_resolve_rejects_unknown_types():
    with pytest.raises(ValueError, match="nope"):
        resolve(["steps", "nope"])
    assert "electrocardiogram" not in [dt.key for dt in resolve(None)]
