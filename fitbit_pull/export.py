"""Flatten raw JSONL data points into one CSV per data type."""

import csv
import json
from pathlib import Path
from typing import Any

from .client import payload
from .datatypes import DataType


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts into dotted keys; lists become JSON strings."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        out[prefix] = json.dumps(obj, separators=(",", ":"))
    else:
        out[prefix] = obj
    return out


def to_row(point: dict[str, Any], dt: DataType) -> dict[str, Any]:
    row = {"name": point.get("name")}
    row.update(flatten(payload(point, dt)))
    row.update(flatten(point.get("dataSource", {}), "dataSource"))
    return row


def export_csv(dt: DataType, raw_dir: Path, csv_path: Path) -> int:
    """Write every point of `dt` under raw_dir to csv_path. Returns row count."""
    files = sorted((raw_dir / dt.key).glob("*.jsonl"))
    rows = []
    for f in files:
        with f.open() as fh:
            rows.extend(to_row(json.loads(line), dt) for line in fh if line.strip())
    if not rows:
        return 0

    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for col in row:
            if col not in seen:
                seen.add(col)
                columns.append(col)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
