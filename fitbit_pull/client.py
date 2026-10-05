"""Minimal synchronous client for listing Google Health API data points."""

import logging
import time
from collections.abc import Iterator
from datetime import date
from typing import Any

from .datatypes import SESSION_TYPES, DataType, TimeKind

API_URL = "https://health.googleapis.com/v4"
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 6

log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


def _literal(kind: TimeKind, day: date) -> str:
    if kind is TimeKind.PHYSICAL:
        return f"{day.isoformat()}T00:00:00Z"
    if kind is TimeKind.CIVIL:
        return f"{day.isoformat()}T00:00:00"
    return day.isoformat()


def build_filter(dt: DataType, start: date, end: date) -> str:
    """AIP-160 filter selecting points in [start, end)."""
    expr = f'{dt.filter_field} >= "{_literal(dt.kind, start)}"'
    if not dt.start_only:
        expr += f' AND {dt.filter_field} < "{_literal(dt.kind, end)}"'
    return expr


class HealthClient:
    def __init__(self, session: Any, base_url: str = API_URL, sleep=time.sleep) -> None:
        """`session` is a requests-compatible session that adds auth headers,
        e.g. google.auth.transport.requests.AuthorizedSession."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/{path}"
        for attempt in range(MAX_RETRIES + 1):
            resp = self._session.get(url, params=params, timeout=60)
            if resp.status_code < 400:
                return resp.json()
            if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                delay = _retry_after(resp) or min(2**attempt, 60)
                log.warning("HTTP %s on %s, retrying in %ss", resp.status_code, path, delay)
                self._sleep(delay)
                continue
            raise ApiError(f"HTTP {resp.status_code} for {path}: {_error_detail(resp)}")
        raise AssertionError("unreachable")

    def list_points(self, dt: DataType, start: date, end: date) -> Iterator[dict[str, Any]]:
        """Yield raw data points of `dt` in [start, end), following pagination."""
        params: dict[str, Any] = {
            "pageSize": 25 if dt.key in SESSION_TYPES else 10000,
            "filter": build_filter(dt, start, end),
        }
        path = f"users/me/dataTypes/{dt.key}/dataPoints"
        end_literal = _literal(dt.kind, end)
        while True:
            page = self._get(path, params)
            for point in page.get("dataPoints", []):
                if dt.start_only and _start_time(point, dt) >= end_literal:
                    continue
                yield point
            token = page.get("nextPageToken")
            if not token:
                return
            params["pageToken"] = token

    def get(self, path: str) -> dict[str, Any]:
        return self._get(path, {})


def payload(point: dict[str, Any], dt: DataType) -> dict[str, Any]:
    """Return the type-specific payload of a raw data point."""
    if dt.field in point:
        return point[dt.field]
    return point.get("data", {}).get(dt.field, {})


def _start_time(point: dict[str, Any], dt: DataType) -> str:
    return payload(point, dt).get("interval", {}).get("startTime", "")


def _retry_after(resp: Any) -> float | None:
    value = resp.headers.get("Retry-After")
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _error_detail(resp: Any) -> str:
    try:
        err = resp.json().get("error")
    except ValueError:
        return resp.text[:500]
    if isinstance(err, dict):
        return f"{err.get('status', '')} {err.get('message', '')}".strip()
    return str(err)
