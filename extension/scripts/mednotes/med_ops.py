#!/usr/bin/env python3
"""Deterministic file/YAML operations for the Medical Notes Workbench pipeline.

The Gemini agent owns clinical reasoning. This script owns filesystem changes:
frontmatter status updates, non-overwriting note writes, manifest publishing, and
the optional semantic linker call.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import wiki_note_style  # noqa: E402


DEFAULT_RAW_DIR = r"C:\Users\leona\OneDrive\Chats_Raw"
DEFAULT_WIKI_DIR = r"C:\Users\leona\iCloudDrive\iCloud~md~obsidian\Wiki_Medicina"
DEFAULT_CATALOG_PATH = "~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json"
DEFAULT_LINKER_PATH = r"C:\Users\leona\.gemini\skills\med-auto-linker\med_linker.py"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_MISSING = 4
EXIT_IO = 5
EXIT_LINKER = 6

MIGRATION_PLAN_SCHEMA = "medical-notes-workbench.taxonomy-migration-plan.v1"
MIGRATION_RECEIPT_SCHEMA = "medical-notes-workbench.taxonomy-migration-receipt.v1"

_FRONTMATTER_DELIM = "---"
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_UNSAFE_TITLE_RE = re.compile(r'[\\/*?:"<>|\x00-\x1f]')
_UNSAFE_TAXONOMY_RE = re.compile(r'[<>:"|?*\x00-\x1f]')
_NEAR_DUPLICATE_CUTOFF = 0.9

CANONICAL_TAXONOMY: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "1. Clínica Médica",
        (
            "Cardiologia",
            "Clínica Médica",
            "Dermatologia",
            "Endocrinologia",
            "Gastroenterologia",
            "Geriatria",
            "Hematologia",
            "Infectologia",
            "Medicina Interna",
            "Nefrologia",
            "Neurologia",
            "Oncologia",
            "Pneumologia",
            "Reumatologia",
            "Psiquiatria",
        ),
    ),
    (
        "2. Cirurgia",
        (
            "Cirurgia Geral",
            "Clínica Cirúrgica",
            "Oftalmologia",
            "Urologia",
            "Trauma",
            "Anestesiologia",
        ),
    ),
    (
        "3. Ginecologia e Obstetrícia",
        (
            "Ginecologia e Obstetrícia",
        ),
    ),
    (
        "4. Pediatria",
        (
            "Pediatria",
            "Neonatologia",
            "Puericultura",
            "Infecto Pediátrica",
        ),
    ),
    (
        "5. Medicina Preventiva",
        (
            "Medicina Preventiva",
            "SUS",
            "Epidemiologia",
            "Ética Médica",
            "Saúde do Trabalho",
        ),
    ),
)

CANONICAL_TAXONOMY_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("Clinica Medica", "1. Clínica Médica", "Clínica Médica"),
    ("Clínica Médica", "1. Clínica Médica", "Clínica Médica"),
    ("Medicina Interna", "1. Clínica Médica", "Medicina Interna"),
    ("Cirurgia_Geral", "2. Cirurgia", "Cirurgia Geral"),
    ("Cirurgia Geral", "2. Cirurgia", "Cirurgia Geral"),
    ("Clinica Cirurgica", "2. Cirurgia", "Clínica Cirúrgica"),
    ("Clínica Cirúrgica", "2. Cirurgia", "Clínica Cirúrgica"),
    ("Ginecologia_Obstetricia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Ginecologia e Obstetricia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Ginecologia e Obstetrícia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Ginecologia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Obstetricia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Obstetrícia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Infecto Pediatrica", "4. Pediatria", "Infecto Pediátrica"),
    ("Infecto Pediátrica", "4. Pediatria", "Infecto Pediátrica"),
    ("Infectopediatria", "4. Pediatria", "Infecto Pediátrica"),
    ("Etica Medica", "5. Medicina Preventiva", "Ética Médica"),
    ("Ética Médica", "5. Medicina Preventiva", "Ética Médica"),
    ("Saude do Trabalho", "5. Medicina Preventiva", "Saúde do Trabalho"),
    ("Saúde do Trabalho", "5. Medicina Preventiva", "Saúde do Trabalho"),
)


class MedOpsError(Exception):
    """Base exception carrying a process exit code."""

    exit_code = EXIT_IO


class ValidationError(MedOpsError):
    exit_code = EXIT_VALIDATION


class MissingPathError(MedOpsError):
    exit_code = EXIT_MISSING


class CollisionError(MedOpsError):
    exit_code = EXIT_VALIDATION


@dataclass(frozen=True)
class MedConfig:
    raw_dir: Path
    wiki_dir: Path
    linker_path: Path
    catalog_path: Path


@dataclass(frozen=True)
class TaxonomyResolution:
    requested_taxonomy: str
    taxonomy: str
    parts: tuple[str, ...]
    canonicalized: tuple[dict[str, str], ...]
    new_dirs: tuple[str, ...]

    @property
    def has_new_dirs(self) -> bool:
        return bool(self.new_dirs)

    def to_json(self, wiki_dir: Path, title: str | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "wiki_dir": str(wiki_dir),
            "requested_taxonomy": self.requested_taxonomy,
            "taxonomy": self.taxonomy,
            "parts": list(self.parts),
            "canonicalized": list(self.canonicalized),
            "new_dirs": list(self.new_dirs),
            "requires_new_folder": self.has_new_dirs,
        }
        if title is not None:
            data["title"] = title
            data["target_path"] = str(wiki_dir.joinpath(*self.parts, f"{safe_title(title)}.md"))
        return data


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    return Path(__file__).resolve().with_name("med_linker.py")


def split_frontmatter(text: str) -> tuple[list[str] | None, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return None, text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_DELIM:
            return lines[1:idx], "".join(lines[idx + 1 :])
    return None, text


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> dict[str, str]:
    frontmatter, _body = split_frontmatter(text)
    if frontmatter is None:
        return {}
    parsed: dict[str, str] = {}
    for line in frontmatter:
        match = _KEY_RE.match(line.strip())
        if match:
            parsed[match.group(1)] = _strip_quotes(match.group(2))
    return parsed


def _format_yaml_value(value: str) -> str:
    if value == "":
        return '""'
    if re.match(r"^[A-Za-z0-9_./@+-]+$", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def update_frontmatter(text: str, updates: dict[str, str]) -> str:
    frontmatter, body = split_frontmatter(text)
    formatted = {key: f"{key}: {_format_yaml_value(value)}\n" for key, value in updates.items()}
    if frontmatter is None:
        return "---\n" + "".join(formatted.values()) + "---\n" + text

    seen: set[str] = set()
    out: list[str] = []
    for line in frontmatter:
        match = _KEY_RE.match(line.strip())
        if match and match.group(1) in formatted:
            key = match.group(1)
            out.append(formatted[key])
            seen.add(key)
        else:
            out.append(line)
    for key, line in formatted.items():
        if key not in seen:
            out.append(line)
    return "---\n" + "".join(out) + "---\n" + body


def read_note_meta(path: Path) -> dict[str, str]:
    try:
        return parse_frontmatter(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MissingPathError(f"File not found: {path}") from exc


def _backup_path(path: Path) -> Path:
    base = path.with_name(path.name + ".bak")
    if not base.exists():
        return base
    for idx in range(1, 1000):
        candidate = path.with_name(f"{path.name}.bak.{idx}")
        if not candidate.exists():
            return candidate
    raise ValidationError(f"Too many backups already exist for {path}")


def create_backup(path: Path) -> Path:
    if not path.exists():
        raise MissingPathError(f"File not found: {path}")
    backup = _backup_path(path)
    shutil.copy2(path, backup)
    return backup


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def mutate_raw_frontmatter(raw_file: Path, updates: dict[str, str], dry_run: bool = False, backup: bool = False) -> dict[str, Any]:
    if not raw_file.exists():
        raise MissingPathError(f"Raw file not found: {raw_file}")
    original = raw_file.read_text(encoding="utf-8")
    updated = update_frontmatter(original, updates)
    if dry_run:
        return {"raw_file": str(raw_file), "backup": None, "updated": False, "updates": updates}
    backup_path = create_backup(raw_file) if backup else None
    atomic_write_text(raw_file, updated)
    return {"raw_file": str(raw_file), "backup": str(backup_path) if backup_path else None, "updated": True, "updates": updates}


def list_raw_files(raw_dir: Path) -> list[Path]:
    if not raw_dir.exists():
        raise MissingPathError(f"Raw dir not found: {raw_dir}")
    return sorted(path for path in raw_dir.glob("*.md") if path.is_file())


def raw_summary(path: Path) -> dict[str, str]:
    meta = read_note_meta(path)
    return {
        "path": str(path),
        "status": meta.get("status", ""),
        "tipo": meta.get("tipo", ""),
        "titulo_triagem": meta.get("titulo_triagem", ""),
        "fonte_id": meta.get("fonte_id", ""),
    }


def list_by_status(raw_dir: Path, mode: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in list_raw_files(raw_dir):
        item = raw_summary(path)
        status = item["status"].lower()
        tipo = item["tipo"].lower()
        if mode == "pending" and status in {"", "pendente"}:
            rows.append(item)
        elif mode == "triados" and status == "triado" and tipo == "medicina":
            rows.append(item)
    return rows


def normalize_taxonomy(taxonomy: str) -> tuple[str, ...]:
    taxonomy = taxonomy.strip()
    if not taxonomy:
        raise ValidationError("Taxonomy cannot be empty")
    if _DRIVE_RE.match(taxonomy):
        raise ValidationError(f"Taxonomy must be relative, got drive path: {taxonomy}")
    normalized = taxonomy.replace("\\", "/")
    if normalized.startswith("/") or PureWindowsPath(normalized).is_absolute():
        raise ValidationError(f"Taxonomy must be relative: {taxonomy}")
    parts = tuple(part.strip() for part in normalized.split("/"))
    if any(not part for part in parts):
        raise ValidationError(f"Taxonomy has an empty segment: {taxonomy}")
    if any(part in {".", ".."} for part in parts):
        raise ValidationError(f"Taxonomy cannot contain '.' or '..': {taxonomy}")
    bad = [part for part in parts if _UNSAFE_TAXONOMY_RE.search(part)]
    if bad:
        raise ValidationError(f"Taxonomy has unsafe characters: {bad[0]}")
    folded = [_fold_taxonomy_segment(part) for part in parts]
    empty = [part for part, folded_part in zip(parts, folded) if not folded_part]
    if empty:
        raise ValidationError(f"Taxonomy segment must contain letters or numbers: {empty[0]}")
    for idx in range(1, len(folded)):
        if folded[idx] == folded[idx - 1]:
            raise ValidationError(f"Taxonomy has duplicated adjacent segments: {parts[idx - 1]}/{parts[idx]}")
    return parts


def safe_title(title: str) -> str:
    cleaned = _UNSAFE_TITLE_RE.sub("", title).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise ValidationError("Title produced an empty filename")
    return cleaned


def _style_report_error_message(report: dict[str, Any]) -> str:
    messages = [str(item.get("message", item.get("code", ""))) for item in report.get("errors", [])]
    return "Generated Wiki note does not match the Wiki_Medicina style contract: " + "; ".join(messages)


def validate_wiki_note_contract(content: str, *, title: str, raw_file: Path) -> dict[str, Any]:
    """Reject generated Wiki_Medicina notes that drift from the house style."""

    report = wiki_note_style.validate_note_style(
        content,
        title=title,
        raw_meta=read_note_meta(raw_file),
        path=str(raw_file),
    )
    if report["errors"]:
        raise ValidationError(_style_report_error_message(report))
    return report


def _fold_taxonomy_segment(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", without_accents.casefold())


def _canonical_roots_by_fold() -> dict[str, str]:
    return {_fold_taxonomy_segment(root): root for root, _specialties in CANONICAL_TAXONOMY}


def _canonical_specialties_by_fold() -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    for root, specialties in CANONICAL_TAXONOMY:
        for specialty in specialties:
            mapping[_fold_taxonomy_segment(specialty)] = (root, specialty)
            mapping[_fold_taxonomy_segment(specialty.replace(" ", "_"))] = (root, specialty)
    for alias, root, specialty in CANONICAL_TAXONOMY_ALIASES:
        mapping[_fold_taxonomy_segment(alias)] = (root, specialty)
    return mapping


def _canonical_specialties_for_root(root: str) -> dict[str, str]:
    specialties = next((items for candidate, items in CANONICAL_TAXONOMY if candidate == root), ())
    mapping = {_fold_taxonomy_segment(specialty): specialty for specialty in specialties}
    for alias, alias_root, specialty in CANONICAL_TAXONOMY_ALIASES:
        if alias_root == root:
            mapping[_fold_taxonomy_segment(alias)] = specialty
    return mapping


def canonical_taxonomy_tree() -> dict[str, Any]:
    areas = []
    for root, specialties in CANONICAL_TAXONOMY:
        areas.append({"area": root, "specialties": list(specialties)})
    return {"schema": "medical-notes-workbench.canonical-taxonomy.v1", "areas": areas}


def _canonicalize_taxonomy_parts(parts: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[dict[str, str], ...]]:
    roots = _canonical_roots_by_fold()
    specialties = _canonical_specialties_by_fold()
    first = parts[0]
    first_folded = _fold_taxonomy_segment(first)
    canonicalized: list[dict[str, str]] = []

    if first_folded in roots:
        root = roots[first_folded]
        if len(parts) == 1:
            raise ValidationError(f"Taxonomy must include a specialty under canonical area: {root}")
        root_specialties = _canonical_specialties_for_root(root)
        second = parts[1]
        second_folded = _fold_taxonomy_segment(second)
        if second_folded not in root_specialties:
            raise ValidationError(f"Unknown specialty under {root}: {second}")
        specialty = root_specialties[second_folded]
        canonical_parts = (root, specialty, *parts[2:])
        if canonical_parts[:2] != parts[:2]:
            canonicalized.append({"from": "/".join(parts[:2]), "to": "/".join(canonical_parts[:2]), "under": ""})
        return canonical_parts, tuple(canonicalized)

    if first_folded in specialties:
        root, specialty = specialties[first_folded]
        canonical_parts = (root, specialty, *parts[1:])
        canonicalized.append({"from": first, "to": "/".join(canonical_parts[:2]), "under": ""})
        return canonical_parts, tuple(canonicalized)

    root_names = ", ".join(root for root, _specialties in CANONICAL_TAXONOMY)
    raise ValidationError(
        f"Taxonomy must start with a canonical area or known specialty. Got: {first}. "
        f"Canonical areas: {root_names}"
    )


def _visible_child_dirs(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(
        (child for child in path.iterdir() if child.is_dir() and not child.name.startswith(".")),
        key=lambda child: _fold_taxonomy_segment(child.name),
    )


def _suggest_existing_segments(siblings: list[Path], requested: str) -> list[str]:
    folded_to_names: dict[str, list[str]] = {}
    for sibling in siblings:
        folded_to_names.setdefault(_fold_taxonomy_segment(sibling.name), []).append(sibling.name)
    requested_folded = _fold_taxonomy_segment(requested)
    close = difflib.get_close_matches(requested_folded, list(folded_to_names), n=4, cutoff=_NEAR_DUPLICATE_CUTOFF)
    suggestions: list[str] = []
    for folded in close:
        suggestions.extend(folded_to_names[folded])
    return suggestions


def _format_suggestions(suggestions: list[str]) -> str:
    if not suggestions:
        return ""
    return " Sugestões existentes: " + ", ".join(suggestions)


def _match_existing_segment(parent: Path, requested: str) -> tuple[str | None, list[str]]:
    siblings = _visible_child_dirs(parent)
    exact = [sibling.name for sibling in siblings if sibling.name == requested]
    if exact:
        return exact[0], []

    requested_folded = _fold_taxonomy_segment(requested)
    folded_matches = [sibling.name for sibling in siblings if _fold_taxonomy_segment(sibling.name) == requested_folded]
    if len(folded_matches) == 1:
        return folded_matches[0], []
    if len(folded_matches) > 1:
        raise ValidationError(
            f"Taxonomy segment is ambiguous under {parent}: {requested}. Matches: {', '.join(folded_matches)}"
        )
    return None, _suggest_existing_segments(siblings, requested)


def _validate_taxonomy_not_title(parts: tuple[str, ...], title: str) -> None:
    title_key = _fold_taxonomy_segment(safe_title(title))
    if parts and _fold_taxonomy_segment(parts[-1]) == title_key:
        raise ValidationError(
            "Taxonomy must be the folder/category path only; do not repeat the note title "
            f"as the final folder: taxonomy {'/'.join(parts)} + title {title}"
        )


def resolve_taxonomy(
    wiki_dir: Path,
    taxonomy: str,
    *,
    title: str | None = None,
    allow_new_leaf: bool = False,
) -> TaxonomyResolution:
    requested_parts = normalize_taxonomy(taxonomy)
    canonical_request_parts, alias_canonicalized = _canonicalize_taxonomy_parts(requested_parts)
    if title is not None:
        _validate_taxonomy_not_title(canonical_request_parts, title)
    if not wiki_dir.exists():
        raise MissingPathError(f"Wiki dir not found: {wiki_dir}")
    if not wiki_dir.is_dir():
        raise ValidationError(f"Wiki dir is not a directory: {wiki_dir}")

    canonical_parts: list[str] = []
    canonicalized: list[dict[str, str]] = list(alias_canonicalized)
    new_dirs: list[str] = []
    parent = wiki_dir

    for idx, requested in enumerate(canonical_request_parts):
        is_leaf = idx == len(canonical_request_parts) - 1
        matched, suggestions = _match_existing_segment(parent, requested)
        if matched is None:
            if is_leaf and allow_new_leaf and canonical_parts:
                if suggestions:
                    raise ValidationError(
                        f"New taxonomy leaf '{requested}' under {'/'.join(canonical_parts)} is too similar to "
                        f"an existing folder.{_format_suggestions(suggestions)}"
                    )
                canonical_parts.append(requested)
                new_dirs.append("/".join(canonical_parts))
                parent = parent / requested
                continue
            location = "/".join(canonical_parts) if canonical_parts else "<wiki-root>"
            raise ValidationError(
                f"Taxonomy segment must already exist under {location}: {requested}."
                f"{_format_suggestions(suggestions)}"
            )

        if matched != requested:
            canonicalized.append({"from": requested, "to": matched, "under": "/".join(canonical_parts)})
        canonical_parts.append(matched)
        parent = parent / matched

    resolved_parts = tuple(canonical_parts)
    if title is not None:
        _validate_taxonomy_not_title(resolved_parts, title)
    return TaxonomyResolution(
        requested_taxonomy="/".join(requested_parts),
        taxonomy="/".join(resolved_parts),
        parts=resolved_parts,
        canonicalized=tuple(canonicalized),
        new_dirs=tuple(new_dirs),
    )


def resolve_target_for_note(
    wiki_dir: Path,
    taxonomy: str,
    title: str,
    *,
    allow_new_taxonomy_leaf: bool = False,
) -> tuple[Path, TaxonomyResolution]:
    resolution = resolve_taxonomy(wiki_dir, taxonomy, title=title, allow_new_leaf=allow_new_taxonomy_leaf)
    return wiki_dir.joinpath(*resolution.parts, f"{safe_title(title)}.md"), resolution


def target_for_note(
    wiki_dir: Path,
    taxonomy: str,
    title: str,
    *,
    allow_new_taxonomy_leaf: bool = False,
) -> Path:
    target, _resolution = resolve_target_for_note(
        wiki_dir,
        taxonomy,
        title,
        allow_new_taxonomy_leaf=allow_new_taxonomy_leaf,
    )
    return target


def taxonomy_tree(wiki_dir: Path, max_depth: int = 0) -> dict[str, Any]:
    if not wiki_dir.exists():
        raise MissingPathError(f"Wiki dir not found: {wiki_dir}")
    if not wiki_dir.is_dir():
        raise ValidationError(f"Wiki dir is not a directory: {wiki_dir}")

    directories: list[dict[str, Any]] = []
    for path in sorted((p for p in wiki_dir.rglob("*") if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.as_posix()):
        rel = path.relative_to(wiki_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        depth = len(rel.parts)
        if max_depth and depth > max_depth:
            continue
        direct_notes = sum(1 for child in path.glob("*.md") if child.is_file())
        child_dirs = sum(1 for child in path.iterdir() if child.is_dir() and not child.name.startswith("."))
        directories.append(
            {
                "path": rel.as_posix(),
                "parts": list(rel.parts),
                "depth": depth,
                "direct_note_count": direct_notes,
                "child_dir_count": child_dirs,
            }
        )
    return {"wiki_dir": str(wiki_dir), "directory_count": len(directories), "directories": directories}


def _canonical_directory_paths() -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    for root, specialties in CANONICAL_TAXONOMY:
        paths.append((root,))
        paths.extend((root, specialty) for specialty in specialties)
    return paths


def taxonomy_audit(wiki_dir: Path) -> dict[str, Any]:
    if not wiki_dir.exists():
        raise MissingPathError(f"Wiki dir not found: {wiki_dir}")
    if not wiki_dir.is_dir():
        raise ValidationError(f"Wiki dir is not a directory: {wiki_dir}")

    roots = _canonical_roots_by_fold()
    specialties = _canonical_specialties_by_fold()
    canonical_paths = _canonical_directory_paths()
    missing_canonical_dirs = [
        "/".join(parts)
        for parts in canonical_paths
        if not wiki_dir.joinpath(*parts).exists()
    ]

    proposed_moves: list[dict[str, Any]] = []
    compliant_top_level_dirs: list[str] = []
    unmapped_top_level_dirs: list[str] = []
    top_level_dirs = _visible_child_dirs(wiki_dir)
    destinations: dict[str, list[str]] = {}

    for directory in top_level_dirs:
        folded = _fold_taxonomy_segment(directory.name)
        rel_source = directory.relative_to(wiki_dir).as_posix()
        if folded in roots:
            compliant_top_level_dirs.append(rel_source)
            continue
        if folded in specialties:
            root, specialty = specialties[folded]
            destination = "/".join((root, specialty))
            destinations.setdefault(destination, []).append(rel_source)
            proposed_moves.append(
                {
                    "source": rel_source,
                    "destination": destination,
                    "reason": "known_specialty_or_alias",
                    "destination_exists": wiki_dir.joinpath(root, specialty).exists(),
                }
            )
        else:
            unmapped_top_level_dirs.append(rel_source)

    duplicate_destinations = [
        {"destination": destination, "sources": sources}
        for destination, sources in sorted(destinations.items())
        if len(sources) > 1
    ]
    duplicate_directory_groups: list[dict[str, list[str]]] = []
    by_folded: dict[str, list[str]] = {}
    for path in sorted((p for p in wiki_dir.rglob("*") if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.as_posix()):
        rel = path.relative_to(wiki_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        by_folded.setdefault(_fold_taxonomy_segment(path.name), []).append(rel.as_posix())
    for folded, paths in sorted(by_folded.items()):
        if len(paths) > 1:
            duplicate_directory_groups.append({"key": folded, "paths": paths})

    root_notes = sorted(path.name for path in wiki_dir.glob("*.md") if path.is_file())
    return {
        "wiki_dir": str(wiki_dir),
        "canonical_taxonomy": canonical_taxonomy_tree(),
        "missing_canonical_dirs": missing_canonical_dirs,
        "compliant_top_level_dirs": compliant_top_level_dirs,
        "proposed_moves": proposed_moves,
        "unmapped_top_level_dirs": unmapped_top_level_dirs,
        "duplicate_destinations": duplicate_destinations,
        "duplicate_directory_groups": duplicate_directory_groups,
        "root_notes": root_notes,
        "requires_review": bool(unmapped_top_level_dirs or duplicate_destinations or root_notes),
        "dry_run_only": True,
    }


def _safe_relative_dir(value: str) -> tuple[str, ...]:
    normalized = value.replace("\\", "/").strip("/")
    if not normalized:
        raise ValidationError("Relative directory path cannot be empty")
    if _DRIVE_RE.match(value) or Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValidationError(f"Directory path must be relative: {value}")
    parts = tuple(part.strip() for part in normalized.split("/"))
    if any(not part for part in parts):
        raise ValidationError(f"Directory path has an empty segment: {value}")
    if any(part in {".", ".."} for part in parts):
        raise ValidationError(f"Directory path cannot contain '.' or '..': {value}")
    if any(part.startswith(".") for part in parts):
        raise ValidationError(f"Directory path cannot contain hidden segments: {value}")
    bad = [part for part in parts if _UNSAFE_TAXONOMY_RE.search(part)]
    if bad:
        raise ValidationError(f"Directory path has unsafe characters: {bad[0]}")
    return parts


def _join_wiki_relative_dir(wiki_dir: Path, value: str) -> Path:
    return wiki_dir.joinpath(*_safe_relative_dir(value))


def _missing_parent_dirs(wiki_dir: Path, destination: Path) -> list[str]:
    missing: list[str] = []
    parents = []
    current = destination.parent
    while current != wiki_dir and current != current.parent:
        parents.append(current)
        current = current.parent
    for parent in reversed(parents):
        if not parent.exists():
            missing.append(parent.relative_to(wiki_dir).as_posix())
    return missing


def _default_migration_receipt_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _path(f"~/.gemini/medical-notes-workbench/taxonomy-migrations/{stamp}.json")


def taxonomy_migration_plan(wiki_dir: Path) -> dict[str, Any]:
    audit = taxonomy_audit(wiki_dir)
    duplicate_destinations = {item["destination"] for item in audit["duplicate_destinations"]}
    operations: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for item in audit["proposed_moves"]:
        source_rel = item["source"]
        destination_rel = item["destination"]
        source = _join_wiki_relative_dir(wiki_dir, source_rel)
        destination = _join_wiki_relative_dir(wiki_dir, destination_rel)
        base = {
            "action": "move_dir",
            "source": source_rel,
            "destination": destination_rel,
            "source_path": str(source),
            "destination_path": str(destination),
            "reason": item.get("reason", ""),
        }
        if destination_rel in duplicate_destinations:
            blocked.append({**base, "blocked_reason": "duplicate_destination"})
        elif not source.exists():
            blocked.append({**base, "blocked_reason": "source_missing"})
        elif not source.is_dir():
            blocked.append({**base, "blocked_reason": "source_not_directory"})
        elif destination.exists():
            blocked.append({**base, "blocked_reason": "destination_exists"})
        elif source in destination.parents or source == destination:
            blocked.append({**base, "blocked_reason": "destination_inside_source"})
        else:
            operations.append({**base, "created_parent_dirs": _missing_parent_dirs(wiki_dir, destination)})

    for source_rel in audit["unmapped_top_level_dirs"]:
        blocked.append({"action": "review_dir", "source": source_rel, "blocked_reason": "unmapped_top_level_dir"})
    for filename in audit["root_notes"]:
        blocked.append({"action": "review_file", "source": filename, "blocked_reason": "root_note"})

    return {
        "schema": MIGRATION_PLAN_SCHEMA,
        "wiki_dir": str(wiki_dir),
        "generated_at": _now_iso(),
        "dry_run": True,
        "operations": operations,
        "blocked": blocked,
        "summary": {
            "operation_count": len(operations),
            "blocked_count": len(blocked),
            "requires_review": bool(blocked),
        },
        "audit": audit,
    }


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MissingPathError(f"JSON file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"JSON file must contain an object: {path}")
    return data


def _plan_wiki_dir(plan: dict[str, Any], config: MedConfig) -> Path:
    if plan.get("schema") != MIGRATION_PLAN_SCHEMA:
        raise ValidationError("Invalid taxonomy migration plan schema")
    plan_wiki = _path(str(plan.get("wiki_dir", "")))
    if plan_wiki.resolve() != config.wiki_dir.resolve():
        raise ValidationError(f"Plan wiki_dir does not match configured wiki_dir: {plan_wiki} != {config.wiki_dir}")
    return plan_wiki


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def apply_taxonomy_migration(plan_path: Path, config: MedConfig, receipt_path: Path | None = None) -> dict[str, Any]:
    plan = _load_json_file(plan_path)
    wiki_dir = _plan_wiki_dir(plan, config)
    operations = plan.get("operations", [])
    if not isinstance(operations, list):
        raise ValidationError("Migration plan operations must be a list")

    receipt = {
        "schema": MIGRATION_RECEIPT_SCHEMA,
        "plan_path": str(plan_path),
        "wiki_dir": str(wiki_dir),
        "started_at": _now_iso(),
        "completed_at": None,
        "applied_operations": [],
    }
    receipt_path = receipt_path or _default_migration_receipt_path()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(receipt_path, receipt)

    try:
        for raw_op in operations:
            if not isinstance(raw_op, dict) or raw_op.get("action") != "move_dir":
                raise ValidationError("Unsupported migration operation")
            source_rel = str(raw_op["source"])
            destination_rel = str(raw_op["destination"])
            source = _join_wiki_relative_dir(wiki_dir, source_rel)
            destination = _join_wiki_relative_dir(wiki_dir, destination_rel)
            if not source.exists():
                raise MissingPathError(f"Migration source missing: {source}")
            if not source.is_dir():
                raise ValidationError(f"Migration source is not a directory: {source}")
            if destination.exists():
                raise CollisionError(f"Migration destination already exists: {destination}")
            created_parent_dirs = _missing_parent_dirs(wiki_dir, destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            applied = {
                "action": "move_dir",
                "source": source_rel,
                "destination": destination_rel,
                "source_path": str(source),
                "destination_path": str(destination),
                "created_parent_dirs": created_parent_dirs,
                "applied_at": _now_iso(),
            }
            receipt["applied_operations"].append(applied)
            _write_json_atomic(receipt_path, receipt)
    except Exception as exc:
        receipt["failed_at"] = _now_iso()
        receipt["error"] = str(exc)
        _write_json_atomic(receipt_path, receipt)
        raise MedOpsError(f"Taxonomy migration failed. Receipt: {receipt_path}. Error: {exc}") from exc

    receipt["completed_at"] = _now_iso()
    _write_json_atomic(receipt_path, receipt)
    return {
        "applied": True,
        "receipt_path": str(receipt_path),
        "applied_count": len(receipt["applied_operations"]),
        "applied_operations": receipt["applied_operations"],
    }


def rollback_taxonomy_migration(receipt_path: Path, config: MedConfig) -> dict[str, Any]:
    receipt = _load_json_file(receipt_path)
    if receipt.get("schema") != MIGRATION_RECEIPT_SCHEMA:
        raise ValidationError("Invalid taxonomy migration receipt schema")
    wiki_dir = _path(str(receipt.get("wiki_dir", "")))
    if wiki_dir.resolve() != config.wiki_dir.resolve():
        raise ValidationError(f"Receipt wiki_dir does not match configured wiki_dir: {wiki_dir} != {config.wiki_dir}")
    operations = receipt.get("applied_operations", [])
    if not isinstance(operations, list):
        raise ValidationError("Migration receipt applied_operations must be a list")

    rolled_back: list[dict[str, Any]] = []
    for raw_op in reversed(operations):
        if not isinstance(raw_op, dict) or raw_op.get("action") != "move_dir":
            raise ValidationError("Unsupported rollback operation")
        source_rel = str(raw_op["source"])
        destination_rel = str(raw_op["destination"])
        source = _join_wiki_relative_dir(wiki_dir, source_rel)
        destination = _join_wiki_relative_dir(wiki_dir, destination_rel)
        if not destination.exists():
            raise MissingPathError(f"Rollback source missing: {destination}")
        if source.exists():
            raise CollisionError(f"Rollback destination already exists: {source}")
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))
        removed_parent_dirs: list[str] = []
        for rel_parent in reversed(raw_op.get("created_parent_dirs", [])):
            parent = _join_wiki_relative_dir(wiki_dir, str(rel_parent))
            try:
                parent.rmdir()
            except OSError:
                continue
            removed_parent_dirs.append(str(rel_parent))
        rolled_back.append(
            {
                "action": "move_dir",
                "source": destination_rel,
                "destination": source_rel,
                "rolled_back_at": _now_iso(),
                "removed_parent_dirs": removed_parent_dirs,
            }
        )

    receipt["rolled_back_at"] = _now_iso()
    receipt["rollback_operations"] = rolled_back
    _write_json_atomic(receipt_path, receipt)
    return {"rolled_back": True, "receipt_path": str(receipt_path), "rolled_back_count": len(rolled_back), "rollback_operations": rolled_back}


def resolve_collision(path: Path, mode: str, reserved: set[Path]) -> Path:
    if mode not in {"abort", "suffix"}:
        raise ValidationError(f"Invalid collision mode: {mode}")
    if mode == "abort":
        if path.exists() or path in reserved:
            raise CollisionError(f"Target note already exists: {path}")
        return path

    candidate = path
    idx = 2
    while candidate.exists() or candidate in reserved:
        candidate = path.with_name(f"{path.stem} ({idx}){path.suffix}")
        idx += 1
    return candidate


def write_new_note(path: Path, content: str, dry_run: bool = False, create_parent: bool = False) -> None:
    if dry_run:
        return
    if path.exists():
        raise CollisionError(f"Target note already exists: {path}")
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.parent.exists():
        raise MissingPathError(f"Target taxonomy directory does not exist: {path.parent}")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        if path.exists():
            raise CollisionError(f"Target note appeared during write: {path}")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MissingPathError(f"Manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid manifest JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("Manifest must be a JSON object")
    return data


def _manifest_batches(data: dict[str, Any]) -> list[dict[str, Any]]:
    if "batches" in data:
        batches = data["batches"]
        if not isinstance(batches, list):
            raise ValidationError("manifest.batches must be a list")
        return batches
    return [data]


def _validate_note_item(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        raise ValidationError("Each manifest note must be an object")
    required = ("taxonomy", "title", "content_path")
    missing = [field for field in required if not item.get(field)]
    if missing:
        raise ValidationError(f"Manifest note missing fields: {', '.join(missing)}")
    return {field: str(item[field]) for field in required}


def plan_publish_batch(
    data: dict[str, Any],
    config: MedConfig,
    collision: str,
    allow_new_taxonomy_leaf: bool = False,
) -> list[dict[str, Any]]:
    planned_batches: list[dict[str, Any]] = []
    reserved: set[Path] = set()
    for batch in _manifest_batches(data):
        if not isinstance(batch, dict):
            raise ValidationError("Each manifest batch must be an object")
        raw_file_value = batch.get("raw_file")
        notes_value = batch.get("notes")
        if not raw_file_value:
            raise ValidationError("Manifest batch missing raw_file")
        if not isinstance(notes_value, list) or not notes_value:
            raise ValidationError("Manifest batch must contain at least one note")
        raw_file = _path(str(raw_file_value))
        if not raw_file.exists():
            raise MissingPathError(f"Raw file not found: {raw_file}")
        notes: list[dict[str, Any]] = []
        for raw_item in notes_value:
            item = _validate_note_item(raw_item)
            content_path = _path(item["content_path"])
            if not content_path.exists():
                raise MissingPathError(f"Content file not found: {content_path}")
            content = content_path.read_text(encoding="utf-8")
            validate_wiki_note_contract(content, title=item["title"], raw_file=raw_file)
            target, taxonomy_resolution = resolve_target_for_note(
                config.wiki_dir,
                item["taxonomy"],
                item["title"],
                allow_new_taxonomy_leaf=allow_new_taxonomy_leaf,
            )
            target = resolve_collision(target, collision, reserved)
            reserved.add(target)
            notes.append(
                {
                    "taxonomy": taxonomy_resolution.taxonomy,
                    "taxonomy_requested": taxonomy_resolution.requested_taxonomy,
                    "taxonomy_canonicalized": list(taxonomy_resolution.canonicalized),
                    "taxonomy_new_dirs": list(taxonomy_resolution.new_dirs),
                    "title": item["title"],
                    "content_path": str(content_path),
                    "target_path": str(target),
                }
            )
        planned_batches.append({"raw_file": str(raw_file), "notes": notes})
    return planned_batches


def publish_batch(
    manifest: Path,
    config: MedConfig,
    collision: str = "abort",
    dry_run: bool = False,
    backup: bool = False,
    allow_new_taxonomy_leaf: bool = False,
) -> dict[str, Any]:
    data = _load_manifest(manifest)
    plan = plan_publish_batch(data, config, collision, allow_new_taxonomy_leaf=allow_new_taxonomy_leaf)
    created: list[str] = []
    raw_updates: list[dict[str, Any]] = []
    if dry_run:
        return {
            "dry_run": True,
            "backup": backup,
            "manifest": str(manifest),
            "allow_new_taxonomy_leaf": allow_new_taxonomy_leaf,
            "planned_batches": plan,
            "created": [],
            "raw_updates": [],
        }

    try:
        for batch in plan:
            for item in batch["notes"]:
                content = Path(item["content_path"]).read_text(encoding="utf-8")
                write_new_note(Path(item["target_path"]), content, create_parent=bool(item.get("taxonomy_new_dirs")))
                created.append(item["target_path"])
        for batch in plan:
            raw_updates.append(
                mutate_raw_frontmatter(
                    Path(batch["raw_file"]),
                    {"status": "processado", "processed_at": _now_iso()},
                    dry_run=False,
                    backup=backup,
                )
            )
    except Exception as exc:
        raise MedOpsError(
            "Batch publish failed before all raw files were marked processed. "
            f"Created notes before failure: {created}. Error: {exc}"
        ) from exc

    return {
        "dry_run": False,
        "backup": backup,
        "manifest": str(manifest),
        "allow_new_taxonomy_leaf": allow_new_taxonomy_leaf,
        "created": created,
        "raw_updates": raw_updates,
        "created_count": len(created),
        "processed_raw_count": len(raw_updates),
    }


def stage_note(
    manifest: Path,
    raw_file: Path,
    taxonomy: str,
    title: str,
    content_path: Path,
    dry_run: bool = False,
    config: MedConfig | None = None,
    allow_new_taxonomy_leaf: bool = False,
) -> dict[str, Any]:
    taxonomy_resolution = (
        resolve_taxonomy(config.wiki_dir, taxonomy, title=title, allow_new_leaf=allow_new_taxonomy_leaf)
        if config is not None
        else None
    )
    canonical_taxonomy = taxonomy_resolution.taxonomy if taxonomy_resolution else "/".join(normalize_taxonomy(taxonomy))
    _validate_taxonomy_not_title(tuple(canonical_taxonomy.split("/")), title)
    safe_title(title)
    if not raw_file.exists():
        raise MissingPathError(f"Raw file not found: {raw_file}")
    if not content_path.exists():
        raise MissingPathError(f"Content file not found: {content_path}")
    content = content_path.read_text(encoding="utf-8")
    validate_wiki_note_contract(content, title=title, raw_file=raw_file)
    if manifest.exists():
        data = _load_manifest(manifest)
    else:
        data = {"raw_file": str(raw_file), "notes": []}
    if data.get("raw_file") and str(_path(str(data["raw_file"]))) != str(raw_file):
        raise ValidationError("Manifest already belongs to a different raw_file")
    notes = data.setdefault("notes", [])
    if not isinstance(notes, list):
        raise ValidationError("manifest.notes must be a list")
    item = {"taxonomy": canonical_taxonomy, "title": title, "content_path": str(content_path)}
    if not dry_run:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        data["raw_file"] = str(raw_file)
        notes.append(item)
        atomic_write_text(manifest, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    result: dict[str, Any] = {
        "manifest": str(manifest),
        "dry_run": dry_run,
        "staged": item,
        "note_count": len(notes) + (1 if dry_run else 0),
    }
    if taxonomy_resolution is not None:
        result["taxonomy_resolution"] = taxonomy_resolution.to_json(config.wiki_dir, title=title)
    return result


def run_linker(config: MedConfig, dry_run: bool = False) -> dict[str, Any]:
    linker = config.linker_path
    if dry_run:
        return {"dry_run": True, "linker_path": str(linker), "would_run": linker.exists()}
    if not linker.exists():
        raise MissingPathError(f"Semantic linker not found: {linker}")
    env = os.environ.copy()
    env.setdefault("MED_WIKI_DIR", str(config.wiki_dir))
    env.setdefault("MED_CATALOG_PATH", str(config.catalog_path))
    command = [
        sys.executable,
        str(linker),
        "--wiki-dir",
        str(config.wiki_dir),
        "--catalog",
        str(config.catalog_path),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
    return {
        "dry_run": False,
        "linker_path": str(linker),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def validate_note_style_file(content_path: Path, title: str, raw_file: Path | None = None) -> dict[str, Any]:
    if not content_path.exists():
        raise MissingPathError(f"Content file not found: {content_path}")
    if raw_file is not None and not raw_file.exists():
        raise MissingPathError(f"Raw file not found: {raw_file}")
    raw_meta = wiki_note_style.raw_meta_from_file(raw_file) if raw_file is not None else {}
    return wiki_note_style.validate_note_style(
        content_path.read_text(encoding="utf-8"),
        title=title,
        raw_meta=raw_meta,
        path=str(content_path),
    )


def fix_note_style_file(
    content_path: Path,
    title: str,
    output_path: Path,
    raw_file: Path | None = None,
) -> dict[str, Any]:
    if not content_path.exists():
        raise MissingPathError(f"Content file not found: {content_path}")
    if raw_file is not None and not raw_file.exists():
        raise MissingPathError(f"Raw file not found: {raw_file}")
    raw_meta = wiki_note_style.raw_meta_from_file(raw_file) if raw_file is not None else {}
    fixed_content, report = wiki_note_style.fix_note_style(
        content_path.read_text(encoding="utf-8"),
        title=title,
        raw_meta=raw_meta,
        path=str(content_path),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output_path, fixed_content)
    report["output_path"] = str(output_path)
    report["wrote_output"] = True
    return report


def validate_wiki_style(wiki_dir: Path) -> dict[str, Any]:
    if not wiki_dir.exists():
        raise MissingPathError(f"Wiki dir not found: {wiki_dir}")
    if not wiki_dir.is_dir():
        raise ValidationError(f"Wiki dir is not a directory: {wiki_dir}")
    return wiki_note_style.validate_wiki_dir(wiki_dir)


def fix_wiki_style(wiki_dir: Path, apply: bool = False, backup: bool = False) -> dict[str, Any]:
    if not wiki_dir.exists():
        raise MissingPathError(f"Wiki dir not found: {wiki_dir}")
    if not wiki_dir.is_dir():
        raise ValidationError(f"Wiki dir is not a directory: {wiki_dir}")
    files = sorted(path for path in wiki_dir.rglob("*.md") if path.is_file())
    reports: list[dict[str, Any]] = []
    changed_count = 0
    written_count = 0
    backup_paths: list[str] = []
    for path in files:
        original = path.read_text(encoding="utf-8")
        title = wiki_note_style.infer_title(original, path)
        fixed, report = wiki_note_style.fix_note_style(original, title=title, path=str(path))
        changed = fixed != original
        report["changed"] = changed
        report["would_write"] = changed
        report["wrote"] = False
        report["backup"] = None
        if changed:
            changed_count += 1
        if apply and changed:
            backup_path = create_backup(path) if backup else None
            atomic_write_text(path, fixed)
            report["wrote"] = True
            report["backup"] = str(backup_path) if backup_path else None
            if backup_path:
                backup_paths.append(str(backup_path))
            written_count += 1
        reports.append(report)
    return {
        "schema": wiki_note_style.STYLE_FIX_SCHEMA,
        "wiki_dir": str(wiki_dir),
        "dry_run": not apply,
        "apply": apply,
        "backup": backup,
        "file_count": len(files),
        "changed_count": changed_count,
        "written_count": written_count,
        "error_count": sum(1 for item in reports if item["errors"]),
        "warning_count": sum(1 for item in reports if item["warnings"]),
        "backup_paths": backup_paths,
        "reports": reports,
    }


def apply_style_rewrite(
    target_path: Path,
    content_path: Path,
    *,
    dry_run: bool = False,
    backup: bool = False,
) -> dict[str, Any]:
    if not target_path.exists():
        raise MissingPathError(f"Target note not found: {target_path}")
    if not content_path.exists():
        raise MissingPathError(f"Rewritten content file not found: {content_path}")
    original = target_path.read_text(encoding="utf-8")
    rewritten = content_path.read_text(encoding="utf-8")
    title = wiki_note_style.infer_title(rewritten, target_path)
    original_title = wiki_note_style.infer_title(original, target_path)
    if original_title != target_path.stem and title != original_title:
        raise ValidationError(f"Rewritten note title changed from {original_title!r} to {title!r}")
    report = wiki_note_style.validate_note_style(rewritten, title=title, path=str(target_path))
    result: dict[str, Any] = {
        "target_path": str(target_path),
        "content_path": str(content_path),
        "title": title,
        "dry_run": dry_run,
        "backup": backup,
        "backup_path": None,
        "changed": rewritten != original,
        "written": False,
        "validation": report,
    }
    if report["errors"]:
        return result
    if not dry_run and rewritten != original:
        backup_path = create_backup(target_path) if backup else None
        atomic_write_text(target_path, rewritten)
        result["written"] = True
        result["backup_path"] = str(backup_path) if backup_path else None
    return result


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


def _json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _add_common(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument("--config", default=default, help="Optional config.toml. Reads [chat_processor].")
    parser.add_argument("--raw-dir", default=default, help="Override Chats_Raw directory.")
    parser.add_argument("--wiki-dir", default=default, help="Override Wiki_Medicina directory.")
    parser.add_argument("--linker-path", default=default, help="Override med-auto-linker script path.")
    parser.add_argument("--catalog-path", default=default, help="Override CATALOGO_WIKI.json path.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Medical Notes Workbench deterministic chat-processing operations.")
    _add_common(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    pending = sub.add_parser("list-pending", help="List raw chats with no status or status=pendente.")
    _add_common(pending, suppress_defaults=True)
    triados = sub.add_parser("list-triados", help="List raw chats with status=triado and tipo=medicina.")
    _add_common(triados, suppress_defaults=True)

    taxonomy_canonical = sub.add_parser("taxonomy-canonical", help="Print the canonical Wiki_Medicina taxonomy.")
    _add_common(taxonomy_canonical, suppress_defaults=True)

    taxonomy = sub.add_parser("taxonomy-tree", help="List existing Wiki_Medicina taxonomy folders.")
    _add_common(taxonomy, suppress_defaults=True)
    taxonomy.add_argument("--max-depth", type=int, default=0, help="Limit folder depth; 0 means all depths.")

    taxonomy_audit_parser = sub.add_parser("taxonomy-audit", help="Dry-run audit of the vault against the canonical taxonomy.")
    _add_common(taxonomy_audit_parser, suppress_defaults=True)

    taxonomy_migrate = sub.add_parser("taxonomy-migrate", help="Plan, apply, or roll back conservative taxonomy directory moves.")
    _add_common(taxonomy_migrate, suppress_defaults=True)
    migrate_mode = taxonomy_migrate.add_mutually_exclusive_group()
    migrate_mode.add_argument("--dry-run", action="store_true", help="Generate a migration plan without moving files. Default mode.")
    migrate_mode.add_argument("--apply", action="store_true", help="Apply a previously generated migration plan.")
    migrate_mode.add_argument("--rollback", action="store_true", help="Rollback a migration receipt.")
    taxonomy_migrate.add_argument("--plan", help="Plan JSON path. Required with --apply.")
    taxonomy_migrate.add_argument("--plan-output", help="Write generated dry-run plan to this path.")
    taxonomy_migrate.add_argument("--receipt", help="Receipt path for --apply output or --rollback input.")

    taxonomy_resolve = sub.add_parser("taxonomy-resolve", help="Validate and canonicalize one taxonomy against the existing wiki tree.")
    _add_common(taxonomy_resolve, suppress_defaults=True)
    taxonomy_resolve.add_argument("--taxonomy", required=True)
    taxonomy_resolve.add_argument("--title", help="Optional note title; rejects taxonomy/title duplication when provided.")
    taxonomy_resolve.add_argument(
        "--allow-new-taxonomy-leaf",
        action="store_true",
        help="Permit exactly the final taxonomy folder to be created under an existing parent.",
    )

    triage = sub.add_parser("triage", help="Mark one raw chat as triaged.")
    _add_common(triage, suppress_defaults=True)
    triage.add_argument("--raw-file", required=True)
    triage.add_argument("--tipo", default="medicina")
    triage.add_argument("--titulo", required=True)
    triage.add_argument("--fonte-id", default="")
    triage.add_argument("--dry-run", action="store_true")
    triage.add_argument("--backup", action="store_true", help="Create a .bak file before mutating raw chat frontmatter.")

    discard = sub.add_parser("discard", help="Mark one raw chat as discarded.")
    _add_common(discard, suppress_defaults=True)
    discard.add_argument("--raw-file", required=True)
    discard.add_argument("--reason", required=True)
    discard.add_argument("--dry-run", action="store_true")
    discard.add_argument("--backup", action="store_true", help="Create a .bak file before mutating raw chat frontmatter.")

    stage = sub.add_parser("stage-note", help="Append a generated note to a manifest.")
    _add_common(stage, suppress_defaults=True)
    stage.add_argument("--manifest", required=True)
    stage.add_argument("--raw-file", required=True)
    stage.add_argument("--taxonomy", required=True)
    stage.add_argument("--title", required=True)
    stage.add_argument("--content", required=True)
    stage.add_argument("--dry-run", action="store_true")
    stage.add_argument(
        "--allow-new-taxonomy-leaf",
        action="store_true",
        help="Permit exactly the final taxonomy folder to be created under an existing parent.",
    )

    publish = sub.add_parser("publish-batch", help="Publish all notes from a manifest, then mark raw files processed.")
    _add_common(publish, suppress_defaults=True)
    publish.add_argument("--manifest", required=True)
    publish.add_argument("--dry-run", action="store_true")
    publish.add_argument("--backup", action="store_true", help="Create .bak files before mutating raw chat frontmatter.")
    publish.add_argument("--collision", choices=("abort", "suffix"), default="abort")
    publish.add_argument(
        "--allow-new-taxonomy-leaf",
        action="store_true",
        help="Permit exactly the final taxonomy folder to be created under an existing parent.",
    )

    commit = sub.add_parser("commit-batch", help="Compatibility alias for publish-batch.")
    _add_common(commit, suppress_defaults=True)
    commit.add_argument("--manifest", required=True)
    commit.add_argument("--dry-run", action="store_true")
    commit.add_argument("--backup", action="store_true", help="Create .bak files before mutating raw chat frontmatter.")
    commit.add_argument("--collision", choices=("abort", "suffix"), default="abort")
    commit.add_argument(
        "--allow-new-taxonomy-leaf",
        action="store_true",
        help="Permit exactly the final taxonomy folder to be created under an existing parent.",
    )

    linker = sub.add_parser("run-linker", help="Run configured semantic linker once.")
    _add_common(linker, suppress_defaults=True)
    linker.add_argument("--dry-run", action="store_true")

    validate_note = sub.add_parser("validate-note", help="Validate one generated Wiki_Medicina note style.")
    _add_common(validate_note, suppress_defaults=True)
    validate_note.add_argument("--content", required=True, help="Generated Markdown note to validate.")
    validate_note.add_argument("--title", required=True, help="Expected note title / level-1 heading.")
    validate_note.add_argument("--raw-file", help="Optional raw chat file for exact Chat Original validation.")
    validate_note.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    fix_note = sub.add_parser("fix-note", help="Apply deterministic style fixes to one generated Wiki_Medicina note.")
    _add_common(fix_note, suppress_defaults=True)
    fix_note.add_argument("--content", required=True, help="Generated Markdown note to fix.")
    fix_note.add_argument("--title", required=True, help="Expected note title / level-1 heading.")
    fix_note.add_argument("--raw-file", help="Optional raw chat file for exact Chat Original validation.")
    fix_note.add_argument("--output", required=True, help="Write fixed Markdown to this path.")
    fix_note.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    validate_wiki = sub.add_parser("validate-wiki", help="Audit all Markdown notes under Wiki_Medicina without writing files.")
    _add_common(validate_wiki, suppress_defaults=True)
    validate_wiki.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    fix_wiki = sub.add_parser("fix-wiki", help="Apply deterministic style fixes across Wiki_Medicina.")
    _add_common(fix_wiki, suppress_defaults=True)
    fix_wiki.add_argument("--apply", action="store_true", help="Write changes in-place. Without this, only reports what would change.")
    fix_wiki.add_argument("--backup", action="store_true", help="Create .bak files before mutating notes when --apply is used.")
    fix_wiki.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    apply_rewrite = sub.add_parser("apply-style-rewrite", help="Validate and apply an LLM-rewritten Wiki_Medicina note.")
    _add_common(apply_rewrite, suppress_defaults=True)
    apply_rewrite.add_argument("--target", required=True, help="Existing Wiki_Medicina note to replace.")
    apply_rewrite.add_argument("--content", required=True, help="Temporary rewritten Markdown note.")
    apply_rewrite.add_argument("--dry-run", action="store_true", help="Validate and report without writing.")
    apply_rewrite.add_argument("--backup", action="store_true", help="Create a .bak file before replacing the target note.")
    apply_rewrite.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    validate = sub.add_parser("validate", help="Print resolved paths and existence checks.")
    _add_common(validate, suppress_defaults=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = resolve_config(args)
        if args.command == "list-pending":
            _json(list_by_status(config.raw_dir, "pending"))
        elif args.command == "list-triados":
            _json(list_by_status(config.raw_dir, "triados"))
        elif args.command == "taxonomy-canonical":
            _json(canonical_taxonomy_tree())
        elif args.command == "taxonomy-tree":
            _json(taxonomy_tree(config.wiki_dir, max_depth=args.max_depth))
        elif args.command == "taxonomy-audit":
            _json(taxonomy_audit(config.wiki_dir))
        elif args.command == "taxonomy-migrate":
            if args.rollback:
                if not args.receipt:
                    raise ValidationError("--receipt is required with --rollback")
                _json(rollback_taxonomy_migration(_path(args.receipt), config))
            elif args.apply:
                if not args.plan:
                    raise ValidationError("--plan is required with --apply")
                _json(apply_taxonomy_migration(_path(args.plan), config, receipt_path=_path(args.receipt) if args.receipt else None))
            else:
                plan = taxonomy_migration_plan(config.wiki_dir)
                if args.plan_output:
                    output = _path(args.plan_output)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    _write_json_atomic(output, plan)
                    plan["plan_path"] = str(output)
                _json(plan)
        elif args.command == "taxonomy-resolve":
            resolved = resolve_taxonomy(
                config.wiki_dir,
                args.taxonomy,
                title=args.title,
                allow_new_leaf=args.allow_new_taxonomy_leaf,
            )
            _json(resolved.to_json(config.wiki_dir, title=args.title))
        elif args.command == "triage":
            _json(
                mutate_raw_frontmatter(
                    _path(args.raw_file),
                    {
                        "tipo": args.tipo,
                        "status": "triado",
                        "data_importacao": date.today().isoformat(),
                        "fonte_id": args.fonte_id,
                        "titulo_triagem": args.titulo,
                    },
                    dry_run=args.dry_run,
                    backup=getattr(args, "backup", False),
                )
            )
        elif args.command == "discard":
            _json(
                mutate_raw_frontmatter(
                    _path(args.raw_file),
                    {"status": "descartado", "discard_reason": args.reason, "discarded_at": _now_iso()},
                    dry_run=args.dry_run,
                    backup=getattr(args, "backup", False),
                )
            )
        elif args.command == "stage-note":
            _json(
                stage_note(
                    _path(args.manifest),
                    _path(args.raw_file),
                    args.taxonomy,
                    args.title,
                    _path(args.content),
                    args.dry_run,
                    config=config,
                    allow_new_taxonomy_leaf=args.allow_new_taxonomy_leaf,
                )
            )
        elif args.command in {"publish-batch", "commit-batch"}:
            _json(
                publish_batch(
                    _path(args.manifest),
                    config,
                    collision=args.collision,
                    dry_run=args.dry_run,
                    backup=args.backup,
                    allow_new_taxonomy_leaf=args.allow_new_taxonomy_leaf,
                )
            )
        elif args.command == "run-linker":
            result = run_linker(config, dry_run=args.dry_run)
            _json(result)
            if not result.get("dry_run") and result.get("returncode", 0) != 0:
                return EXIT_LINKER
        elif args.command == "validate-note":
            report = validate_note_style_file(
                _path(args.content),
                args.title,
                raw_file=_path(args.raw_file) if args.raw_file else None,
            )
            _json(report)
            if report["errors"]:
                return EXIT_VALIDATION
        elif args.command == "fix-note":
            report = fix_note_style_file(
                _path(args.content),
                args.title,
                _path(args.output),
                raw_file=_path(args.raw_file) if args.raw_file else None,
            )
            _json(report)
            if report["errors"]:
                return EXIT_VALIDATION
        elif args.command == "validate-wiki":
            audit = validate_wiki_style(config.wiki_dir)
            _json(audit)
            if audit["error_count"]:
                return EXIT_VALIDATION
        elif args.command == "fix-wiki":
            report = fix_wiki_style(config.wiki_dir, apply=args.apply, backup=args.backup)
            _json(report)
            if report["error_count"]:
                return EXIT_VALIDATION
        elif args.command == "apply-style-rewrite":
            result = apply_style_rewrite(
                _path(args.target),
                _path(args.content),
                dry_run=args.dry_run,
                backup=args.backup,
            )
            _json(result)
            if result["validation"]["errors"]:
                return EXIT_VALIDATION
        elif args.command == "validate":
            _json(validate_config(config))
        else:  # pragma: no cover - argparse prevents this
            parser.print_help()
            return EXIT_USAGE
        return EXIT_OK
    except MedOpsError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
