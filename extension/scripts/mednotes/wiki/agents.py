"""Safe subagent planning for Wiki workflows."""
from __future__ import annotations

import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from wiki.artifacts import discover_artifact_manifests
from wiki.common import SUBAGENT_PLAN_SCHEMA, MedOpsError, ValidationError
from wiki.config import MedConfig
from wiki.link_terms import normalize_key
from wiki.note_plan import CREATE_NOTE_ACTION, note_plan_summary, parse_triage_note_plan
from wiki.raw_chats import list_by_status, read_note_meta
from wiki.style import validate_wiki_style
from wiki.workflow_guardrails import (
    PROCESS_CHATS_REQUIRED_INPUTS,
    STYLE_REWRITE_REQUIRED_INPUTS,
    annotate_payload,
    note_target_index,
    plan_status,
)

DEFAULT_PROCESS_CHATS_MAX_CONCURRENCY = 5
DEFAULT_STYLE_REWRITE_MAX_CONCURRENCY = 3


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_text).strip("-._").lower()
    return slug or "raw"


def _chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _planned_create_targets(note_plan: dict[str, Any]) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for item in note_plan.get("items", []):
        if item.get("action") != CREATE_NOTE_ACTION:
            continue
        title = str(item.get("staged_title") or item.get("title") or "").strip()
        if not title:
            continue
        targets.append(
            {
                "id": str(item.get("id") or "").strip(),
                "title": title,
                "target_key": normalize_key(title),
            }
        )
    return targets


def _duplicate_next_action() -> str:
    return (
        "Revise o note_plan antes de arquitetura: converta duplicatas para "
        "covered_by_existing ou consolide fontes em um unico create_note."
    )


def _plan_architect_subagents(
    config: MedConfig,
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    total_available_count: int,
    concurrency: int,
    temp_root: Path,
    limit: int | None,
) -> dict[str, Any]:
    existing_targets = note_target_index(config.wiki_dir, as_relative=True)
    parsed_items: list[dict[str, Any]] = []
    blocked_items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, row in enumerate(rows, start=1):
        raw_file = str(row["path"])
        raw_key = str(Path(raw_file).expanduser())
        if raw_key in seen:
            continue
        seen.add(raw_key)
        work_id = f"architect-{index:03d}-{_slug(Path(raw_file).stem)}"
        item: dict[str, Any] = {
            "work_id": work_id,
            "agent": spec["agent"],
            "item_type": spec["item_type"],
            "raw_file": raw_file,
            "owner_key": raw_key,
            "titulo_triagem": row.get("titulo_triagem", ""),
            "fonte_id": row.get("fonte_id", ""),
        }
        try:
            raw_plan = read_note_meta(Path(raw_file)).get("note_plan", "")
            if not raw_plan:
                raise ValidationError("Raw chat missing triage note_plan; rerun triage with --note-plan")
            note_plan = parse_triage_note_plan(raw_plan, Path(raw_file))
        except ValidationError as exc:
            item["blocked_reason"] = "missing_or_invalid_note_plan"
            item["note_plan_error"] = str(exc)
            item["next_action"] = "Refaça a triagem com --note-plan exaustivo antes de planejar arquitetura."
            blocked_items.append(item)
            continue

        item["note_plan"] = note_plan
        item.update(note_plan_summary(note_plan))
        targets = _planned_create_targets(note_plan)
        duplicate_targets: list[dict[str, Any]] = []
        for target in targets:
            matches = existing_targets.get(target["target_key"], [])
            if matches:
                duplicate_targets.append(
                    {
                        **target,
                        "conflict_type": "existing_wiki_note",
                        "existing_paths": matches[:5],
                    }
                )
        parsed_items.append({"item": item, "targets": targets, "duplicate_targets": duplicate_targets})

    planned_by_key: dict[str, list[dict[str, str]]] = {}
    for parsed in parsed_items:
        item = parsed["item"]
        for target in parsed["targets"]:
            planned_by_key.setdefault(target["target_key"], []).append(
                {
                    "raw_file": str(item["raw_file"]),
                    "work_id": str(item["work_id"]),
                    "id": target["id"],
                    "title": target["title"],
                }
            )

    work_items: list[dict[str, Any]] = []
    for parsed in parsed_items:
        item = parsed["item"]
        duplicate_targets = list(parsed["duplicate_targets"])
        for target in parsed["targets"]:
            planned_matches = planned_by_key.get(target["target_key"], [])
            if len(planned_matches) > 1:
                duplicate_targets.append(
                    {
                        **target,
                        "conflict_type": "planned_in_batch",
                        "planned_matches": planned_matches,
                    }
                )
        if duplicate_targets:
            item["blocked_reason"] = "duplicate_create_note_targets"
            item["duplicate_targets"] = duplicate_targets
            item["next_action"] = _duplicate_next_action()
            blocked_items.append(item)
            continue

        try:
            artifact_manifests = discover_artifact_manifests(Path(item["raw_file"]), artifact_dir=config.artifact_dir)
        except MedOpsError as exc:
            item["blocked_reason"] = "missing_or_invalid_artifact_manifest"
            item["artifact_manifest_error"] = str(exc)
            item["next_action"] = "Corrija o manifesto HTML do Gemini ou remova a dependência antes de lançar architects."
            blocked_items.append(item)
            continue
        item["artifact_manifest_count"] = len(artifact_manifests)
        item["artifact_count"] = sum(len(manifest.artifacts) for manifest in artifact_manifests)
        if artifact_manifests:
            item["artifact_manifests"] = [manifest.to_json() for manifest in artifact_manifests]
        item["temp_dir"] = str(temp_root / item["work_id"])
        work_items.append(item)

    batches = [
        {"batch": batch_index, "max_concurrency": concurrency, "items": batch}
        for batch_index, batch in enumerate(_chunked(work_items, concurrency), start=1)
    ]
    status, next_action, human_decision_required = plan_status(
        item_count=len(work_items),
        blocked_item_count=len(blocked_items),
    )
    return annotate_payload({
        "schema": SUBAGENT_PLAN_SCHEMA,
        "phase": "architect",
        "agent": spec["agent"],
        "unit": spec["unit"],
        "max_concurrency": concurrency,
        "item_count": len(work_items),
        "total_available_count": total_available_count,
        "blocked_item_count": len(blocked_items),
        "blocked_items": blocked_items,
        "limit": limit,
        "truncated": limit is not None and len(rows) < total_available_count,
        "parallel_safe": len(work_items) > 1,
        "work_items": work_items,
        "batches": batches,
        "rules": [
            "Spawn at most one subagent per work_item.raw_file.",
            "Never spawn multiple subagents for the same raw chat or generated note.",
            "Do not split one raw chat across multiple med-knowledge-architect agents.",
            "Architect work_items must follow the triage-authored note_plan exactly.",
            "Architect planning blocks create_note targets that duplicate existing Wiki notes or another planned raw chat after accent/case normalization.",
            "Every architect result must include an exhaustive raw coverage inventory before staging.",
            "If artifact_manifests is non-empty, the staged note group for that raw chat must cover every listed HTML artifact; each note carrying one must include embed/link/provenance.",
            "Do not launch more subagents than item_count or max_concurrency.",
            "If item_count is 0 or 1, there is no useful fan-out for this phase.",
            "When limit is set, spawn only the returned work_items",
            "Rerun planning after serial consolidation before launching more.",
            "Run serial consolidation after each batch returns.",
        ],
        "serial_after": spec["serial_after"],
        "canonical_parent_commands": spec["canonical_parent_commands"],
    },
        phase="architect",
        status=status,
        blocked_reason="preconditions_failed" if blocked_items and not work_items else "",
        next_action=next_action,
        required_inputs=PROCESS_CHATS_REQUIRED_INPUTS,
        human_decision_required=human_decision_required,
    )


def plan_subagents(
    config: MedConfig,
    phase: str,
    max_concurrency: int | None = None,
    temp_root: Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    specs: dict[str, dict[str, Any]] = {
        "triage": {
            "agent": "med-chat-triager",
            "mode": "pending",
            "default_max_concurrency": DEFAULT_PROCESS_CHATS_MAX_CONCURRENCY,
            "item_type": "raw_chat",
            "unit": "one pending raw chat per subagent",
            "serial_after": [
                "parent applies med_ops.py triage or discard after each returned item",
                "parent refreshes list-triados before architect planning",
            ],
            "canonical_parent_commands": [
                'triage: uv run python "<med_ops.py>" triage --raw-file "<raw_file>" --tipo medicina --titulo "<titulo_triagem>" --fonte-id "<fonte_id>" --note-plan "<note-plan.json>"',
                'discard: uv run python "<med_ops.py>" discard --raw-file "<raw_file>" --reason "<reason>"',
            ],
        },
        "architect": {
            "agent": "med-knowledge-architect",
            "mode": "triados",
            "default_max_concurrency": DEFAULT_PROCESS_CHATS_MAX_CONCURRENCY,
            "item_type": "triaged_raw_chat",
            "unit": "one triaged raw chat per subagent; all notes split from that chat stay with the same subagent",
            "serial_after": [
                "parent validates/fixes each returned temp note",
                "parent stages notes with med_ops.py stage-note and the architect coverage inventory",
                "catalog, dry-run, guard, publish and linker stay serial",
            ],
            "canonical_parent_commands": [
                'validate-note: uv run python "<med_ops.py>" validate-note --content "<temp.md>" --title "<title>" --raw-file "<raw_file>" --json',
                'fix-note: uv run python "<med_ops.py>" fix-note --content "<temp.md>" --title "<title>" --raw-file "<raw_file>" --output "<temp.md>" --json',
                'stage-note: uv run python "<med_ops.py>" stage-note --manifest "<manifest.json>" --raw-file "<raw_file>" --coverage "<coverage.json>" --taxonomy "<taxonomy>" --title "<title>" --content "<temp.md>"',
                'publish dry-run: uv run python "<med_ops.py>" publish-batch --manifest "<manifest.json>" --dry-run',
                'publish: uv run python "<med_ops.py>" publish-batch --manifest "<manifest.json>"',
                'refresh index/linker: uv run python "<med_ops.py>" run-linker --json',
            ],
        },
        "style-rewrite": {
            "agent": "med-knowledge-architect",
            "mode": "wiki_style_rewrite",
            "default_max_concurrency": DEFAULT_STYLE_REWRITE_MAX_CONCURRENCY,
            "item_type": "wiki_note_style_rewrite",
            "unit": "one existing Wiki_Medicina note per subagent; each target path is unique",
            "serial_after": [
                "parent validates each returned temp rewrite with med_ops.py apply-style-rewrite --dry-run",
                "parent applies accepted rewrites serially with med_ops.py apply-style-rewrite",
                "parent runs validate-wiki again after rewrites",
            ],
            "canonical_parent_commands": [
                'apply rewrite dry-run: uv run python "<med_ops.py>" apply-style-rewrite --target "<note.md>" --content "<rewrite.md>" --dry-run --json',
                'apply rewrite: uv run python "<med_ops.py>" apply-style-rewrite --target "<note.md>" --content "<rewrite.md>" --backup --json',
            ],
        },
    }
    if phase not in specs:
        raise ValidationError(f"Unknown subagent planning phase: {phase}")
    spec = specs[phase]
    concurrency = max_concurrency or int(spec["default_max_concurrency"])
    if concurrency < 1:
        raise ValidationError("--max-concurrency must be at least 1")
    if limit is not None and limit < 1:
        raise ValidationError("--limit must be at least 1")
    if phase == "architect" and temp_root is None:
        temp_root = Path(tempfile.gettempdir()) / "medical-notes-workbench" / "process-chats"
    elif phase == "style-rewrite" and temp_root is None:
        temp_root = Path(tempfile.gettempdir()) / "medical-notes-workbench" / "fix-wiki"

    if phase == "style-rewrite":
        audit = validate_wiki_style(config.wiki_dir)
        work_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        rewrite_reports = [
            report
            for report in audit["reports"]
            if report.get("requires_llm_rewrite") and report.get("path")
        ]
        total_available_count = len(rewrite_reports)
        if limit is not None:
            rewrite_reports = rewrite_reports[:limit]
        for index, report in enumerate(rewrite_reports, start=1):
            target_path = Path(str(report["path"]))
            owner_key = str(target_path.expanduser())
            if owner_key in seen:
                continue
            seen.add(owner_key)
            work_id = f"{phase}-{index:03d}-{_slug(target_path.stem)}"
            item = {
                "work_id": work_id,
                "agent": spec["agent"],
                "item_type": spec["item_type"],
                "target_path": str(target_path),
                "owner_key": owner_key,
                "title": str(report.get("title") or target_path.stem),
                "rewrite_prompt": report.get("rewrite_prompt"),
                "errors": report.get("errors", []),
                "warnings": report.get("warnings", []),
                "temp_dir": str(temp_root / work_id),
                "temp_output": str(temp_root / work_id / f"{target_path.stem}.rewrite.md"),
            }
            work_items.append(item)
        batches = [
            {"batch": batch_index, "max_concurrency": concurrency, "items": batch}
            for batch_index, batch in enumerate(_chunked(work_items, concurrency), start=1)
        ]
        return {
            "schema": SUBAGENT_PLAN_SCHEMA,
            "phase": phase,
            "agent": spec["agent"],
            "unit": spec["unit"],
            "max_concurrency": concurrency,
            "item_count": len(work_items),
            "total_available_count": total_available_count,
            "limit": limit,
            "truncated": len(work_items) < total_available_count,
            "parallel_safe": len(work_items) > 1,
            "work_items": work_items,
            "batches": batches,
            "rules": [
                "Spawn at most one subagent per work_item.target_path.",
                "Never spawn multiple subagents for the same Wiki note.",
                "Do not split one note rewrite across multiple med-knowledge-architect agents.",
                "Do not launch more subagents than item_count or max_concurrency.",
                "If item_count is 0 or 1, there is no useful fan-out for this phase.",
                "When limit is set, spawn only the returned work_items",
                "Rerun planning after serial consolidation before launching more.",
                "Run serial apply-style-rewrite validation and application after each batch returns.",
            ],
            "serial_after": spec["serial_after"],
            "canonical_parent_commands": spec["canonical_parent_commands"],
            "source_audit": {
                "schema": audit["schema"],
                "wiki_dir": audit["wiki_dir"],
                "file_count": audit["file_count"],
                "error_count": audit["error_count"],
                "warning_count": audit["warning_count"],
            },
        }

    rows = list_by_status(config.raw_dir, str(spec["mode"]))
    total_available_count = len(rows)
    if limit is not None:
        rows = rows[:limit]
    if phase == "architect":
        if temp_root is None:
            raise ValidationError("Internal error: architect temp_root was not resolved")
        return _plan_architect_subagents(
            config,
            spec,
            rows,
            total_available_count=total_available_count,
            concurrency=concurrency,
            temp_root=temp_root,
            limit=limit,
        )
    work_items: list[dict[str, Any]] = []
    blocked_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        raw_file = str(row["path"])
        raw_key = str(Path(raw_file).expanduser())
        if raw_key in seen:
            continue
        seen.add(raw_key)
        work_id = f"{phase}-{index:03d}-{_slug(Path(raw_file).stem)}"
        item: dict[str, Any] = {
            "work_id": work_id,
            "agent": spec["agent"],
            "item_type": spec["item_type"],
            "raw_file": raw_file,
            "owner_key": raw_key,
            "titulo_triagem": row.get("titulo_triagem", ""),
            "fonte_id": row.get("fonte_id", ""),
        }
        if phase == "architect":
            try:
                raw_plan = read_note_meta(Path(raw_file)).get("note_plan", "")
                if not raw_plan:
                    raise ValidationError("Raw chat missing triage note_plan; rerun triage with --note-plan")
                note_plan = parse_triage_note_plan(raw_plan, Path(raw_file))
            except ValidationError as exc:
                item["blocked_reason"] = "missing_or_invalid_note_plan"
                item["note_plan_error"] = str(exc)
                blocked_items.append(item)
                continue
            item["note_plan"] = note_plan
            item.update(note_plan_summary(note_plan))
            try:
                artifact_manifests = discover_artifact_manifests(Path(raw_file), artifact_dir=config.artifact_dir)
            except MedOpsError as exc:
                item["blocked_reason"] = "missing_or_invalid_artifact_manifest"
                item["artifact_manifest_error"] = str(exc)
                blocked_items.append(item)
                continue
            item["artifact_manifest_count"] = len(artifact_manifests)
            item["artifact_count"] = sum(len(manifest.artifacts) for manifest in artifact_manifests)
            if artifact_manifests:
                item["artifact_manifests"] = [manifest.to_json() for manifest in artifact_manifests]
        if temp_root is not None:
            item["temp_dir"] = str(temp_root / work_id)
        work_items.append(item)

    batches = [
        {"batch": batch_index, "max_concurrency": concurrency, "items": batch}
        for batch_index, batch in enumerate(_chunked(work_items, concurrency), start=1)
    ]
    status, next_action, human_decision_required = plan_status(
        item_count=len(work_items),
        blocked_item_count=len(blocked_items),
    )
    return annotate_payload({
        "schema": SUBAGENT_PLAN_SCHEMA,
        "phase": phase,
        "agent": spec["agent"],
        "unit": spec["unit"],
        "max_concurrency": concurrency,
        "item_count": len(work_items),
        "total_available_count": total_available_count,
        "blocked_item_count": len(blocked_items),
        "blocked_items": blocked_items,
        "limit": limit,
        "truncated": limit is not None and len(rows) < total_available_count,
        "parallel_safe": len(work_items) > 1,
        "work_items": work_items,
        "batches": batches,
        "rules": [
            "Spawn at most one subagent per work_item.raw_file.",
            "Never spawn multiple subagents for the same raw chat or generated note.",
            "Do not split one raw chat across multiple med-knowledge-architect agents.",
            "Architect work_items must follow the triage-authored note_plan exactly.",
            "Every architect result must include an exhaustive raw coverage inventory before staging.",
            "If artifact_manifests is non-empty, the staged note group for that raw chat must cover every listed HTML artifact; each note carrying one must include embed/link/provenance.",
            "Do not launch more subagents than item_count or max_concurrency.",
            "If item_count is 0 or 1, there is no useful fan-out for this phase.",
            "When limit is set, spawn only the returned work_items",
            "Rerun planning after serial consolidation before launching more.",
            "Run serial consolidation after each batch returns.",
        ],
        "serial_after": spec["serial_after"],
        "canonical_parent_commands": spec["canonical_parent_commands"],
    },
        phase=phase,
        status=status,
        blocked_reason="preconditions_failed" if blocked_items and not work_items else "",
        next_action=next_action,
        required_inputs=STYLE_REWRITE_REQUIRED_INPUTS if phase == "style-rewrite" else PROCESS_CHATS_REQUIRED_INPUTS,
        human_decision_required=human_decision_required,
    )
