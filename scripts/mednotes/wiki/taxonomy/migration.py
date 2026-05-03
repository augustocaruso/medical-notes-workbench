"""Conservative taxonomy migration planning, apply and rollback."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
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
from wiki.taxonomy.audit import taxonomy_audit
from wiki.taxonomy.normalize import _DRIVE_RE, _safe_relative_dir

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
