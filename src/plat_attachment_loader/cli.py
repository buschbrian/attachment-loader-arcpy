"""Command-line interface for the attachment loader."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import re
import sys

from . import __version__
from .arcpy_tools import (
    add_attachments,
    attachment_count,
    attachment_relationship,
    attachment_table,
    delete_existing_attachments,
    existing_attachment_names_by_oid,
    feature_rows,
    filter_duplicate_attachment_rows,
    index_features,
    load_arcpy,
    make_output,
    validate_feature_inputs,
)
from .config import load_matching_config
from .matching import scan_plats
from .planning import (
    build_plan,
    missing_planned_attachment_rows,
    missing_polygon_rows,
    plat_lookup,
    unresolved,
    verified_attached_oids,
)
from .publish import overwrite_online
from .reports import (
    default_metadata,
    size_rows,
    summarize_statuses,
    write_attachment_report,
    write_missing_report,
    write_summary_report,
)

LOGGER = logging.getLogger(__name__)


def default_output_folder() -> Path:
    documents = Path.home() / "Documents"
    return documents if documents.exists() else Path.cwd()


def configure_logging(level: str, log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = prompt_input(f"{prompt}{suffix}: ", default).strip()
    return value or (default or "")


def ask_bool(prompt: str, default: bool = False) -> bool:
    label = "Y/n" if default else "y/N"
    while True:
        value = prompt_input(f"{prompt} [{label}]: ", "y" if default else "n").strip().lower()
        if not value:
            return default
        if value in {"y", "yes", "true", "1"}:
            return True
        if value in {"n", "no", "false", "0"}:
            return False
        print("Please answer yes or no.")


def ask_choice(prompt: str, choices: list[str], default: str) -> str:
    while True:
        value = ask(prompt, default).strip().lower()
        if value in choices:
            return value
        print(f"Please choose one of: {', '.join(choices)}")


def ask_float(prompt: str, default: float) -> float:
    while True:
        value = ask(prompt, f"{default:g}")
        try:
            return float(value)
        except ValueError:
            print("Please enter a number.")


def prompt_input(prompt: str, default: str | None = None) -> str:
    try:
        return input(prompt)
    except (EOFError, OSError, RuntimeError):
        return gui_input(prompt, default)


def gui_input(prompt: str, default: str | None = None) -> str:
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except Exception as exc:
        raise SystemExit(
            "Console input is not available, and tkinter dialogs could not be opened. "
            "Run this script from a terminal with command arguments or as an ArcGIS Pro script tool. "
            f"Original prompt was: {prompt}. Dialog error: {exc}"
        ) from exc

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    value = simpledialog.askstring("Attachment loader setup", prompt, initialvalue=default or "", parent=root)
    root.destroy()
    if value is None:
        raise SystemExit("User canceled attachment loader setup.")
    return value


def interactive_args() -> argparse.Namespace:
    print("ArcGIS attachment loader setup")
    print("Leave optional paths blank if you do not use them.")
    size_only = ask_bool("Only run a size report", False)
    plats_dir = Path(ask("Attachment file folder", str(Path.cwd()))).expanduser()
    overlay_text = ask("Reduced-file overlay folder", "")
    output_folder = Path(ask("Output/report folder", str(default_output_folder()))).expanduser()
    recursive = ask_bool("Scan folders recursively", True)
    report_csv = Path(ask("Report CSV", str(output_folder / "attachment_report.csv"))).expanduser()
    max_mb = ask_float("Maximum attachment size in MB", 10.0)

    args = argparse.Namespace(
        input_features=None,
        plats_dir=plats_dir,
        overlay_dir=Path(overlay_text).expanduser() if overlay_text else None,
        overlay_match_by="relative-path",
        key_field=None,
        config=None,
        extensions=None,
        output_gdb=output_folder / "attachment_output.gdb",
        output_name="features_with_attachments",
        in_place=False,
        report_csv=report_csv,
        missing_report_csv=output_folder / "features_missing_attachments.csv",
        run_summary_csv=output_folder / "attachment_run_summary.csv",
        recursive=recursive,
        filename_regex=None,
        max_mb=max_mb,
        size_only=size_only,
        attach_to_all_matches=False,
        attach=False,
        overwrite_output=False,
        overwrite_online=False,
        allow_incomplete_overwrite=False,
        ignore_unmatched_files=False,
        ignore_missing_features=False,
        existing_attachment_policy="skip",
        service_name=None,
        aprx="CURRENT",
        map_name="Attachment Publish",
        layer_name=None,
        portal_folder=None,
        summary="Feature layer with file attachments.",
        tags="attachments",
        log_level="INFO",
        log_file=None,
    )
    if size_only:
        return args

    args.input_features = ask("Input feature layer or feature class")
    args.key_field = ask("Feature key field")
    args.missing_report_csv = Path(
        ask("Missing feature report CSV", str(output_folder / "features_missing_attachments.csv"))
    ).expanduser()
    copy_features = ask_bool("Copy input features before attaching", True)
    args.in_place = not copy_features
    if copy_features:
        args.output_gdb = Path(ask("Output file geodatabase", str(output_folder / "attachment_output.gdb"))).expanduser()
        args.output_name = ask("Output feature class name", "features_with_attachments")
    args.attach_to_all_matches = ask_bool("Attach one file to every feature with the same key", True)
    args.attach = ask_bool("Add attachments now", False)
    args.overwrite_output = args.attach and ask_bool("Overwrite existing local output/match table if needed", False)
    if args.attach:
        args.existing_attachment_policy = ask_choice(
            "Existing matching attachments policy", ["skip", "replace", "allow"], "skip"
        )
    args.overwrite_online = args.attach and ask_bool("Overwrite hosted feature layer after attaching", False)
    if args.overwrite_online:
        args.service_name = ask("Hosted feature layer service name")
        args.portal_folder = ask("Portal folder", "") or None
        args.layer_name = ask("Published layer name", args.output_name)
    return args


def _expand_path(value: Path | None) -> Path | None:
    return value.expanduser() if value else None


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    for attr in [
        "plats_dir",
        "overlay_dir",
        "output_gdb",
        "report_csv",
        "missing_report_csv",
        "run_summary_csv",
        "config",
        "log_file",
    ]:
        if hasattr(args, attr):
            setattr(args, attr, _expand_path(getattr(args, attr)))
    return args


def validate_args(args: argparse.Namespace) -> None:
    if not args.plats_dir or not args.plats_dir.is_dir():
        raise SystemExit(f"Not a folder: {args.plats_dir}")
    if args.overlay_dir and not args.overlay_dir.is_dir():
        raise SystemExit(f"Not an overlay folder: {args.overlay_dir}")
    if not args.size_only and (not args.input_features or not args.key_field):
        raise SystemExit("--input-features and --key-field are required unless --size-only is used.")
    if args.max_mb <= 0:
        raise SystemExit("--max-mb must be greater than 0.")
    if args.filename_regex:
        try:
            re.compile(args.filename_regex, re.I)
        except re.error as exc:
            raise SystemExit(f"Invalid --filename-regex: {exc}") from exc
    if args.overwrite_online and (not args.attach or not args.service_name):
        raise SystemExit("--overwrite-online requires --attach and --service-name.")
    if args.size_only and args.attach:
        raise SystemExit("--size-only cannot be combined with --attach.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    examples = """
Examples:
  Size report only:
    python attach_plats_to_feature_layer.py --size-only --attachments-dir path\\to\\attachments --recursive

  Dry-run matching report:
    python attach_plats_to_feature_layer.py --input-features path\\to\\data.gdb\\features --key-field FEATURE_KEY --attachments-dir path\\to\\attachments --recursive

  Attach to a copied local feature class:
    python attach_plats_to_feature_layer.py --input-features path\\to\\data.gdb\\features --key-field FEATURE_KEY --attachments-dir path\\to\\attachments --recursive --attach --overwrite-output

  Attach and then overwrite a hosted feature layer:
    python attach_plats_to_feature_layer.py --input-features path\\to\\data.gdb\\features --key-field FEATURE_KEY --attachments-dir path\\to\\attachments --recursive --attach --overwrite-output --overwrite-online --service-name HostedFeatureLayerName
"""
    parser = argparse.ArgumentParser(
        description="Attach local files to ArcGIS features by matching normalized filenames to a feature key field.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=examples,
    )
    parser.add_argument("--version", action="version", version=f"plat-attachment-loader {__version__}")
    parser.add_argument("--input-features", help="Local ArcGIS Pro layer or feature class.")
    parser.add_argument(
        "--attachments-dir",
        "--plats-dir",
        dest="plats_dir",
        required=True,
        type=Path,
        help="Folder containing source attachment files. --plats-dir is kept as a backward-compatible alias.",
    )
    parser.add_argument("--overlay-dir", type=Path, help="Optional prepared/reduced file folder whose files replace base files.")
    parser.add_argument(
        "--overlay-match-by",
        choices=["relative-path", "normalized-name"],
        default="relative-path",
        help="How overlay files replace base files. Default: relative-path.",
    )
    parser.add_argument("--key-field", help="Feature field whose values match attachment filenames.")
    parser.add_argument("--config", type=Path, help="Optional JSON config for drop words, aliases, and extensions.")
    parser.add_argument(
        "--extensions",
        help="Comma-separated extensions to scan, such as '.pdf,.tif,.jpg'. Overrides config extensions.",
    )
    parser.add_argument("--output-gdb", type=Path, default=Path("attachment_output.gdb"))
    parser.add_argument("--output-name", default="features_with_attachments")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Attach directly to --input-features instead of copying to --output-gdb first.",
    )
    parser.add_argument("--report-csv", type=Path, default=Path("attachment_report.csv"))
    parser.add_argument(
        "--missing-report-csv",
        type=Path,
        help="CSV of feature rows that will not receive, or still do not have, expected attachments.",
    )
    parser.add_argument("--run-summary-csv", type=Path, help="Optional one-row CSV summary of the run.")
    parser.add_argument("--recursive", action="store_true", help="Scan attachment folders recursively.")
    parser.add_argument("--filename-regex", help="Regex with named group (?P<name>...) or a first capture group.")
    parser.add_argument("--max-mb", type=float, default=10.0)
    parser.add_argument("--size-only", action="store_true", help="Only write a size report; do not import arcpy or read features.")
    parser.add_argument("--attach-to-all-matches", action="store_true", help="Attach one file to every feature with the same key.")
    parser.add_argument("--attach", action="store_true", help="Add attachments. Without this, only reports are written.")
    parser.add_argument("--overwrite-output", action="store_true", help="Replace existing copied output feature class or match table.")
    parser.add_argument(
        "--existing-attachment-policy",
        choices=["skip", "replace", "allow"],
        default="skip",
        help="What to do when the same filename is already attached to the target ObjectID. Default: skip.",
    )
    parser.add_argument("--overwrite-online", action="store_true", help="Overwrite hosted feature layer after attaching.")
    parser.add_argument(
        "--allow-incomplete-overwrite",
        action="store_true",
        help="Allow hosted overwrite even when file-side or feature-side QA is incomplete.",
    )
    parser.add_argument(
        "--ignore-unmatched-files",
        action="store_true",
        help="Do not treat extra unmatched files as hosted-overwrite blockers.",
    )
    parser.add_argument(
        "--ignore-missing-features",
        action="store_true",
        help="Do not treat features with no attachable matching file as hosted-overwrite blockers.",
    )
    parser.add_argument("--service-name", help="Hosted feature layer service name to overwrite.")
    parser.add_argument("--aprx", default="CURRENT")
    parser.add_argument("--map-name", default="Attachment Publish")
    parser.add_argument("--layer-name")
    parser.add_argument("--portal-folder")
    parser.add_argument("--summary", default="Feature layer with file attachments.")
    parser.add_argument("--tags", default="attachments")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    parser.add_argument("--log-file", type=Path)
    return parser.parse_args(argv)


def print_report_summary(report_csv: Path, missing_report_csv: Path | None, statuses: dict[str, int], attachable_rows: int, missing_rows: int) -> None:
    print(f"Report: {report_csv}")
    if missing_report_csv:
        print(f"Missing feature report: {missing_report_csv}")
    print(f"Status counts: {statuses}")
    print(f"Attachable rows: {attachable_rows}")
    print(f"Features without an attachable/verified attachment: {missing_rows}")


def main(argv: list[str] | None = None) -> int:
    raw_args = sys.argv[1:] if argv is None else argv
    args = interactive_args() if not raw_args else parse_args(raw_args)
    args = normalize_args(args)
    configure_logging(args.log_level, args.log_file)
    validate_args(args)

    config = load_matching_config(args.config, args.extensions)
    LOGGER.info("Scanning attachments in %s", args.plats_dir)
    plats = scan_plats(
        args.plats_dir,
        args.recursive,
        args.filename_regex,
        config,
        args.overlay_dir,
        args.overlay_match_by,
    )
    if not plats:
        raise SystemExit(f"No supported attachment files found in {args.plats_dir}. Extensions: {sorted(config.extensions)}")

    metadata = default_metadata(args.input_features, args.plats_dir, args.overlay_dir, args.key_field, args.max_mb)
    if args.size_only:
        rows = size_rows(plats, args.max_mb, config)
        write_attachment_report(args.report_csv, rows, metadata)
        statuses = summarize_statuses(rows)
        oversized = statuses.get("too_large", 0)
        print(f"Report: {args.report_csv}")
        print(f"Files scanned: {len(rows)}")
        print(f"Files over {args.max_mb:g} MB: {oversized}")
        if args.run_summary_csv:
            write_summary_report(args.run_summary_csv, metadata, len(rows), 0, 0, statuses)
            print(f"Run summary: {args.run_summary_csv}")
        return 2 if oversized else 0

    arcpy = load_arcpy()
    validate_feature_inputs(arcpy, args.input_features, args.key_field)

    if args.attach and not args.in_place:
        fc = make_output(arcpy, args.input_features, args.output_gdb, args.output_name, args.overwrite_output)
    else:
        fc = args.input_features

    found = index_features(arcpy, fc, args.key_field, config)
    report, attach_rows = build_plan(args.max_mb, args.attach_to_all_matches, plats, found, config)
    lookup = plat_lookup(plats, config)
    features = feature_rows(arcpy, fc, args.key_field)
    missing_report_csv = args.missing_report_csv or args.report_csv.with_name(f"{args.report_csv.stem}_missing_features.csv")
    planned_oids = {int(row["oid"]) for row in attach_rows if row.get("oid") not in (None, "")}
    pre_missing_rows = missing_polygon_rows(features, args.key_field, lookup, args.max_mb, config, planned=planned_oids)
    statuses = summarize_statuses(report)

    write_attachment_report(args.report_csv, report, metadata)
    write_missing_report(missing_report_csv, args.key_field, pre_missing_rows, metadata)
    if args.run_summary_csv:
        write_summary_report(args.run_summary_csv, metadata, len(report), len(attach_rows), len(pre_missing_rows), statuses)

    print_report_summary(args.report_csv, missing_report_csv, statuses, len(attach_rows), len(pre_missing_rows))

    file_blockers = unresolved(report, ignore_unmatched_files=args.ignore_unmatched_files)
    feature_blockers = [] if args.ignore_missing_features else pre_missing_rows
    if args.overwrite_online and (file_blockers or feature_blockers) and not args.allow_incomplete_overwrite:
        print(
            "Stopped before attaching or overwriting because hosted overwrite would be incomplete. "
            f"File-side blockers: {len(file_blockers)}. Feature-side blockers: {len(feature_blockers)}."
        )
        print(
            "Fix the reports, pass --ignore-unmatched-files/--ignore-missing-features for intentional exceptions, "
            "or pass --allow-incomplete-overwrite to override all blockers."
        )
        return 4

    if not args.attach:
        print("Dry run only. Add --attach when the reports look right.")
        return 0
    if not attach_rows:
        raise SystemExit("No matched files to attach.")

    existing_before = existing_attachment_names_by_oid(arcpy, fc)
    skipped_existing: list[dict] = []
    rows_to_attach = attach_rows
    if args.existing_attachment_policy == "skip":
        rows_to_attach, skipped_existing = filter_duplicate_attachment_rows(attach_rows, existing_before)
        if skipped_existing:
            print(f"Skipped existing matching attachments: {len(skipped_existing)}")
    elif args.existing_attachment_policy == "replace":
        deleted = delete_existing_attachments(arcpy, fc, attach_rows)
        print(f"Deleted existing matching attachments before replacement: {deleted}")
    elif args.existing_attachment_policy == "allow":
        print("Duplicate attachments are allowed for this run.")

    match_table = ""
    if rows_to_attach:
        match_table = add_attachments(arcpy, fc, args.output_gdb, rows_to_attach, args.overwrite_output)
    else:
        print("No new attachment rows were needed; all planned files were already attached.")

    existing_after = existing_attachment_names_by_oid(arcpy, fc)
    missing_planned = missing_planned_attachment_rows(attach_rows, existing_after)
    verified_oids = verified_attached_oids(attach_rows, existing_after)
    post_missing_rows = missing_polygon_rows(features, args.key_field, lookup, args.max_mb, config, verified_oids)
    write_missing_report(missing_report_csv, args.key_field, post_missing_rows, metadata)
    if args.run_summary_csv:
        write_summary_report(args.run_summary_csv, metadata, len(report), len(attach_rows), len(post_missing_rows), statuses)

    count = attachment_count(arcpy, fc)
    rel = attachment_relationship(arcpy, fc)
    print(f"Attached to: {fc}")
    if match_table:
        print(f"Match table: {match_table}")
    print(f"Attachment table: {attachment_table(arcpy, fc) or 'not found'}")
    print(f"Attachment relationship: {rel or 'not found'}")
    if count is None:
        print("Attachment table was not found for verification.")
    else:
        print(f"Total attachment rows in feature class: {count}")
    print(f"Planned attachment rows still missing after verification: {len(missing_planned)}")
    print(f"Features still without verified expected attachments: {len(post_missing_rows)}")

    if args.overwrite_online:
        post_feature_blockers = [] if args.ignore_missing_features else post_missing_rows
        if (missing_planned or post_feature_blockers) and not args.allow_incomplete_overwrite:
            print(
                "Stopped before hosted overwrite because post-attachment verification found problems. "
                f"Missing planned rows: {len(missing_planned)}. Feature-side blockers: {len(post_feature_blockers)}."
            )
            return 5
        overwrite_online(arcpy, fc, args)
        print(f"Overwrote hosted service: {args.service_name}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
