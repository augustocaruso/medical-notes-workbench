"""Staging and publishing generated Wiki notes."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from wiki.artifacts import validate_artifact_batch, validate_note_artifacts
from wiki.common import CollisionError, MedOpsError, MissingPathError, ValidationError, _now_iso
from wiki.config import MedConfig, _path
from wiki.coverage import validate_raw_coverage, validate_raw_coverage_structure
from wiki.link_terms import normalize_key
from wiki.raw_chats import atomic_write_text, mutate_raw_frontmatter
from wiki.style import validate_wiki_note_contract
from wiki.taxonomy import (
    _validate_taxonomy_not_title,
    normalize_taxonomy,
    resolve_taxonomy,
    resolve_target_for_note,
    safe_title,
)
from wiki.workflow_guardrails import PUBLISH_REQUIRED_INPUTS, annotate_payload, note_target_index


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


def _paths_match(left: str, right: Path) -> bool:
    left_path = _path(left)
    try:
        return left_path.resolve() == right.resolve()
    except OSError:
        return str(left_path) == str(right)


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return str(left) == str(right)


def _note_target_key(path: Path) -> str:
    return normalize_key(path.stem)


def _wiki_note_targets(wiki_dir: Path) -> dict[str, list[Path]]:
    raw_targets = note_target_index(wiki_dir, as_relative=False)
    return {key: [path for path in values if isinstance(path, Path)] for key, values in raw_targets.items()}


def _display_path(path: Path, wiki_dir: Path) -> str:
    try:
        return path.relative_to(wiki_dir).as_posix()
    except ValueError:
        return str(path)


def _validate_normalized_target_available(
    target: Path,
    wiki_dir: Path,
    existing_targets: dict[str, list[Path]],
    reserved_targets: dict[str, Path],
) -> None:
    target_key = _note_target_key(target)
    reserved = reserved_targets.get(target_key)
    if reserved is not None and not _same_path(reserved, target):
        raise CollisionError(
            "Target note would duplicate another note in this publish batch after "
            f"Obsidian target normalization: {_display_path(target, wiki_dir)} conflicts with "
            f"{_display_path(reserved, wiki_dir)}"
        )

    conflicts = [path for path in existing_targets.get(target_key, []) if not _same_path(path, target)]
    if conflicts:
        conflict_list = ", ".join(_display_path(path, wiki_dir) for path in conflicts[:5])
        extra = "" if len(conflicts) <= 5 else f" and {len(conflicts) - 5} more"
        raise CollisionError(
            "Target note would duplicate an existing Obsidian target after accent/case "
            f"normalization: {_display_path(target, wiki_dir)} conflicts with {conflict_list}{extra}. "
            "Use the existing note or merge/rename before publishing."
        )


def _manifest_note_count(data: dict[str, Any]) -> int:
    return sum(len(batch.get("notes", [])) for batch in _manifest_batches(data) if isinstance(batch, dict))


def _batch_for_stage(data: dict[str, Any], raw_file: Path) -> dict[str, Any]:
    raw_text = str(raw_file)
    if "batches" in data:
        batches = data["batches"]
        if not isinstance(batches, list):
            raise ValidationError("manifest.batches must be a list")
        for batch in batches:
            if not isinstance(batch, dict):
                raise ValidationError("Each manifest batch must be an object")
            if batch.get("raw_file") and _paths_match(str(batch["raw_file"]), raw_file):
                notes = batch.setdefault("notes", [])
                if not isinstance(notes, list):
                    raise ValidationError("manifest batch notes must be a list")
                return batch
        new_batch: dict[str, Any] = {"raw_file": raw_text, "notes": []}
        batches.append(new_batch)
        return new_batch

    existing_raw = data.get("raw_file")
    if not existing_raw:
        data["raw_file"] = raw_text
        notes = data.setdefault("notes", [])
        if not isinstance(notes, list):
            raise ValidationError("manifest.notes must be a list")
        return data
    if _paths_match(str(existing_raw), raw_file):
        notes = data.setdefault("notes", [])
        if not isinstance(notes, list):
            raise ValidationError("manifest.notes must be a list")
        return data

    existing_notes = data.get("notes", [])
    if not isinstance(existing_notes, list):
        raise ValidationError("manifest.notes must be a list")
    existing_batch: dict[str, Any] = {"raw_file": str(existing_raw), "notes": existing_notes}
    if data.get("coverage_path"):
        existing_batch["coverage_path"] = data["coverage_path"]
    data.clear()
    data["batches"] = [
        existing_batch,
        {"raw_file": raw_text, "notes": []},
    ]
    return data["batches"][1]


def plan_publish_batch(
    data: dict[str, Any],
    config: MedConfig,
    collision: str,
    allow_new_taxonomy_leaf: bool = True,
    require_coverage: bool = True,
) -> list[dict[str, Any]]:
    planned_batches: list[dict[str, Any]] = []
    reserved: set[Path] = set()
    reserved_targets: dict[str, Path] = {}
    existing_targets = _wiki_note_targets(config.wiki_dir)
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
        coverage_path_value = batch.get("coverage_path")
        if require_coverage and not coverage_path_value:
            raise ValidationError(
                "Manifest batch missing coverage_path; create an exhaustive raw coverage inventory "
                "and stage notes with stage-note --coverage <coverage.json>"
            )
        artifact_note_inputs: list[dict[str, str]] = []
        for raw_item in notes_value:
            item = _validate_note_item(raw_item)
            content_path = _path(item["content_path"])
            if not content_path.exists():
                raise MissingPathError(f"Content file not found: {content_path}")
            content = content_path.read_text(encoding="utf-8")
            validate_wiki_note_contract(content, title=item["title"], raw_file=raw_file)
            artifact_validation = validate_note_artifacts(
                content,
                raw_file=raw_file,
                artifact_dir=config.artifact_dir,
            )
            artifact_note_inputs.append(
                {
                    "title": item["title"],
                    "content_path": str(content_path),
                    "content": content,
                }
            )
            target, taxonomy_resolution = resolve_target_for_note(
                config.wiki_dir,
                item["taxonomy"],
                item["title"],
                allow_new_taxonomy_leaf=allow_new_taxonomy_leaf,
            )
            target = resolve_collision(target, collision, reserved)
            _validate_normalized_target_available(target, config.wiki_dir, existing_targets, reserved_targets)
            reserved.add(target)
            reserved_targets[_note_target_key(target)] = target
            notes.append(
                {
                    "taxonomy": taxonomy_resolution.taxonomy,
                    "taxonomy_requested": taxonomy_resolution.requested_taxonomy,
                    "taxonomy_canonicalized": list(taxonomy_resolution.canonicalized),
                    "taxonomy_new_dirs": list(taxonomy_resolution.new_dirs),
                    "title": item["title"],
                    "content_path": str(content_path),
                    "target_path": str(target),
                    "artifact_validation": artifact_validation,
                }
            )
        planned_batch: dict[str, Any] = {
            "raw_file": str(raw_file),
            "notes": notes,
            "artifact_validation": validate_artifact_batch(
                artifact_note_inputs,
                raw_file=raw_file,
                artifact_dir=config.artifact_dir,
            ),
        }
        if coverage_path_value:
            coverage_path = _path(str(coverage_path_value))
            planned_batch["coverage_path"] = str(coverage_path)
            planned_batch["coverage"] = validate_raw_coverage(
                coverage_path,
                raw_file,
                [str(note["title"]) for note in notes],
                require_triage_note_plan=require_coverage,
            )
        planned_batches.append(planned_batch)
    return planned_batches


def publish_batch(
    manifest: Path,
    config: MedConfig,
    collision: str = "abort",
    dry_run: bool = False,
    backup: bool = False,
    allow_new_taxonomy_leaf: bool = True,
    require_coverage: bool = True,
) -> dict[str, Any]:
    data = _load_manifest(manifest)
    plan = plan_publish_batch(
        data,
        config,
        collision,
        allow_new_taxonomy_leaf=allow_new_taxonomy_leaf,
        require_coverage=require_coverage,
    )
    created: list[str] = []
    raw_updates: list[dict[str, Any]] = []
    if dry_run:
        return annotate_payload({
            "dry_run": True,
            "backup": backup,
            "manifest": str(manifest),
            "allow_new_taxonomy_leaf": allow_new_taxonomy_leaf,
            "require_coverage": require_coverage,
            "planned_batches": plan,
            "created": [],
            "raw_updates": [],
        },
            phase="publish_dry_run",
            status="preview",
            next_action="Revisar o plano e então rodar publish-batch sem --dry-run com o mesmo manifest.",
            required_inputs=PUBLISH_REQUIRED_INPUTS,
        )

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

    return annotate_payload({
        "dry_run": False,
        "backup": backup,
        "manifest": str(manifest),
        "allow_new_taxonomy_leaf": allow_new_taxonomy_leaf,
        "require_coverage": require_coverage,
        "created": created,
        "raw_updates": raw_updates,
        "created_count": len(created),
        "processed_raw_count": len(raw_updates),
    },
        phase="publish_apply",
        status="completed",
        next_action="Rodar run-linker uma única vez para atualizar links e índice após o lote.",
        required_inputs=PUBLISH_REQUIRED_INPUTS,
    )


def stage_note(
    manifest: Path,
    raw_file: Path,
    taxonomy: str,
    title: str,
    content_path: Path,
    dry_run: bool = False,
    config: MedConfig | None = None,
    allow_new_taxonomy_leaf: bool = True,
    coverage_path: Path | None = None,
) -> dict[str, Any]:
    taxonomy_resolution = (
        resolve_taxonomy(config.wiki_dir, taxonomy, title=title, allow_new_leaf=allow_new_taxonomy_leaf)
        if config is not None
        else None
    )
    canonical_taxonomy = taxonomy_resolution.taxonomy if taxonomy_resolution else "/".join(normalize_taxonomy(taxonomy))
    _validate_taxonomy_not_title(tuple(canonical_taxonomy.split("/")), title)
    filename = safe_title(title)
    if taxonomy_resolution is not None and config is not None:
        target = config.wiki_dir.joinpath(*taxonomy_resolution.parts, f"{filename}.md")
        _validate_normalized_target_available(target, config.wiki_dir, _wiki_note_targets(config.wiki_dir), {})
    if not raw_file.exists():
        raise MissingPathError(f"Raw file not found: {raw_file}")
    if not content_path.exists():
        raise MissingPathError(f"Content file not found: {content_path}")
    content = content_path.read_text(encoding="utf-8")
    validate_wiki_note_contract(content, title=title, raw_file=raw_file)
    artifact_validation = validate_note_artifacts(
        content,
        raw_file=raw_file,
        artifact_dir=config.artifact_dir if config is not None else None,
    )
    if manifest.exists():
        data = _load_manifest(manifest)
    else:
        data = {"raw_file": str(raw_file), "notes": []}
    item = {"taxonomy": canonical_taxonomy, "title": title, "content_path": str(content_path)}
    batch = _batch_for_stage(data, raw_file)
    notes = batch["notes"]
    if coverage_path is not None:
        validate_raw_coverage_structure(coverage_path, raw_file)
        existing_coverage = batch.get("coverage_path")
        if existing_coverage and not _paths_match(str(existing_coverage), coverage_path):
            raise ValidationError(
                f"Manifest batch already has a different coverage_path: {existing_coverage}"
            )
        batch["coverage_path"] = str(coverage_path)
    if not dry_run:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        notes.append(item)
        atomic_write_text(manifest, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    result: dict[str, Any] = {
        "manifest": str(manifest),
        "dry_run": dry_run,
        "staged": item,
        "artifact_validation": artifact_validation,
        "note_count": _manifest_note_count(data) + (1 if dry_run else 0),
        "batch_count": len(_manifest_batches(data)),
    }
    if coverage_path is not None:
        result["coverage_path"] = str(coverage_path)
    if taxonomy_resolution is not None:
        result["taxonomy_resolution"] = taxonomy_resolution.to_json(config.wiki_dir, title=title)
    return annotate_payload(
        result,
        phase="stage_note",
        status="preview" if dry_run else "completed",
        next_action=(
            "Adicionar as demais notas/coberturas ao manifest antes do publish-batch --dry-run."
            if not dry_run
            else "Se a nota estiver correta, repetir stage-note sem --dry-run."
        ),
        required_inputs=["raw_file", "taxonomy", "title", "content_path", "coverage_path"],
    )
