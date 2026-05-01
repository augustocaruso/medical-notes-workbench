"""Configuration and resolved path helpers for Wiki workflows."""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None

from wiki.common import MissingPathError, ValidationError

DEFAULT_RAW_DIR = r"C:\Users\leona\OneDrive\Chats_Raw"
DEFAULT_WIKI_DIR = r"C:\Users\leona\iCloudDrive\iCloud~md~obsidian\Wiki_Medicina"
DEFAULT_CATALOG_PATH = "~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json"
DEFAULT_LINKER_PATH = r"C:\Users\leona\.gemini\skills\med-auto-linker\med_linker.py"


@dataclass(frozen=True)
class MedConfig:
    raw_dir: Path
    wiki_dir: Path
    linker_path: Path
    catalog_path: Path


def _path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


def _read_toml(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    if tomllib is None:
        raise ValidationError("tomllib unavailable; use Python 3.11+ for config.toml support")
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _find_config(explicit: str | None) -> Path | None:
    if explicit:
        return _path(explicit)
    candidates: list[Path] = []
    cwd = Path.cwd().resolve()
    candidates.extend(parent / "config.toml" for parent in (cwd, *cwd.parents))
    script = Path(__file__).resolve()
    candidates.extend(parent / "config.toml" for parent in script.parents)
    return next((candidate for candidate in candidates if candidate.exists()), None)


def resolve_config(args: argparse.Namespace) -> MedConfig:
    cfg = _read_toml(_find_config(getattr(args, "config", None)))
    section = cfg.get("chat_processor", {}) if isinstance(cfg.get("chat_processor", {}), dict) else {}

    def pick(name: str, env: str, default: str) -> Path:
        cli_value = getattr(args, name, None)
        value = cli_value or os.getenv(env) or section.get(name) or default
        return _path(str(value))

    linker_value = getattr(args, "linker_path", None) or os.getenv("MED_LINKER_PATH") or section.get("linker_path")
    if linker_value:
        linker_path = _path(str(linker_value))
    else:
        bundled = _bundled_linker_path()
        linker_path = bundled if bundled.exists() else _path(DEFAULT_LINKER_PATH)

    return MedConfig(
        raw_dir=pick("raw_dir", "MED_RAW_DIR", DEFAULT_RAW_DIR),
        wiki_dir=pick("wiki_dir", "MED_WIKI_DIR", DEFAULT_WIKI_DIR),
        linker_path=linker_path,
        catalog_path=pick("catalog_path", "MED_CATALOG_PATH", DEFAULT_CATALOG_PATH),
    )


def _bundled_linker_path() -> Path:
    return Path(__file__).resolve().parents[1] / "med_linker.py"


def validate_config(config: MedConfig) -> dict[str, Any]:
    return {
        "raw_dir": str(config.raw_dir),
        "raw_dir_exists": config.raw_dir.exists(),
        "wiki_dir": str(config.wiki_dir),
        "wiki_dir_exists": config.wiki_dir.exists(),
        "catalog_path": str(config.catalog_path),
        "catalog_path_exists": config.catalog_path.exists(),
        "linker_path": str(config.linker_path),
        "linker_path_exists": config.linker_path.exists(),
    }
