"""CSV report writers."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable, Mapping

from . import __version__
from .config import MatchingConfig
from .matching import PlatFile, norm


ATTACHMENT_REPORT_FIELDS = [
    "run_timestamp_utc",
    "script_version",
    "input_features",
    "attachments_dir",
    "overlay_dir",
    "key_field",
    "max_mb",
    "status",
    "oid",
    "file",
    "source_file_name",
    "size_mb",
    "file_key",
    "feature_value",
    "message",
]


MISSING_REPORT_BASE_FIELDS = [
    "run_timestamp_utc",
    "script_version",
    "input_features",
    "attachments_dir",
    "overlay_dir",
    "key_field",
    "max_mb",
    "oid",
]


SUMMARY_FIELDS = [
    "run_timestamp_utc",
    "script_version",
    "input_features",
    "attachments_dir",
    "overlay_dir",
    "key_field",
    "max_mb",
    "files_scanned",
    "attachable_rows",
    "missing_feature_rows",
    "status_counts_json",
]


def run_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_metadata(
    input_features: str | None,
    attachments_dir: Path,
    overlay_dir: Path | None,
    key_field: str | None,
    max_mb: float,
) -> dict[str, object]:
    return {
        "run_timestamp_utc": run_timestamp(),
        "script_version": __version__,
        "input_features": input_features or "",
        "attachments_dir": str(attachments_dir),
        "overlay_dir": str(overlay_dir) if overlay_dir else "",
        "key_field": key_field or "",
        "max_mb": f"{max_mb:g}",
    }


def _with_metadata(row: Mapping[str, object], metadata: Mapping[str, object]) -> dict[str, object]:
    return dict(metadata) | dict(row)


def write_attachment_report(path: Path, rows: list[dict], metadata: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ATTACHMENT_REPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(_with_metadata(row, metadata))
    write_metadata_json(path, metadata)


def write_missing_report(path: Path, key_field: str, rows: list[dict], metadata: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = MISSING_REPORT_BASE_FIELDS + [key_field, "missing_reason", "file", "file_size_mb"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(_with_metadata(row, metadata))
    write_metadata_json(path, metadata)


def write_summary_report(
    path: Path,
    metadata: Mapping[str, object],
    files_scanned: int,
    attachable_rows: int,
    missing_feature_rows: int,
    status_counts: Mapping[str, int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(metadata) | {
        "files_scanned": files_scanned,
        "attachable_rows": attachable_rows,
        "missing_feature_rows": missing_feature_rows,
        "status_counts_json": json.dumps(dict(status_counts), sort_keys=True),
    }
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)


def write_metadata_json(csv_path: Path, metadata: Mapping[str, object]) -> None:
    metadata_path = csv_path.with_suffix(csv_path.suffix + ".metadata.json")
    metadata_path.write_text(json.dumps(dict(metadata), indent=2, sort_keys=True), encoding="utf-8")


def size_rows(plats: list[PlatFile], max_mb: float, config: MatchingConfig) -> list[dict]:
    max_bytes = max_mb * 1024 * 1024
    rows: list[dict] = []
    for plat in sorted(plats, key=lambda item: item.size_bytes, reverse=True):
        status = "too_large" if plat.size_bytes > max_bytes else "ok"
        rows.append(
            {
                "status": status,
                "oid": "",
                "file": str(plat.path),
                "source_file_name": plat.path.name,
                "size_mb": f"{plat.size_mb:.3f}",
                "file_key": norm(plat.raw_name, config),
                "feature_value": "",
                "message": f"Over {max_mb:g} MB" if status == "too_large" else "",
            }
        )
    return rows


def summarize_statuses(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status", ""))
        counts[status] = counts.get(status, 0) + 1
    return counts
