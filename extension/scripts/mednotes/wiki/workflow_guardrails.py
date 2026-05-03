"""Shared operational guardrails for deterministic Wiki workflows."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from wiki.link_terms import normalize_key

PROCESS_CHATS_REQUIRED_INPUTS = ["raw_file", "note_plan", "coverage_path"]
PUBLISH_REQUIRED_INPUTS = ["manifest", "coverage_path", "dry_run_receipt"]
LINK_REQUIRED_INPUTS = ["wiki_dir", "catalog_path", "linker_path"]
FIX_WIKI_REQUIRED_INPUTS = ["wiki_dir", "catalog_path", "linker_path"]
STYLE_REWRITE_REQUIRED_INPUTS = ["target", "content"]


def annotate_payload(
    payload: dict[str, Any],
    *,
    phase: str,
    status: str,
    blocked_reason: str | None = None,
    next_action: str | None = None,
    required_inputs: list[str] | None = None,
    human_decision_required: bool = False,
) -> dict[str, Any]:
    """Attach stable operational fields expected by workflows/tests/agents."""
    payload["phase"] = phase
    payload["status"] = status
    payload["blocked_reason"] = blocked_reason or ""
    payload["next_action"] = next_action or ""
    payload["required_inputs"] = list(required_inputs or [])
    payload["human_decision_required"] = bool(human_decision_required)
    return payload


def note_target_index(wiki_dir: Path, *, as_relative: bool = False) -> dict[str, list[Path | str]]:
    """Index existing note stems by Obsidian-style normalized target key."""
    targets: dict[str, list[Path | str]] = {}
    if not wiki_dir.exists():
        return targets
    for path in sorted(wiki_dir.rglob("*.md"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.name.startswith("."):
            continue
        display: Path | str
        if as_relative:
            try:
                display = path.relative_to(wiki_dir).as_posix()
            except ValueError:
                display = str(path)
        else:
            display = path
        targets.setdefault(normalize_key(path.stem), []).append(display)
    return targets


def plan_status(*, item_count: int, blocked_item_count: int) -> tuple[str, str, bool]:
    """Return status, next action and whether a human decision is needed."""
    if item_count == 0 and blocked_item_count:
        return (
            "blocked",
            "Revisar os blocked_items, corrigir as precondições e planejar novamente.",
            True,
        )
    if item_count and blocked_item_count:
        return (
            "ready_with_blockers",
            "Executar apenas os work_items liberados e tratar os blocked_items antes do próximo lote.",
            True,
        )
    if item_count:
        return ("ready", "Executar somente os work_items deste plano e consolidar serialmente depois.", False)
    return ("completed", "Nenhum item pendente para esta fase.", False)
