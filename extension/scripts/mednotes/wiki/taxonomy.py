"""Wiki_Medicina taxonomy normalization, audit and migration."""
from __future__ import annotations

import difflib
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from wiki.common import (
    MIGRATION_PLAN_SCHEMA,
    MIGRATION_RECEIPT_SCHEMA,
    CollisionError,
    MedOpsError,
    MissingPathError,
    ValidationError,
    _now_iso,
)
from wiki.config import MedConfig, _path
from wiki.raw_chats import atomic_write_text

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
    allow_new_leaf: bool = True,
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
            if idx < 2:
                canonical_parts.append(requested)
                new_dirs.append("/".join(canonical_parts))
                parent = parent / requested
                continue
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
    allow_new_taxonomy_leaf: bool = True,
) -> tuple[Path, TaxonomyResolution]:
    resolution = resolve_taxonomy(wiki_dir, taxonomy, title=title, allow_new_leaf=allow_new_taxonomy_leaf)
    return wiki_dir.joinpath(*resolution.parts, f"{safe_title(title)}.md"), resolution


def target_for_note(
    wiki_dir: Path,
    taxonomy: str,
    title: str,
    *,
    allow_new_taxonomy_leaf: bool = True,
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
