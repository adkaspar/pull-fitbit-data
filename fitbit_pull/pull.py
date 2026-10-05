"""Pull data points month by month into JSONL files, resuming where the last run ended.

Layout under the output directory:

    raw/<data-type>/<YYYY-MM>.jsonl          one raw API data point per line
    reconciled/<data-type>/<YYYY-MM>.jsonl   same, with sources merged (--reconciled)
    state.json, state-reconciled.json        {data-type: end date of last completed pull}

Each month file is rewritten whole, so re-pulling a month is idempotent.
"""

import json
import logging
import os
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

from .client import HealthClient
from .datatypes import DataType

log = logging.getLogger(__name__)


def month_chunks(start: date, end: date) -> Iterator[tuple[date, date]]:
    """Split [start, end) into chunks aligned to calendar months.

    The first chunk starts at the first of start's month so that each chunk
    covers its whole month file (up to `end`).
    """
    cur = start.replace(day=1)
    while cur < end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield cur, min(nxt, end)
        cur = nxt


class State:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}

    def last_end(self, key: str) -> date | None:
        value = self._data.get(key)
        return date.fromisoformat(value) if value else None

    def set_last_end(self, key: str, value: date) -> None:
        self._data[key] = value.isoformat()
        _atomic_write(self.path, json.dumps(self._data, indent=2, sort_keys=True) + "\n")


def pull(
    client: HealthClient,
    types: list[DataType],
    out_dir: Path,
    start: date | None,
    end: date,
    reconcile: bool = False,
) -> dict[str, int]:
    """Pull each type from `start` (or where the last run ended) up to `end`.

    Returns the number of data points written per type.
    """
    kind = "reconciled" if reconcile else "raw"
    state = State(out_dir / ("state-reconciled.json" if reconcile else "state.json"))
    counts: dict[str, int] = {}
    for dt in types:
        type_start = start or state.last_end(dt.key)
        if type_start is None:
            raise ValueError(
                f"No previous pull for {dt.key}; pass --start for the first run."
            )
        total = 0
        for chunk_start, chunk_end in month_chunks(type_start, end):
            points = _dedupe(client.list_points(dt, chunk_start, chunk_end, reconcile))
            path = out_dir / kind / dt.key / f"{chunk_start:%Y-%m}.jsonl"
            _write_jsonl(path, points)
            total += len(points)
            log.info("%s %s: %d points", dt.key, f"{chunk_start:%Y-%m}", len(points))
            state.set_last_end(dt.key, chunk_end)
        counts[dt.key] = total
    return counts


def _dedupe(points: Iterator[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for p in points:
        name = p.get("name")
        if name:
            if name in seen:
                continue
            seen.add(name)
        out.append(p)
    return out


def _write_jsonl(path: Path, points: list[dict]) -> None:
    if not points:
        # Don't leave stale data behind if a month is now empty.
        path.unlink(missing_ok=True)
        return
    _atomic_write(path, "".join(json.dumps(p, separators=(",", ":")) + "\n" for p in points))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
