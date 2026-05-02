"""Safe subagent planning for Wiki workflows."""
from __future__ import annotations

import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from wiki.common import SUBAGENT_PLAN_SCHEMA, ValidationError
from wiki.config import MedConfig
from wiki.raw_chats import list_by_status
from wiki.style import validate_wiki_style

DEFAULT_PROCESS_CHATS_MAX_CONCURRENCY = 5
DEFAULT_STYLE_REWRITE_MAX_CONCURRENCY = 3


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_text).strip("-._").lower()
    return slug or "raw"


def _chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


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
                'triage: uv run python "<med_ops.py>" triage --raw-file "<raw_file>" --tipo medicina --titulo "<titulo_triagem>" --fonte-id "<fonte_id>"',
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
    work_items: list[dict[str, Any]] = []
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
        if temp_root is not None:
            item["temp_dir"] = str(temp_root / work_id)
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
            "Spawn at most one subagent per work_item.raw_file.",
            "Never spawn multiple subagents for the same raw chat or generated note.",
            "Do not split one raw chat across multiple med-knowledge-architect agents.",
            "Every architect result must include an exhaustive raw coverage inventory before staging.",
            "Do not launch more subagents than item_count or max_concurrency.",
            "If item_count is 0 or 1, there is no useful fan-out for this phase.",
            "When limit is set, spawn only the returned work_items",
            "Rerun planning after serial consolidation before launching more.",
            "Run serial consolidation after each batch returns.",
        ],
        "serial_after": spec["serial_after"],
        "canonical_parent_commands": spec["canonical_parent_commands"],
    }
