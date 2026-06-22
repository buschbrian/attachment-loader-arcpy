"""Configuration helpers for filename normalization and file scanning."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Mapping

DEFAULT_EXTENSIONS = {".pdf", ".tif", ".tiff"}
DEFAULT_DROP_WORDS = {
    "A",
    "AN",
    "AND",
    "FINAL",
    "MAP",
    "OF",
    "PLAT",
    "RECORDED",
    "RECORD",
    "REPLAT",
    "SUB",
    "SUBD",
    "SUBDIVISION",
    "THE",
}
DEFAULT_ALIASES = {
    "ADDITION": "ADDN",
    "AMENDED": "AMD",
    "AMENDMENT": "AMD",
    "CONDOMINIUM": "CONDO",
    "CONDOMINIUMS": "CONDO",
}


@dataclass(frozen=True)
class MatchingConfig:
    """Settings that control file discovery and normalized key matching."""

    drop_words: frozenset[str]
    aliases: Mapping[str, str]
    extensions: frozenset[str]

    @classmethod
    def defaults(cls) -> "MatchingConfig":
        return cls(
            drop_words=frozenset(DEFAULT_DROP_WORDS),
            aliases=dict(DEFAULT_ALIASES),
            extensions=frozenset(DEFAULT_EXTENSIONS),
        )


def normalize_extension(value: str) -> str:
    """Return a lowercase file extension that starts with a dot."""

    value = value.strip().lower()
    if not value:
        return value
    return value if value.startswith(".") else f".{value}"


def parse_extensions(values: str | Iterable[str] | None) -> frozenset[str]:
    """Parse comma-separated or iterable extension settings."""

    if values is None:
        return frozenset(DEFAULT_EXTENSIONS)
    if isinstance(values, str):
        parts = [part.strip() for part in values.split(",")]
    else:
        parts = [str(part).strip() for part in values]
    parsed = {normalize_extension(part) for part in parts if normalize_extension(part)}
    return frozenset(parsed or DEFAULT_EXTENSIONS)


def _upper_set(values: Iterable[object]) -> set[str]:
    return {str(value).strip().upper() for value in values if str(value).strip()}


def _upper_aliases(values: Mapping[object, object]) -> dict[str, str]:
    return {
        str(key).strip().upper(): str(value).strip().upper()
        for key, value in values.items()
        if str(key).strip() and str(value).strip()
    }


def load_matching_config(config_path: Path | None = None, extensions_override: str | None = None) -> MatchingConfig:
    """Load matching settings from JSON and merge them with safe defaults.

    Supported JSON keys:
      - drop_words: list[str]
      - aliases: dict[str, str]
      - extensions: list[str] or comma-separated str
      - merge_with_defaults: bool, defaults to true

    When merge_with_defaults is false, the JSON values fully replace defaults.
    The command-line extension override always wins over JSON extensions.
    """

    defaults = MatchingConfig.defaults()
    if config_path is None:
        config = defaults
    else:
        try:
            raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise SystemExit(f"Could not read config file: {config_path}\n{exc}") from exc
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON config file: {config_path}\n{exc}") from exc
        if not isinstance(raw, dict):
            raise SystemExit("Config JSON must contain an object at the top level.")

        merge = bool(raw.get("merge_with_defaults", True))
        drop_words = set(defaults.drop_words) if merge else set()
        aliases = dict(defaults.aliases) if merge else {}
        extensions = set(defaults.extensions) if merge else set()

        if "drop_words" in raw:
            if not isinstance(raw["drop_words"], list):
                raise SystemExit("Config key 'drop_words' must be a list of words.")
            drop_words.update(_upper_set(raw["drop_words"]))
        if "aliases" in raw:
            if not isinstance(raw["aliases"], dict):
                raise SystemExit("Config key 'aliases' must be an object/dictionary.")
            aliases.update(_upper_aliases(raw["aliases"]))
        if "extensions" in raw:
            extensions = set(parse_extensions(raw["extensions"])) if not merge else extensions | set(parse_extensions(raw["extensions"]))

        config = MatchingConfig(
            drop_words=frozenset(drop_words),
            aliases=aliases,
            extensions=frozenset(extensions or DEFAULT_EXTENSIONS),
        )

    if extensions_override:
        config = MatchingConfig(
            drop_words=config.drop_words,
            aliases=config.aliases,
            extensions=parse_extensions(extensions_override),
        )
    return config
