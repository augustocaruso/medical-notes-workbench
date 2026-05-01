"""High-level Wiki health workflow (`fix-wiki`)."""
from __future__ import annotations

from typing import Any

from wiki.agents import plan_subagents
from wiki.common import WIKI_HEALTH_FIX_SCHEMA
from wiki.config import MedConfig
from wiki.linking import graph_audit, run_linker
from wiki.style import _requires_style_rewrite, fix_wiki_style, validate_wiki_style
from wiki.taxonomy import taxonomy_audit


def _style_rewrite_plan_if_needed(config: MedConfig, audit: dict[str, Any]) -> dict[str, Any] | None:
    if not _requires_style_rewrite(audit):
        return None
    return plan_subagents(config, "style-rewrite", max_concurrency=3)


def _taxonomy_action_issue_count(audit: dict[str, Any]) -> int:
    action_keys = (
        "proposed_moves",
        "unmapped_top_level_dirs",
        "duplicate_destinations",
        "duplicate_directory_groups",
        "root_notes",
    )
    return sum(len(audit.get(key, [])) for key in action_keys)


def fix_wiki_health(config: MedConfig, apply: bool = False, backup: bool = False) -> dict[str, Any]:
    taxonomy_report = taxonomy_audit(config.wiki_dir)
    taxonomy_issue_count = _taxonomy_action_issue_count(taxonomy_report)
    style_fix = fix_wiki_style(config.wiki_dir, apply=apply, backup=backup)
    style_audit = validate_wiki_style(config.wiki_dir)
    rewrite_plan = _style_rewrite_plan_if_needed(config, style_audit)
    graph_before = graph_audit(config)
    linker_dry_run = run_linker(config, dry_run=True)
    linker_apply: dict[str, Any] | None = None
    linker_skipped_reason = ""

    if apply:
        if rewrite_plan and rewrite_plan.get("item_count", 0):
            linker_skipped_reason = "requires_llm_rewrite"
        elif linker_dry_run.get("blocker_count", 0):
            linker_skipped_reason = "graph_blockers"
        else:
            linker_apply = run_linker(config, dry_run=False)

    graph_after = graph_audit(config)
    return {
        **style_fix,
        "schema": WIKI_HEALTH_FIX_SCHEMA,
        "style_fix": style_fix,
        "style_audit": style_audit,
        "taxonomy_audit": taxonomy_report,
        "taxonomy_action_required": bool(taxonomy_issue_count),
        "taxonomy_issue_count": taxonomy_issue_count,
        "taxonomy_missing_canonical_dir_count": len(taxonomy_report.get("missing_canonical_dirs", [])),
        "taxonomy_proposed_move_count": len(taxonomy_report.get("proposed_moves", [])),
        "taxonomy_unmapped_top_level_dir_count": len(taxonomy_report.get("unmapped_top_level_dirs", [])),
        "taxonomy_duplicate_destination_count": len(taxonomy_report.get("duplicate_destinations", [])),
        "taxonomy_duplicate_directory_group_count": len(taxonomy_report.get("duplicate_directory_groups", [])),
        "taxonomy_root_note_count": len(taxonomy_report.get("root_notes", [])),
        "requires_llm_rewrite_count": sum(1 for item in style_audit.get("reports", []) if item.get("requires_llm_rewrite")),
        "style_rewrite_plan": rewrite_plan,
        "graph_audit": graph_before,
        "graph_error_count": graph_before.get("error_count", 0),
        "graph_warning_count": graph_before.get("warning_count", 0),
        "linker_dry_run": linker_dry_run,
        "linker_apply": linker_apply,
        "linker_applied": bool(linker_apply and linker_apply.get("returncode") == 0),
        "linker_skipped_reason": linker_skipped_reason,
        "graph_audit_final": graph_after,
    }
