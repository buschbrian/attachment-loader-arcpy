"""Attachment planning and QA logic that does not require ArcPy."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .config import MatchingConfig
from .matching import PlatFile, norm


def plat_lookup(plats: list[PlatFile], config: MatchingConfig) -> dict[str, list[tuple[Path, int]]]:
    lookup: dict[str, list[tuple[Path, int]]] = {}
    for plat in plats:
        key = norm(plat.raw_name, config)
        if key:
            lookup.setdefault(key, []).append((plat.path, plat.size_bytes))
    return lookup


def missing_reason(value: object, lookup: dict[str, list[tuple[Path, int]]], max_bytes: float, config: MatchingConfig) -> tuple[str, str, str]:
    key = norm(value, config)
    if not key:
        return "blank_key_field", "", ""
    matches = lookup.get(key, [])
    if not matches:
        return "no_matching_attachment_file", "", ""
    attachable = [(path, size) for path, size in matches if size <= max_bytes]
    source = attachable or matches
    files = "; ".join(str(path) for path, _size in source)
    sizes = "; ".join(f"{size / 1024 / 1024:.3f}" for _path, size in source)
    if attachable:
        return "ready_to_attach", files, sizes
    return "matching_attachment_file_too_large", files, sizes


def missing_polygon_rows(
    features: list[dict],
    key_field: str,
    lookup: dict[str, list[tuple[Path, int]]],
    max_mb: float,
    config: MatchingConfig,
    attached: set[int] | None = None,
    planned: set[int] | None = None,
) -> list[dict]:
    """Return feature rows that will not receive, or still lack, attachments.

    When attached is None this is a pre-attachment report and rows with an
    attachable planned file are not reported. When attached is supplied, a
    feature is reported unless its ObjectID is in that verified attached set.
    """

    rows: list[dict] = []
    max_bytes = max_mb * 1024 * 1024
    for feature in features:
        reason, files, sizes = missing_reason(feature.get(key_field), lookup, max_bytes, config)
        if attached is None and reason == "ready_to_attach" and (planned is None or feature["oid"] in planned):
            continue
        if attached is None and reason == "ready_to_attach" and planned is not None and feature["oid"] not in planned:
            reason = "not_planned_for_attachment"
        if attached is not None and feature["oid"] in attached:
            continue
        rows.append(
            {
                "oid": feature["oid"],
                key_field: feature.get(key_field),
                "missing_reason": reason,
                "file": files,
                "file_size_mb": sizes,
            }
        )
    return rows


def build_plan(
    max_mb: float,
    attach_to_all_matches: bool,
    plats: list[PlatFile],
    found: dict[str, list[tuple[int, str]]],
    config: MatchingConfig,
) -> tuple[list[dict], list[dict]]:
    """Build QA report rows and the subset of rows safe to attach."""

    report: list[dict] = []
    attach: list[dict] = []
    max_bytes = max_mb * 1024 * 1024
    for plat in plats:
        file_key = norm(plat.raw_name, config)
        base = {
            "file": str(plat.path),
            "source_file_name": plat.path.name,
            "size_mb": f"{plat.size_mb:.3f}",
            "file_key": file_key,
        }
        if plat.size_bytes > max_bytes:
            report.append(
                base
                | {
                    "status": "too_large",
                    "oid": "",
                    "feature_value": "",
                    "message": f"Over {max_mb:g} MB",
                }
            )
            continue
        matches = found.get(file_key, [])
        if not matches:
            report.append(
                base
                | {
                    "status": "unmatched",
                    "oid": "",
                    "feature_value": "",
                    "message": "No matching feature key",
                }
            )
            continue
        if len(matches) > 1 and not attach_to_all_matches:
            report.append(
                base
                | {
                    "status": "ambiguous",
                    "oid": "",
                    "feature_value": "; ".join(value for _oid, value in matches),
                    "message": "Use --attach-to-all-matches or make the key unique",
                }
            )
            continue
        for object_id, value in matches:
            row = base | {"status": "matched", "oid": object_id, "feature_value": value, "message": ""}
            report.append(row)
            attach.append(row)
    return report, attach


def unresolved(rows: Iterable[dict], ignore_unmatched_files: bool = False) -> list[dict]:
    """Return file-side report rows that should block publishing."""

    blockers: list[dict] = []
    for row in rows:
        if row["status"] == "matched":
            continue
        if ignore_unmatched_files and row["status"] == "unmatched":
            continue
        blockers.append(row)
    return blockers


def planned_filenames_by_oid(rows: Iterable[dict]) -> dict[int, set[str]]:
    """Return planned attachment basenames grouped by target ObjectID."""

    planned: dict[int, set[str]] = {}
    for row in rows:
        if row.get("oid") in (None, ""):
            continue
        planned.setdefault(int(row["oid"]), set()).add(Path(str(row["file"])).name.lower())
    return planned


def verified_attached_oids(rows: Iterable[dict], existing_names_by_oid: dict[int, set[str]]) -> set[int]:
    """Return ObjectIDs whose planned attachment filenames are present."""

    attached: set[int] = set()
    planned = planned_filenames_by_oid(rows)
    for oid, filenames in planned.items():
        existing = {name.lower() for name in existing_names_by_oid.get(oid, set())}
        if filenames & existing:
            attached.add(oid)
    return attached


def missing_planned_attachment_rows(rows: Iterable[dict], existing_names_by_oid: dict[int, set[str]]) -> list[dict]:
    """Return planned rows whose expected filename is not present after attachment."""

    missing: list[dict] = []
    for row in rows:
        oid = int(row["oid"])
        expected = Path(str(row["file"])).name.lower()
        existing = {name.lower() for name in existing_names_by_oid.get(oid, set())}
        if expected not in existing:
            missing.append(row)
    return missing
