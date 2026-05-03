"""High-level Wiki health workflow (`fix-wiki`)."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wiki.agents import plan_subagents
from wiki.common import BLOCKER_RESOLUTION_SCHEMA, FileWriteError, WIKI_HEALTH_FIX_SCHEMA
from wiki.config import MedConfig, _path
from wiki.graph_fixes import fix_wiki_graph
from wiki.hygiene import cleanup_wiki_hygiene, collect_wiki_hygiene
from wiki.linking import graph_audit, run_linker
from wiki.raw_chats import atomic_write_text, create_backup
from wiki.style import _requires_style_rewrite, fix_wiki_style, validate_wiki_style
from wiki.taxonomy import apply_taxonomy_migration, taxonomy_audit, taxonomy_migration_plan
from wiki.workflow_guardrails import FIX_WIKI_REQUIRED_INPUTS, annotate_payload


def _style_rewrite_plan_if_needed(config: MedConfig, audit: dict[str, Any]) -> dict[str, Any] | None:
    if not _requires_style_rewrite(audit):
        return None
    return plan_subagents(config, "style-rewrite", max_concurrency=3)


def _taxonomy_action_issue_count(audit: dict[str, Any]) -> int:
    action_keys = (
        "proposed_moves",
        "unmapped_top_level_dirs",
        "duplicate_destinations",
        "root_notes",
    )
    return sum(len(audit.get(key, [])) for key in action_keys)


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_dir(run_id: str) -> Path:
    return _path(f"~/.gemini/medical-notes-workbench/runs/{run_id}")


def _archive_root(run_id: str) -> Path:
    day = run_id[:8]
    return _path(f"~/.gemini/backup_archive/fix-wiki/{day}/{run_id}")


def _write_json_file(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _try_write_json_file(path: Path, data: dict[str, Any]) -> str | None:
    try:
        _write_json_file(path, data)
    except (FileWriteError, OSError) as exc:
        return str(exc)
    return None


def _quote_arg(value: str | Path) -> str:
    return '"' + str(value).replace('"', '\\"') + '"'


def _fix_wiki_command(config: MedConfig, *, apply: bool, backup: bool) -> str:
    flags = ["--wiki-dir", _quote_arg(config.wiki_dir), "fix-wiki"]
    flags.append("--apply" if apply else "--dry-run")
    if backup:
        flags.append("--backup")
    flags.append("--json")
    return "uv run python scripts/mednotes/med_ops.py " + " ".join(str(flag) for flag in flags)


def _rollback_command(config: MedConfig, receipt_path: str | None) -> str | None:
    if not receipt_path:
        return None
    return (
        "uv run python scripts/mednotes/med_ops.py "
        f"--wiki-dir {_quote_arg(config.wiki_dir)} "
        f"taxonomy-migrate --rollback --receipt {_quote_arg(receipt_path)}"
    )


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
    taxonomy_plan: dict[str, Any],
    taxonomy_issue_count: int,
) -> dict[str, Any]:
    graph_errors = [item for item in graph_audit_report.get("errors", []) if isinstance(item, dict)]
    by_code = _issues_by_code(graph_errors)
    taxonomy_operations = [item for item in taxonomy_plan.get("operations", []) if isinstance(item, dict)]
    taxonomy_blocked = [item for item in taxonomy_plan.get("blocked", []) if isinstance(item, dict)]
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

    if taxonomy_operations and not apply:
        add_group(
            "taxonomy_migrate",
            count=len(taxonomy_operations),
            automatic=True,
            reason="Taxonomia tem movimentos determinísticos que o modo --apply pode executar com recibo e rollback.",
            next_action="Rodar fix-wiki --apply --backup --json; o workflow vai aplicar movimentos seguros e revalidar.",
            sample=[
                {
                    "source": item.get("source"),
                    "destination": item.get("destination"),
                    "reason": item.get("reason"),
                }
                for item in taxonomy_operations[:5]
            ],
        )
    add_group(
        "taxonomy_review_required",
        count=len(taxonomy_blocked),
        automatic=False,
        reason="A taxonomia restante não tem destino único seguro.",
        next_action="Revisar os itens do sample, resolver a classificação e rodar fix-wiki --apply --backup --json novamente.",
        sample=[
            {
                "source": item.get("source"),
                "destination": item.get("destination"),
                "reason": item.get("blocked_reason") or item.get("reason"),
            }
            for item in taxonomy_blocked[:5]
        ],
    )

    return {
        "schema": BLOCKER_RESOLUTION_SCHEMA,
        "remaining_graph_blocker_count": len(graph_errors),
        "write_error_count": len(write_errors),
        "requires_llm_rewrite_count": rewrite_count,
        "taxonomy_issue_count": taxonomy_issue_count,
        "taxonomy_operation_count": len(taxonomy_operations),
        "taxonomy_blocked_count": len(taxonomy_blocked),
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
    run_id = _run_id()
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    archive_root = _archive_root(run_id)

    hygiene_before = collect_wiki_hygiene(config.wiki_dir)
    hygiene_pre_cleanup = (
        cleanup_wiki_hygiene(
            config.wiki_dir,
            archive_root=archive_root / "preflight",
            archive_backups=True,
            remove_rewrites=True,
            remove_empty_dirs=True,
        )
        if apply and (hygiene_before.get("bak_or_rewrite", 0) or hygiene_before.get("empty_dirs", 0))
        else None
    )
    hygiene_after_preflight = collect_wiki_hygiene(config.wiki_dir)
    taxonomy_initial_report = taxonomy_audit(config.wiki_dir)
    taxonomy_initial_plan = taxonomy_migration_plan(config.wiki_dir)
    taxonomy_apply: dict[str, Any] | None = None
    taxonomy_plan_path: str | None = None
    taxonomy_receipt_path: str | None = None

    if apply and taxonomy_initial_plan.get("operations"):
        plan_path = run_dir / "taxonomy-plan.json"
        receipt_path = run_dir / "taxonomy-receipt.json"
        _write_json_file(plan_path, taxonomy_initial_plan)
        taxonomy_plan_path = str(plan_path)
        taxonomy_receipt_path = str(receipt_path)
        taxonomy_apply = apply_taxonomy_migration(plan_path, config, receipt_path=receipt_path)

    taxonomy_report = taxonomy_audit(config.wiki_dir)
    taxonomy_plan_after = taxonomy_migration_plan(config.wiki_dir)
    taxonomy_issue_count = _taxonomy_action_issue_count(taxonomy_report)
    style_fix = fix_wiki_style(config.wiki_dir, apply=apply, backup=backup)
    graph_fix = fix_wiki_graph(config.wiki_dir, catalog_path=config.catalog_path, apply=apply, backup=backup)
    write_errors = [*style_fix.get("write_errors", []), *graph_fix.get("write_errors", [])]
    write_error_count = len(write_errors)
    style_audit = validate_wiki_style(config.wiki_dir)
    rewrite_plan = _style_rewrite_plan_if_needed(config, style_audit)
    graph_before_linker = graph_audit(config)
    linker_dry_run = run_linker(config, dry_run=True)
    blocker_resolution = _blocker_resolution_plan(
        apply=apply,
        graph_audit_report=graph_before_linker,
        write_errors=write_errors,
        rewrite_plan=rewrite_plan,
        taxonomy_plan=taxonomy_plan_after,
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
        elif graph_before_linker.get("error_count", 0) or linker_dry_run.get("blocker_count", 0):
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
    hygiene_cleanup = (
        cleanup_wiki_hygiene(
            config.wiki_dir,
            archive_root=archive_root / "final",
            archive_backups=True,
            remove_rewrites=True,
            remove_empty_dirs=True,
        )
        if apply
        else None
    )
    hygiene_after = collect_wiki_hygiene(config.wiki_dir)
    backup_cleanup = (
        {
            **hygiene_cleanup,
            "deleted_count": hygiene_cleanup.get("removed_empty_dir_count", 0),
            "kept_count": 0,
            "retention_days": backup_retention_days,
            "max_per_file": backup_max_per_file,
        }
        if hygiene_cleanup
        else None
    )
    taxonomy_action_required = bool(taxonomy_issue_count)
    requires_llm_rewrite_count = sum(1 for item in style_audit.get("reports", []) if item.get("requires_llm_rewrite"))
    graph_error_count = int(graph_after.get("error_count", 0) or 0)
    hygiene_error_count = int(hygiene_cleanup.get("error_count", 0) if hygiene_cleanup else 0) + int(
        hygiene_pre_cleanup.get("error_count", 0) if hygiene_pre_cleanup else 0
    )
    human_decision_required = any(
        bool(group)
        for group in blocker_resolution.get("groups", [])
        if isinstance(group, dict) and not group.get("automatic", False)
    )
    status = _status(
        write_error_count=write_error_count,
        requires_llm_rewrite_count=requires_llm_rewrite_count,
        graph_error_count=graph_error_count,
        taxonomy_action_required=taxonomy_action_required,
        hygiene_error_count=hygiene_error_count,
        human_decision_required=human_decision_required,
        warning_count=int(graph_after.get("warning_count", 0) or 0),
    )
    rollback_cmd = _rollback_command(config, taxonomy_apply.get("receipt_path") if taxonomy_apply else taxonomy_receipt_path)
    next_command = None if human_decision_required or status == "completed" else _fix_wiki_command(config, apply=True, backup=backup or apply)
    total_changed_count = _total_changed_count(
        style_fix=style_fix,
        graph_fix=graph_fix,
        taxonomy_apply=taxonomy_apply,
        linker_apply=linker_apply,
        hygiene_pre_cleanup=hygiene_pre_cleanup,
        hygiene_cleanup=hygiene_cleanup,
    )

    blocked_reason = ""
    if write_error_count:
        blocked_reason = "write_errors"
    elif requires_llm_rewrite_count:
        blocked_reason = "requires_llm_rewrite"
    elif graph_error_count:
        blocked_reason = "graph_blockers"
    elif taxonomy_action_required:
        blocked_reason = "taxonomy_action_required"
    elif human_decision_required:
        blocked_reason = "human_decision_required"

    report = annotate_payload({
        **style_fix,
        "schema": WIKI_HEALTH_FIX_SCHEMA,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "status": status,
        "summary": _summary(
            status=status,
            total_changed_count=total_changed_count,
            graph_error_count=graph_error_count,
            taxonomy_action_required=taxonomy_action_required,
            human_decision_required=human_decision_required,
        ),
        "safe_for_agent": True,
        "next_command": next_command,
        "resume_command": _fix_wiki_command(config, apply=apply, backup=backup),
        "rollback_command": rollback_cmd,
        "human_decision_required": human_decision_required,
        "human_decisions": _human_decisions(blocker_resolution),
        "total_changed_count": total_changed_count,
        "hygiene_before": hygiene_before,
        "hygiene_pre_cleanup": hygiene_pre_cleanup,
        "hygiene_after_preflight": hygiene_after_preflight,
        "hygiene_cleanup": hygiene_cleanup,
        "hygiene_after": hygiene_after,
        "style_fix": style_fix,
        "graph_fix": graph_fix,
        "style_audit": style_audit,
        "taxonomy_initial_audit": taxonomy_initial_report,
        "taxonomy_initial_plan": taxonomy_initial_plan,
        "taxonomy_plan_path": taxonomy_plan_path,
        "taxonomy_apply": taxonomy_apply,
        "taxonomy_receipt_path": taxonomy_apply.get("receipt_path") if taxonomy_apply else taxonomy_receipt_path,
        "taxonomy_plan_after": taxonomy_plan_after,
        "taxonomy_audit": taxonomy_report,
        "taxonomy_action_required": taxonomy_action_required,
        "taxonomy_issue_count": taxonomy_issue_count,
        "taxonomy_missing_canonical_dir_count": len(taxonomy_report.get("missing_canonical_dirs", [])),
        "taxonomy_proposed_move_count": len(taxonomy_report.get("proposed_moves", [])),
        "taxonomy_initial_proposed_move_count": len(taxonomy_initial_report.get("proposed_moves", [])),
        "taxonomy_applied_move_count": int(taxonomy_apply.get("applied_count", 0)) if taxonomy_apply else 0,
        "taxonomy_unmapped_top_level_dir_count": len(taxonomy_report.get("unmapped_top_level_dirs", [])),
        "taxonomy_duplicate_destination_count": len(taxonomy_report.get("duplicate_destinations", [])),
        "taxonomy_duplicate_directory_group_count": len(taxonomy_report.get("duplicate_directory_groups", [])),
        "taxonomy_root_note_count": len(taxonomy_report.get("root_notes", [])),
        "requires_llm_rewrite_count": requires_llm_rewrite_count,
        "style_rewrite_plan": rewrite_plan,
        "write_error_count": write_error_count,
        "write_errors": write_errors,
        "graph_audit": graph_before_linker,
        "graph_audit_before_linker": graph_before_linker,
        "graph_error_count": graph_error_count,
        "graph_error_count_before_linker": graph_before_linker.get("error_count", 0),
        "graph_warning_count": graph_after.get("warning_count", 0),
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
        "final_validation": {
            "graph": {
                "error_count": graph_error_count,
                "blocker_count": graph_after.get("blocker_count", graph_error_count),
                "orphan_count": graph_after.get("metrics", {}).get("orphan_count", 0),
            },
            "hygiene": {
                "bak_or_rewrite": hygiene_after.get("bak_or_rewrite", 0),
                "empty_dirs": hygiene_after.get("empty_dirs", 0),
                "duplicate_hash_groups": hygiene_after.get("duplicate_hash_groups", 0),
                "duplicate_filename_groups": hygiene_after.get("duplicate_filename_groups", 0),
            },
            "taxonomy": {
                "proposed_moves": len(taxonomy_report.get("proposed_moves", [])),
                "blocked": len(taxonomy_plan_after.get("blocked", [])),
                "duplicate_directory_groups": len(taxonomy_report.get("duplicate_directory_groups", [])),
                "ignored_items": ["attachments", "_Mock_Embeds", "_Índice_Medicina.md"],
            },
        },
    },
        phase="fix_wiki_apply" if apply else "fix_wiki_dry_run",
        status=status,
        blocked_reason=blocked_reason,
        next_action=next_command or blocker_resolution.get("next_action") or "",
        required_inputs=FIX_WIKI_REQUIRED_INPUTS,
        human_decision_required=human_decision_required,
    )
    report["compact_report_path"] = str(run_dir / "compact-report.json")
    report["full_report_path"] = str(run_dir / "full-report.json")
    report["run_state_path"] = str(run_dir / "run_state.json")
    report_write_errors = []
    compact_error = _try_write_json_file(run_dir / "compact-report.json", _compact_report(report))
    if compact_error:
        report_write_errors.append({"path": report["compact_report_path"], "error": compact_error})
    state_error = _try_write_json_file(run_dir / "run_state.json", _run_state(report))
    if state_error:
        report_write_errors.append({"path": report["run_state_path"], "error": state_error})
    full_error = _try_write_json_file(run_dir / "full-report.json", report)
    if full_error:
        report_write_errors.append({"path": report["full_report_path"], "error": full_error})
    report["report_write_error_count"] = len(report_write_errors)
    report["report_write_errors"] = report_write_errors
    return report


def _status(
    *,
    write_error_count: int,
    requires_llm_rewrite_count: int,
    graph_error_count: int,
    taxonomy_action_required: bool,
    hygiene_error_count: int,
    human_decision_required: bool,
    warning_count: int,
) -> str:
    if write_error_count or hygiene_error_count:
        return "failed"
    if human_decision_required or requires_llm_rewrite_count or graph_error_count or taxonomy_action_required:
        return "blocked"
    if warning_count:
        return "completed_with_warnings"
    return "completed"


def _summary(
    *,
    status: str,
    total_changed_count: int,
    graph_error_count: int,
    taxonomy_action_required: bool,
    human_decision_required: bool,
) -> str:
    if status == "completed":
        return "fix-wiki concluiu sem blockers técnicos."
    if status == "completed_with_warnings":
        return "fix-wiki concluiu os reparos determinísticos e deixou apenas warnings não bloqueantes."
    if human_decision_required:
        return "fix-wiki aplicou reparos determinísticos e parou em decisões humanas/semânticas."
    if graph_error_count:
        return "fix-wiki aplicou reparos determinísticos, mas ainda há blockers de grafo."
    if taxonomy_action_required:
        return "fix-wiki aplicou movimentos seguros, mas ainda há taxonomia sem destino único."
    if total_changed_count:
        return "fix-wiki aplicou mudanças; rode novamente se houver next_command."
    return "fix-wiki está bloqueado por pendência operacional."


def _total_changed_count(
    *,
    style_fix: dict[str, Any],
    graph_fix: dict[str, Any],
    taxonomy_apply: dict[str, Any] | None,
    linker_apply: dict[str, Any] | None,
    hygiene_pre_cleanup: dict[str, Any] | None,
    hygiene_cleanup: dict[str, Any] | None,
) -> int:
    return (
        int(style_fix.get("written_count", 0) or 0)
        + int(graph_fix.get("written_count", 0) or 0)
        + int(taxonomy_apply.get("applied_count", 0) if taxonomy_apply else 0)
        + int(linker_apply.get("files_changed", 0) if linker_apply else 0)
        + int(hygiene_pre_cleanup.get("archived_count", 0) if hygiene_pre_cleanup else 0)
        + int(hygiene_pre_cleanup.get("removed_empty_dir_count", 0) if hygiene_pre_cleanup else 0)
        + int(hygiene_cleanup.get("archived_count", 0) if hygiene_cleanup else 0)
        + int(hygiene_cleanup.get("removed_empty_dir_count", 0) if hygiene_cleanup else 0)
    )


def _human_decisions(blocker_resolution: dict[str, Any]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for group in blocker_resolution.get("groups", []):
        if not isinstance(group, dict) or group.get("automatic", False):
            continue
        kind = group.get("route", "manual_review")
        options: list[dict[str, str]]
        if kind == "duplicate_merge_required":
            options = [
                {"id": "merge_keep_canonical", "label": "Fundir e manter uma nota canônica"},
                {"id": "rename_split_topics", "label": "Renomear para separar tópicos distintos"},
            ]
        elif kind == "taxonomy_review_required":
            options = [
                {"id": "choose_taxonomy", "label": "Escolher a taxonomia correta"},
                {"id": "defer_move", "label": "Adiar migração e manter como está"},
            ]
        elif kind == "io_retry":
            options = [
                {"id": "retry_now", "label": "Liberar arquivo e tentar novamente"},
                {"id": "stop_and_inspect", "label": "Parar para inspecionar o bloqueio externo"},
            ]
        else:
            options = [
                {"id": "continue_safely", "label": "Escolher a rota segura sugerida"},
                {"id": "stop_and_review", "label": "Parar e revisar manualmente"},
            ]
        decisions.append(
            {
                "kind": kind,
                "question": group.get("reason", "Revisão humana necessária."),
                "prompt": (
                    "Escolha o caminho humano para este blocker; depois continue o workflow pela rota segura indicada."
                ),
                "options": options,
                "items": group.get("sample", [])[:5],
                "next_action": group.get("next_action", ""),
                "continue_after_choice": group.get("next_action", ""),
            }
        )
        if len(decisions) >= 5:
            break
    return decisions


def _compact_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": report.get("schema"),
        "run_id": report.get("run_id"),
        "phase": report.get("phase"),
        "status": report.get("status"),
        "blocked_reason": report.get("blocked_reason"),
        "safe_for_agent": report.get("safe_for_agent"),
        "summary": report.get("summary"),
        "wiki_dir": report.get("wiki_dir"),
        "dry_run": report.get("dry_run"),
        "apply": report.get("apply"),
        "changed_count": report.get("changed_count"),
        "total_changed_count": report.get("total_changed_count"),
        "taxonomy_applied_move_count": report.get("taxonomy_applied_move_count"),
        "requires_llm_rewrite_count": report.get("requires_llm_rewrite_count"),
        "linker_applied": report.get("linker_applied"),
        "linker_skipped_reason": report.get("linker_skipped_reason"),
        "graph": report.get("final_validation", {}).get("graph", {}),
        "hygiene": report.get("final_validation", {}).get("hygiene", {}),
        "taxonomy": report.get("final_validation", {}).get("taxonomy", {}),
        "human_decision_required": report.get("human_decision_required"),
        "human_decisions": report.get("human_decisions", []),
        "next_action": report.get("next_action"),
        "required_inputs": report.get("required_inputs", []),
        "next_command": report.get("next_command"),
        "resume_command": report.get("resume_command"),
        "rollback_command": report.get("rollback_command"),
        "compact_report_path": report.get("compact_report_path"),
        "full_report_path": report.get("full_report_path"),
    }


def _run_state(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "medical-notes-workbench.fix-wiki-run-state.v1",
        "run_id": report.get("run_id"),
        "phase": report.get("phase"),
        "status": report.get("status"),
        "blocked_reason": report.get("blocked_reason"),
        "wiki_dir": report.get("wiki_dir"),
        "next_action": report.get("next_action"),
        "next_command": report.get("next_command"),
        "resume_command": report.get("resume_command"),
        "rollback_command": report.get("rollback_command"),
        "human_decision_required": report.get("human_decision_required"),
        "required_inputs": report.get("required_inputs", []),
        "compact_report_path": report.get("compact_report_path"),
        "full_report_path": report.get("full_report_path"),
    }
