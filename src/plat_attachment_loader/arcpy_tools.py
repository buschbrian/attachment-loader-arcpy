"""ArcPy-specific operations isolated from the pure-Python modules."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from .config import MatchingConfig
from .matching import norm

LOGGER = logging.getLogger(__name__)


def load_arcpy():
    """Import ArcPy lazily so pure-Python modes can run without ArcGIS Pro."""

    try:
        import arcpy  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - requires ArcGIS Pro
        raise SystemExit(
            "Could not initialize arcpy. Run this from a licensed ArcGIS Pro "
            "Python session, such as an ArcGIS Pro notebook/Python window, or "
            "sign in and initialize Pro licensing before using propy.bat. "
            f"Original error: {exc}"
        ) from exc
    return arcpy


def arcpy_messages(arcpy, severity: int = 2) -> str:
    try:
        return arcpy.GetMessages(severity)
    except Exception:
        return ""


def fail_arcpy(arcpy, message: str, exc: Exception | None = None) -> None:
    details = arcpy_messages(arcpy, 2)
    if details:
        message = f"{message}\nArcGIS messages:\n{details}"
    elif exc is not None:
        message = f"{message}\nOriginal error: {exc}"
    raise SystemExit(message) from exc


def ensure_gdb(arcpy, gdb: Path) -> Path:
    """Create a file geodatabase if it does not already exist."""

    gdb = gdb.resolve()
    if arcpy.Exists(str(gdb)) or gdb.exists():
        return gdb
    gdb.parent.mkdir(parents=True, exist_ok=True)
    try:
        arcpy.management.CreateFileGDB(str(gdb.parent), gdb.stem)
    except Exception as exc:  # pragma: no cover - requires ArcPy
        fail_arcpy(
            arcpy,
            "Could not create the output file geodatabase. Choose a folder you can write to.\n"
            f"Folder: {gdb.parent}\nGeodatabase: {gdb.name}",
            exc,
        )
    return gdb


def validate_feature_inputs(arcpy, input_features: str, key_field: str) -> None:
    """Validate the dataset and matching key field before doing work."""

    if not arcpy.Exists(input_features):
        raise SystemExit(f"Input features do not exist or are not accessible: {input_features}")
    fields = {field.name.upper(): field.name for field in arcpy.ListFields(input_features)}
    if key_field.upper() not in fields:
        available = ", ".join(sorted(fields.values()))
        raise SystemExit(f"Key field not found: {key_field}\nAvailable fields: {available}")


def make_output(arcpy, input_features: str, output_gdb: Path, output_name: str, overwrite_output: bool) -> str:
    """Copy input features to a safe output feature class."""

    gdb = ensure_gdb(arcpy, output_gdb)
    out_fc = str(gdb / output_name)
    if arcpy.Exists(out_fc):
        if not overwrite_output:
            raise SystemExit(f"{out_fc} exists. Use --overwrite-output to replace it.")
        try:
            arcpy.management.Delete(out_fc)
        except Exception as exc:  # pragma: no cover - requires ArcPy
            fail_arcpy(arcpy, f"Could not delete existing output feature class: {out_fc}", exc)
    try:
        arcpy.management.CopyFeatures(input_features, out_fc)
    except Exception as exc:  # pragma: no cover - requires ArcPy
        fail_arcpy(arcpy, f"Could not copy features to: {out_fc}", exc)
    return out_fc


def oid_field(arcpy, dataset: str) -> str:
    desc = arcpy.Describe(dataset)
    for attr in ("OIDFieldName", "oidFieldName"):
        try:
            value = getattr(desc, attr)
        except Exception:
            value = None
        if value:
            return value
    for field in arcpy.ListFields(dataset):
        if str(getattr(field, "type", "")).upper() == "OID":
            return field.name
    raise SystemExit(f"Could not find an ObjectID field for: {dataset}")


def index_features(arcpy, fc: str, field: str, config: MatchingConfig) -> dict[str, list[tuple[int, str]]]:
    """Index feature rows by normalized key field value."""

    oid = oid_field(arcpy, fc)
    found: dict[str, list[tuple[int, str]]] = {}
    try:
        with arcpy.da.SearchCursor(fc, [oid, field]) as cursor:
            for object_id, value in cursor:
                key = norm(value, config)
                if key:
                    found.setdefault(key, []).append((int(object_id), str(value)))
    except Exception as exc:  # pragma: no cover - requires ArcPy
        fail_arcpy(arcpy, f"Could not index features by field: {field}", exc)
    return found


def feature_rows(arcpy, fc: str, field: str) -> list[dict]:
    oid = oid_field(arcpy, fc)
    rows: list[dict] = []
    try:
        with arcpy.da.SearchCursor(fc, [oid, field]) as cursor:
            for object_id, value in cursor:
                rows.append({"oid": int(object_id), field: value})
    except Exception as exc:  # pragma: no cover - requires ArcPy
        fail_arcpy(arcpy, f"Could not read feature rows from: {fc}", exc)
    return rows


def attachment_table(arcpy, fc: str) -> str | None:
    catalog = getattr(arcpy.Describe(fc), "catalogPath", fc)
    candidate = str(Path(catalog).parent / f"{Path(catalog).name}__ATTACH")
    return candidate if arcpy.Exists(candidate) else None


def attachment_relationship(arcpy, fc: str) -> str | None:
    catalog = getattr(arcpy.Describe(fc), "catalogPath", fc)
    candidate = str(Path(catalog).parent / f"{Path(catalog).name}__ATTACHREL")
    return candidate if arcpy.Exists(candidate) else None


def attachment_count(arcpy, fc: str) -> int | None:
    table = attachment_table(arcpy, fc)
    if table is None:
        return None
    try:
        return int(arcpy.management.GetCount(table)[0])
    except Exception:
        return None


def _attachment_fields(arcpy, table: str) -> tuple[str | None, str | None]:
    fields = {field.name.upper(): field.name for field in arcpy.ListFields(table)}
    rel_field = fields.get("REL_OBJECTID")
    name_field = fields.get("ATT_NAME") or fields.get("NAME")
    return rel_field, name_field


def existing_attachment_names_by_oid(arcpy, fc: str) -> dict[int, set[str]]:
    """Return existing attachment filenames grouped by related ObjectID."""

    table = attachment_table(arcpy, fc)
    if table is None:
        return {}
    rel_field, name_field = _attachment_fields(arcpy, table)
    if not rel_field or not name_field:
        LOGGER.warning("Attachment table exists but expected fields were not found: %s", table)
        return {}
    names: dict[int, set[str]] = {}
    try:
        with arcpy.da.SearchCursor(table, [rel_field, name_field]) as cursor:
            for rel_oid, name in cursor:
                if rel_oid is None or not name:
                    continue
                names.setdefault(int(rel_oid), set()).add(str(name))
    except Exception as exc:  # pragma: no cover - requires ArcPy
        fail_arcpy(arcpy, f"Could not read existing attachment table: {table}", exc)
    return names


def attached_oids(arcpy, fc: str) -> set[int] | None:
    table = attachment_table(arcpy, fc)
    if table is None:
        return None
    rel_field, _name_field = _attachment_fields(arcpy, table)
    if not rel_field:
        return None
    try:
        with arcpy.da.SearchCursor(table, [rel_field]) as cursor:
            return {int(row[0]) for row in cursor if row[0] is not None}
    except Exception:
        return None


def filter_duplicate_attachment_rows(rows: list[dict], existing_names_by_oid: dict[int, set[str]]) -> tuple[list[dict], list[dict]]:
    """Split planned rows into new rows and rows already attached by filename."""

    new_rows: list[dict] = []
    skipped: list[dict] = []
    for row in rows:
        oid = int(row["oid"])
        filename = Path(str(row["file"])).name.lower()
        existing = {name.lower() for name in existing_names_by_oid.get(oid, set())}
        if filename in existing:
            skipped.append(row)
        else:
            new_rows.append(row)
    return new_rows, skipped


def delete_existing_attachments(arcpy, fc: str, rows: Iterable[dict]) -> int:
    """Delete existing attachments that match planned ObjectID + filename rows."""

    table = attachment_table(arcpy, fc)
    if table is None:
        return 0
    rel_field, name_field = _attachment_fields(arcpy, table)
    if not rel_field or not name_field:
        return 0
    targets = {(int(row["oid"]), Path(str(row["file"])).name.lower()) for row in rows}
    deleted = 0
    try:
        with arcpy.da.UpdateCursor(table, [rel_field, name_field]) as cursor:
            for rel_oid, name in cursor:
                if rel_oid is None or not name:
                    continue
                if (int(rel_oid), str(name).lower()) in targets:
                    cursor.deleteRow()
                    deleted += 1
    except Exception as exc:  # pragma: no cover - requires ArcPy
        fail_arcpy(arcpy, f"Could not delete existing matching attachments from: {table}", exc)
    return deleted


def add_attachments(arcpy, fc: str, gdb: Path, rows: list[dict], overwrite_match_table: bool) -> str:
    """Create a match table and add attachments through ArcPy."""

    gdb = ensure_gdb(arcpy, gdb)
    table = str(gdb / "plat_attachment_match")
    if arcpy.Exists(table):
        if not overwrite_match_table:
            raise SystemExit(f"{table} exists. Use --overwrite-output to replace it.")
        try:
            arcpy.management.Delete(table)
        except Exception as exc:  # pragma: no cover - requires ArcPy
            fail_arcpy(arcpy, f"Could not delete existing match table: {table}", exc)
    try:
        arcpy.management.CreateTable(str(gdb), "plat_attachment_match")
        arcpy.management.AddField(table, "TARGET_OID", "LONG")
        arcpy.management.AddField(table, "ATTACH_PATH", "TEXT", field_length=1000)
        with arcpy.da.InsertCursor(table, ["TARGET_OID", "ATTACH_PATH"]) as cursor:
            for row in rows:
                cursor.insertRow([row["oid"], row["file"]])
        if not bool(getattr(arcpy.Describe(fc), "hasAttachments", False)):
            arcpy.management.EnableAttachments(fc)
        arcpy.management.AddAttachments(fc, oid_field(arcpy, fc), table, "TARGET_OID", "ATTACH_PATH")
    except Exception as exc:  # pragma: no cover - requires ArcPy
        fail_arcpy(arcpy, "Could not add attachments.", exc)
    return table
