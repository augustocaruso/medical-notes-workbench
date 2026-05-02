"""High-level Wiki health workflow (`fix-wiki`)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from wiki.agents import plan_subagents
from wiki.common import WIKI_HEALTH_FIX_SCHEMA
from wiki.config import MedConfig
from wiki.graph_fixes import fix_wiki_graph
from wiki.linking import graph_audit, run_linker
from wiki.raw_chats import create_backup, prune_backup_files
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


def _backup_linker_planned_changes(config: MedConfig, linker_dry_run: dict[str, Any], backup: bool) -> list[str]:
    if not backup:
        return []
    backup_paths: list[str] = []
    for plan in linker_dry_run.get("plans", []):
        if not isinstance(plan, dict) or not plan.get("changed"):
            continue
        file_value = plan.get("file")
        if not isinstance(file_value, str):
            continue
        path = Path(file_value)
        if not path.exists() or not path.is_file():
            continue
        backup_paths.append(str(create_backup(path)))
    return backup_paths


def fix_wiki_health(
    config: MedConfig,
    apply: bool = False,
    backup: bool = False,
    backup_retention_days: int = 14,
    backup_max_per_file: int = 3,
) -> dict[str, Any]:
    taxonomy_report = taxonomy_audit(config.wiki_dir)
    taxonomy_issue_count = _taxonomy_action_issue_count(taxonomy_report)
    style_fix = fix_wiki_style(config.wiki_dir, apply=apply, backup=backup)
    graph_fix = fix_wiki_graph(config.wiki_dir, catalog_path=config.catalog_path, apply=apply, backup=backup)
    style_audit = validate_wiki_style(config.wiki_dir)
    rewrite_plan = _style_rewrite_plan_if_needed(config, style_audit)
    graph_before = graph_audit(config)
    linker_dry_run = run_linker(config, dry_run=True)
    linker_apply: dict[str, Any] | None = None
    linker_skipped_reason = ""
    linker_backup_paths: list[str] = []

    if apply:
        if rewrite_plan and rewrite_plan.get("item_count", 0):
            linker_skipped_reason = "requires_llm_rewrite"
        elif linker_dry_run.get("blocker_count", 0):
            linker_skipped_reason = "graph_blockers"
        else:
            linker_backup_paths = _backup_linker_planned_changes(config, linker_dry_run, backup)
            linker_apply = run_linker(config, dry_run=False)

    graph_after = graph_audit(config)
    backup_cleanup = (
        prune_backup_files(config.wiki_dir, max_per_file=backup_max_per_file, retention_days=backup_retention_days)
        if apply and backup
        else None
    )
    return {
        **style_fix,
        "schema": WIKI_HEALTH_FIX_SCHEMA,
        "style_fix": style_fix,
        "graph_fix": graph_fix,
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
        "linker_backup_paths": linker_backup_paths,
        "linker_skipped_reason": linker_skipped_reason,
        "graph_audit_final": graph_after,
        "backup_policy": {
            "enabled": bool(apply and backup),
            "retention_days": backup_retention_days,
            "max_per_file": backup_max_per_file,
        },
        "backup_cleanup": backup_cleanup,
    }
