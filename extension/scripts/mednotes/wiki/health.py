"""High-level Wiki health workflow (`fix-wiki`)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from wiki.agents import plan_subagents
from wiki.common import BLOCKER_RESOLUTION_SCHEMA, WIKI_HEALTH_FIX_SCHEMA
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


def _issue_sample(issues: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    for issue in issues[:limit]:
        sample.append(
            {
                key: issue.get(key)
                for key in ("code", "file", "line", "target", "raw", "message", "files")
                if issue.get(key) is not None
            }
        )
    return sample


def _issues_by_code(issues: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        code = str(issue.get("code", "unknown"))
        grouped.setdefault(code, []).append(issue)
    return grouped


def _blocker_resolution_plan(
    *,
    apply: bool,
    graph_audit_report: dict[str, Any],
    write_errors: list[dict[str, Any]],
    rewrite_plan: dict[str, Any] | None,
    taxonomy_issue_count: int,
) -> dict[str, Any]:
    graph_errors = [item for item in graph_audit_report.get("errors", []) if isinstance(item, dict)]
    by_code = _issues_by_code(graph_errors)
    groups: list[dict[str, Any]] = []

    def add_group(
        route: str,
        *,
        count: int,
        automatic: bool,
        reason: str,
        next_action: str,
        codes: list[str] | None = None,
        sample: list[dict[str, Any]] | None = None,
    ) -> None:
        if count <= 0:
            return
        groups.append(
            {
                "route": route,
                "count": count,
                "automatic": automatic,
                "reason": reason,
                "next_action": next_action,
                "codes": codes or [],
                "sample": sample or [],
            }
        )

    add_group(
        "io_retry",
        count=len(write_errors),
        automatic=False,
        reason="Arquivos bloqueados para escrita impedem confirmar reparos antes do linker.",
        next_action="Liberar iCloud/Obsidian/antivirus/processo que bloqueou o arquivo e rodar fix-wiki --apply --backup --json novamente.",
        sample=write_errors[:5],
    )

    deterministic_codes = ["dangling_link", "self_link", "ambiguous_link"]
    deterministic_issues = [issue for code in deterministic_codes for issue in by_code.get(code, [])]
    graph_fix_next_action = (
        "Rodar fix-wiki --apply --backup --json; o graph_fix vai remover esses WikiLinks inválidos antes do linker."
        if not apply
        else "O graph_fix já tentou reparar nesta rodada; se persistiu, tratar como bug do reparo ou arquivo que não pôde ser escrito."
    )
    add_group(
        "graph_fix_retry",
        count=len(deterministic_issues),
        automatic=True,
        reason="São blockers determinísticos que o graph_fix remove convertendo WikiLinks inválidos em texto visível.",
        next_action=graph_fix_next_action,
        codes=deterministic_codes,
        sample=_issue_sample(deterministic_issues),
    )

    duplicate_issues = by_code.get("duplicate_stem", [])
    add_group(
        "duplicate_merge_required",
        count=len(duplicate_issues),
        automatic=False,
        reason="Duplicatas exatas são removidas automaticamente; duplicatas divergentes exigem merge/revisão clínica antes de apagar qualquer nota.",
        next_action="Comparar as notas do sample, fundir conteúdo quando necessário, manter um único target Obsidian e rodar fix-wiki novamente.",
        codes=["duplicate_stem"],
        sample=_issue_sample(duplicate_issues),
    )

    catalog_codes = [
        "catalog_invalid_json",
        "catalog_entry_missing_target",
        "catalog_target_missing",
        "catalog_target_ambiguous",
        "alias_conflict",
    ]
    catalog_issues = [issue for code in catalog_codes for issue in by_code.get(code, [])]
    add_group(
        "catalog_repair",
        count=len(catalog_issues),
        automatic=True,
        reason="O blocker está no catálogo/alias, não na nota; o linker precisa de catálogo sem alvo ausente ou ambíguo.",
        next_action="Rodar med-catalog-curator ou corrigir CATALOGO_WIKI.json, depois fix-wiki --apply --backup --json.",
        codes=catalog_codes,
        sample=_issue_sample(catalog_issues),
    )

    other_issues = [
        issue
        for issue in graph_errors
        if issue.get("code") not in {*deterministic_codes, "duplicate_stem", *catalog_codes}
    ]
    add_group(
        "unknown_graph_blocker",
        count=len(other_issues),
        automatic=False,
        reason="Tipo de blocker ainda não tem reparo determinístico conhecido.",
        next_action="Inspecionar o sample, corrigir a causa e adicionar reparo determinístico se for recorrente.",
        sample=_issue_sample(other_issues),
    )

    rewrite_count = int(rewrite_plan.get("item_count", 0)) if isinstance(rewrite_plan, dict) else 0
    add_group(
        "style_rewrite",
        count=rewrite_count,
        automatic=True,
        reason="A nota precisa de reescrita estrutural; fix-note não deve inventar seções clínicas ausentes.",
        next_action="Rodar plan-subagents --phase style-rewrite, aplicar via apply-style-rewrite e repetir fix-wiki.",
    )

    add_group(
        "taxonomy_migrate",
        count=taxonomy_issue_count,
        automatic=True,
        reason="Taxonomia precisa ser resolvida com plano, recibo e rollback.",
        next_action="Rodar taxonomy-migrate --dry-run, aplicar plano sem blockers e repetir fix-wiki.",
    )

    return {
        "schema": BLOCKER_RESOLUTION_SCHEMA,
        "remaining_graph_blocker_count": len(graph_errors),
        "write_error_count": len(write_errors),
        "requires_llm_rewrite_count": rewrite_count,
        "taxonomy_issue_count": taxonomy_issue_count,
        "group_count": len(groups),
        "groups": groups,
        "has_blockers": bool(groups),
        "linker_can_apply": not groups,
        "next_action": groups[0]["next_action"] if groups else "Aplicar linker; não há blockers pendentes.",
    }


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
    write_errors = [*style_fix.get("write_errors", []), *graph_fix.get("write_errors", [])]
    write_error_count = len(write_errors)
    style_audit = validate_wiki_style(config.wiki_dir)
    rewrite_plan = _style_rewrite_plan_if_needed(config, style_audit)
    graph_before = graph_audit(config)
    linker_dry_run = run_linker(config, dry_run=True)
    blocker_resolution = _blocker_resolution_plan(
        apply=apply,
        graph_audit_report=graph_before,
        write_errors=write_errors,
        rewrite_plan=rewrite_plan,
        taxonomy_issue_count=taxonomy_issue_count,
    )
    linker_apply: dict[str, Any] | None = None
    linker_skipped_reason = ""
    linker_backup_paths: list[str] = []

    if apply:
        if write_error_count:
            linker_skipped_reason = "write_errors"
        elif rewrite_plan and rewrite_plan.get("item_count", 0):
            linker_skipped_reason = "requires_llm_rewrite"
        elif linker_dry_run.get("blocker_count", 0):
            linker_skipped_reason = "graph_blockers"
        elif not blocker_resolution.get("linker_can_apply", False):
            if taxonomy_issue_count:
                linker_skipped_reason = "taxonomy_action_required"
            else:
                linker_skipped_reason = "blocker_resolution"
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
        "write_error_count": write_error_count,
        "write_errors": write_errors,
        "graph_audit": graph_before,
        "graph_error_count": graph_before.get("error_count", 0),
        "graph_warning_count": graph_before.get("warning_count", 0),
        "linker_dry_run": linker_dry_run,
        "blocker_resolution": blocker_resolution,
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
