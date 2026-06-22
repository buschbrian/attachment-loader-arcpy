"""Pure-Python matching and file scanning functions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .config import MatchingConfig


@dataclass(frozen=True)
class PlatFile:
    """A source attachment file discovered on disk."""

    path: Path
    raw_name: str
    size_bytes: int

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1024 / 1024


def norm(value: object, config: MatchingConfig) -> str:
    """Normalize feature values and filenames so they can be compared.

    None becomes an empty key, but falsy values like 0 remain valid keys.
    """

    raw = "" if value is None else str(value)
    text = re.sub(r"[^A-Z0-9 ]+", " ", raw.upper().replace("&", " AND "))
    return " ".join(config.aliases.get(word, word) for word in text.split() if word not in config.drop_words)


def name_from_file(path: Path, regex: str | None) -> str:
    """Return the candidate matching name for a file.

    If regex is supplied, a named group called 'name' wins. Otherwise the first
    capture group wins. If the regex does not match, the filename stem is used.
    """

    if not regex:
        return path.stem
    match = re.search(regex, path.name, re.I)
    if not match:
        return path.stem
    return match.groupdict().get("name") or (match.group(1) if match.groups() else match.group(0))


def scan_one_folder(folder: Path, recursive: bool, regex: str | None, config: MatchingConfig) -> list[PlatFile]:
    """Scan one folder for supported attachment files."""

    paths = folder.rglob("*") if recursive else folder.glob("*")
    rows: list[PlatFile] = []
    for path in sorted(paths):
        if path.is_file() and path.suffix.lower() in config.extensions:
            rows.append(PlatFile(path=path.resolve(), raw_name=name_from_file(path, regex), size_bytes=path.stat().st_size))
    return rows


def scan_plats(
    folder: Path,
    recursive: bool,
    regex: str | None,
    config: MatchingConfig,
    overlay_dir: Path | None = None,
    overlay_match_by: str = "relative-path",
) -> list[PlatFile]:
    """Scan base and optional overlay folders.

    The overlay folder can replace base files either by relative path or by
    normalized filename. Relative path is safest when the overlay mirrors the
    source folder. Normalized name is useful when compressed/reduced files live
    in a flat folder.
    """

    if overlay_match_by not in {"relative-path", "normalized-name"}:
        raise SystemExit("--overlay-match-by must be 'relative-path' or 'normalized-name'.")

    files: dict[str, PlatFile] = {}
    for base in [folder, overlay_dir]:
        if base is None:
            continue
        resolved_base = base.resolve()
        for row in scan_one_folder(resolved_base, recursive, regex, config):
            if overlay_match_by == "normalized-name":
                rel_key = norm(row.raw_name, config) or row.path.stem.upper()
            else:
                rel_key = row.path.relative_to(resolved_base).as_posix().lower()
            files[rel_key] = row
    return [files[key] for key in sorted(files)]
