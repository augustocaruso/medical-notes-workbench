"""Triage-authored note plan validation for raw chat processing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wiki.common import MissingPathError, ValidationError
from wiki.config import _path

TRIAGE_NOTE_PLAN_SCHEMA = "medical-notes-workbench.triage-note-plan.v1"
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


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MissingPathError(f"Triage note plan not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid triage note plan JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("Triage note plan must be a JSON object")
    return data


def _normalized_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ValidationError("Triage note plan must contain a non-empty items list")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_create_titles: set[str] = set()
    for index, raw_item in enumerate(items, start=1):
        if not isinstance(raw_item, dict):
            raise ValidationError(f"Triage note plan item #{index} must be an object")
        item_id = str(raw_item.get("id") or f"T{index:03d}").strip()
        title = str(raw_item.get("title") or "").strip()
        action = str(raw_item.get("action") or "").strip()
        if not item_id:
            raise ValidationError(f"Triage note plan item #{index} missing id")
        if item_id in seen_ids:
            raise ValidationError(f"Triage note plan item id duplicated: {item_id}")
        if not title:
            raise ValidationError(f"Triage note plan item {item_id} missing title")
        if action not in ALLOWED_ACTIONS:
            raise ValidationError(
                f"Triage note plan item {item_id} has invalid action {action!r}; "
                f"expected one of {', '.join(sorted(ALLOWED_ACTIONS))}"
            )

        item: dict[str, Any] = {"id": item_id, "title": title, "action": action}
        staged_title = str(raw_item.get("staged_title") or title).strip()
        if action == CREATE_NOTE_ACTION:
            if not staged_title:
                raise ValidationError(f"Triage note plan item {item_id} missing staged_title")
            if staged_title in seen_create_titles:
                raise ValidationError(f"Triage note plan create_note title duplicated: {staged_title}")
            item["staged_title"] = staged_title
            seen_create_titles.add(staged_title)
        else:
            reason = str(raw_item.get("reason") or "").strip()
            if not reason:
                raise ValidationError(f"Triage note plan item {item_id} with action {action} must include reason")
            item["reason"] = reason
            if action == COVERED_BY_EXISTING_ACTION:
                existing_title = str(raw_item.get("existing_title") or "").strip()
                if not existing_title:
                    raise ValidationError(
                        f"Triage note plan item {item_id} with action {action} must include existing_title"
                    )
                item["existing_title"] = existing_title

        taxonomy_hint = str(raw_item.get("taxonomy_hint") or "").strip()
        if taxonomy_hint:
            item["taxonomy_hint"] = taxonomy_hint
        aliases = raw_item.get("aliases")
        if isinstance(aliases, list):
            clean_aliases = [str(alias).strip() for alias in aliases if str(alias).strip()]
            if clean_aliases:
                item["aliases"] = clean_aliases

        normalized.append(item)
        seen_ids.add(item_id)

    if not any(item["action"] == CREATE_NOTE_ACTION for item in normalized):
        raise ValidationError("Triage note plan must include at least one create_note item")
    return normalized


def normalize_triage_note_plan(data: dict[str, Any], raw_file: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("Triage note plan must be a JSON object")
    if data.get("schema") != TRIAGE_NOTE_PLAN_SCHEMA:
        raise ValidationError(f"Triage note plan schema must be {TRIAGE_NOTE_PLAN_SCHEMA}")
    raw_value = str(data.get("raw_file") or "")
    if not raw_value:
        raise ValidationError("Triage note plan missing raw_file")
    if not _paths_match(raw_value, raw_file):
        raise ValidationError(f"Triage note plan raw_file does not match: {raw_value}")
    if data.get("exhaustive") is not True:
        raise ValidationError("Triage note plan must set exhaustive: true")
    return {
        "schema": TRIAGE_NOTE_PLAN_SCHEMA,
        "raw_file": str(raw_file),
        "exhaustive": True,
        "items": _normalized_items(data.get("items")),
    }


def load_triage_note_plan(path: Path, raw_file: Path) -> dict[str, Any]:
    return normalize_triage_note_plan(_load_json_file(path), raw_file)


def parse_triage_note_plan(value: str, raw_file: Path) -> dict[str, Any]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid triage note plan in raw frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("Triage note plan in raw frontmatter must be a JSON object")
    return normalize_triage_note_plan(data, raw_file)


def serialize_triage_note_plan(data: dict[str, Any], raw_file: Path) -> str:
    normalized = normalize_triage_note_plan(data, raw_file)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def create_note_titles(plan: dict[str, Any]) -> set[str]:
    return {
        str(item.get("staged_title") or item.get("title") or "").strip()
        for item in plan.get("items", [])
        if item.get("action") == CREATE_NOTE_ACTION and str(item.get("staged_title") or item.get("title") or "").strip()
    }


def note_plan_summary(plan: dict[str, Any]) -> dict[str, int]:
    counts = {action: 0 for action in sorted(ALLOWED_ACTIONS)}
    for item in plan.get("items", []):
        action = str(item.get("action") or "")
        if action in counts:
            counts[action] += 1
    return {
        "note_plan_item_count": sum(counts.values()),
        "note_plan_create_count": counts[CREATE_NOTE_ACTION],
        "note_plan_covered_existing_count": counts[COVERED_BY_EXISTING_ACTION],
        "note_plan_not_a_note_count": counts[NOT_A_NOTE_ACTION],
    }
