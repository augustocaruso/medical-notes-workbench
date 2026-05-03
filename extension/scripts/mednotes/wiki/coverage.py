"""Coverage inventory validation for raw chat publishing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wiki.common import MissingPathError, ValidationError
from wiki.config import _path
from wiki.note_plan import create_note_titles, note_plan_summary, parse_triage_note_plan
from wiki.raw_chats import read_note_meta

RAW_COVERAGE_SCHEMA = "medical-notes-workbench.raw-coverage.v1"
CREATE_NOTE_ACTION = "create_note"
COVERED_BY_EXISTING_ACTION = "covered_by_existing"
NOT_A_NOTE_ACTION = "not_a_note"
ALLOWED_ACTIONS = {CREATE_NOTE_ACTION, COVERED_BY_EXISTING_ACTION, NOT_A_NOTE_ACTION}


def _paths_match(left: str, right: Path) -> bool:
    left_path = _path(left)
    try:
        return left_path.resolve() == right.resolve()
    except OSError:
        return str(left_path) == str(right)


def _load_coverage(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MissingPathError(f"Coverage inventory not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid coverage inventory JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("Coverage inventory must be a JSON object")
    return data


def _triage_note_plan(raw_file: Path, *, required: bool) -> dict[str, Any] | None:
    raw_plan = read_note_meta(raw_file).get("note_plan", "")
    if not raw_plan:
        if required:
            raise ValidationError("Raw chat missing triage note_plan; rerun triage with --note-plan")
        return None
    return parse_triage_note_plan(raw_plan, raw_file)


def _coverage_create_titles(items: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("staged_title") or item.get("title") or "").strip()
        for item in items
        if item.get("action") == CREATE_NOTE_ACTION and str(item.get("staged_title") or item.get("title") or "").strip()
    }


def _item_signature(item: dict[str, Any]) -> tuple[str, str, str, str]:
    action = str(item.get("action") or "").strip()
    title = str(item.get("staged_title") or item.get("title") or "").strip()
    existing = str(item.get("existing_title") or "").strip()
    return (str(item.get("id") or "").strip(), action, title, existing)


def validate_raw_coverage_structure(path: Path, raw_file: Path, *, require_triage_note_plan: bool = True) -> dict[str, Any]:
    """Validate structure and raw-file binding without checking staged notes."""

    data = _load_coverage(path)
    if data.get("schema") != RAW_COVERAGE_SCHEMA:
        raise ValidationError(f"Coverage inventory schema must be {RAW_COVERAGE_SCHEMA}")
    raw_value = str(data.get("raw_file") or "")
    if not raw_value:
        raise ValidationError("Coverage inventory missing raw_file")
    if not _paths_match(raw_value, raw_file):
        raise ValidationError(f"Coverage inventory raw_file does not match manifest batch: {raw_value}")
    if data.get("exhaustive") is not True:
        raise ValidationError("Coverage inventory must set exhaustive: true")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError("Coverage inventory must contain a non-empty items list")

    action_counts = {action: 0 for action in sorted(ALLOWED_ACTIONS)}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Coverage item #{index} must be an object")
        item_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        action = str(item.get("action") or "").strip()
        if not item_id:
            raise ValidationError(f"Coverage item #{index} missing id")
        if not title:
            raise ValidationError(f"Coverage item {item_id} missing title")
        if action not in ALLOWED_ACTIONS:
            raise ValidationError(
                f"Coverage item {item_id} has invalid action {action!r}; "
                f"expected one of {', '.join(sorted(ALLOWED_ACTIONS))}"
            )
        if action != CREATE_NOTE_ACTION and not str(item.get("reason") or "").strip():
            raise ValidationError(f"Coverage item {item_id} with action {action} must include reason")
        if action == COVERED_BY_EXISTING_ACTION and not str(item.get("existing_title") or "").strip():
            raise ValidationError(f"Coverage item {item_id} with action {action} must include existing_title")
        action_counts[action] += 1

    result = {
        "schema": RAW_COVERAGE_SCHEMA,
        "coverage_path": str(path),
        "raw_file": str(raw_file),
        "exhaustive": True,
        "item_count": len(items),
        "create_note_count": action_counts[CREATE_NOTE_ACTION],
        "covered_by_existing_count": action_counts[COVERED_BY_EXISTING_ACTION],
        "not_a_note_count": action_counts[NOT_A_NOTE_ACTION],
    }
    note_plan = _triage_note_plan(raw_file, required=require_triage_note_plan)
    if note_plan:
        plan_titles = create_note_titles(note_plan)
        coverage_titles = _coverage_create_titles(items)
        missing = sorted(plan_titles - coverage_titles)
        extra = sorted(coverage_titles - plan_titles)
        if missing:
            raise ValidationError(
                "Coverage inventory is missing triage-planned notes: " + ", ".join(missing)
            )
        if extra:
            raise ValidationError(
                "Coverage inventory has create_note items absent from triage note_plan: " + ", ".join(extra)
            )
        plan_signatures = {_item_signature(item) for item in note_plan.get("items", [])}
        coverage_signatures = {_item_signature(item) for item in items}
        if plan_signatures != coverage_signatures:
            raise ValidationError("Coverage inventory does not match triage note_plan items")
        result.update(note_plan_summary(note_plan))
    return result


def validate_raw_coverage(
    path: Path,
    raw_file: Path,
    staged_titles: list[str],
    *,
    require_triage_note_plan: bool = True,
) -> dict[str, Any]:
    """Validate that the exhaustive inventory and staged manifest agree."""

    summary = validate_raw_coverage_structure(
        path,
        raw_file,
        require_triage_note_plan=require_triage_note_plan,
    )
    data = _load_coverage(path)
    items = data["items"]
    staged = {title.strip() for title in staged_titles if title.strip()}
    create_titles: set[str] = set()
    for item in items:
        if item["action"] != CREATE_NOTE_ACTION:
            continue
        staged_title = str(item.get("staged_title") or item.get("title") or "").strip()
        create_titles.add(staged_title)

    missing = sorted(create_titles - staged)
    unexpected = sorted(staged - create_titles)
    if missing:
        raise ValidationError(
            "Coverage inventory has create_note items not staged in manifest: " + ", ".join(missing)
        )
    if unexpected:
        raise ValidationError(
            "Manifest has staged notes absent from coverage inventory: " + ", ".join(unexpected)
        )

    summary["staged_note_count"] = len(staged)
    return summary
