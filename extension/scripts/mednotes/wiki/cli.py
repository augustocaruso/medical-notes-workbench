"""Command-line interface for deterministic Wiki workflow operations."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wiki.api import (
    EXIT_LINKER,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_VALIDATION,
    MedOpsError,
    ValidationError,
    _json,
    _now_iso,
    _path,
    _write_json_atomic,
    apply_style_rewrite,
    apply_taxonomy_migration,
    canonical_taxonomy_tree,
    fix_note_style_file,
    fix_wiki_health,
    graph_audit,
    list_by_status,
    mutate_raw_frontmatter,
    plan_subagents,
    publish_batch,
    resolve_config,
    resolve_taxonomy,
    rollback_taxonomy_migration,
    run_linker,
    stage_note,
    taxonomy_audit,
    taxonomy_migration_plan,
    taxonomy_tree,
    validate_note_style_file,
    validate_wiki_style,
    validate_config,
)


def _add_common(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument("--config", default=default, help="Optional config.toml. Reads [chat_processor].")
    parser.add_argument("--raw-dir", default=default, help="Override Chats_Raw directory.")
    parser.add_argument("--wiki-dir", default=default, help="Override Wiki_Medicina directory.")
    parser.add_argument("--linker-path", default=default, help="Override med-auto-linker script path.")
    parser.add_argument("--catalog-path", default=default, help="Override CATALOGO_WIKI.json path.")


def _add_taxonomy_creation_mode(parser: argparse.ArgumentParser) -> None:
    parser.set_defaults(allow_new_taxonomy_leaf=True)
    parser.add_argument(
        "--strict-existing-taxonomy",
        action="store_false",
        dest="allow_new_taxonomy_leaf",
        help="Require the final non-canonical taxonomy leaf to already exist.",
    )
    parser.add_argument(
        "--allow-new-taxonomy-leaf",
        action="store_true",
        dest="allow_new_taxonomy_leaf",
        help=argparse.SUPPRESS,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Medical Notes Workbench deterministic chat-processing operations.")
    _add_common(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    pending = sub.add_parser("list-pending", help="List raw chats with no status or status=pendente.")
    _add_common(pending, suppress_defaults=True)
    triados = sub.add_parser("list-triados", help="List raw chats with status=triado and tipo=medicina.")
    _add_common(triados, suppress_defaults=True)

    plan_agents = sub.add_parser("plan-subagents", help="Build a safe subagent work plan for process-chats.")
    _add_common(plan_agents, suppress_defaults=True)
    plan_agents.add_argument("--phase", choices=("triage", "architect", "style-rewrite"), required=True)
    plan_agents.add_argument("--max-concurrency", type=int, default=0)
    plan_agents.add_argument("--temp-root", help="Base temporary directory for isolated architect work.")

    taxonomy_canonical = sub.add_parser("taxonomy-canonical", help="Print the canonical Wiki_Medicina taxonomy.")
    _add_common(taxonomy_canonical, suppress_defaults=True)

    taxonomy = sub.add_parser("taxonomy-tree", help="List existing Wiki_Medicina taxonomy folders.")
    _add_common(taxonomy, suppress_defaults=True)
    taxonomy.add_argument("--max-depth", type=int, default=0, help="Limit folder depth; 0 means all depths.")

    taxonomy_audit_parser = sub.add_parser("taxonomy-audit", help="Dry-run audit of the vault against the canonical taxonomy.")
    _add_common(taxonomy_audit_parser, suppress_defaults=True)

    taxonomy_migrate = sub.add_parser("taxonomy-migrate", help="Plan, apply, or roll back conservative taxonomy directory moves.")
    _add_common(taxonomy_migrate, suppress_defaults=True)
    migrate_mode = taxonomy_migrate.add_mutually_exclusive_group()
    migrate_mode.add_argument("--dry-run", action="store_true", help="Generate a migration plan without moving files. Default mode.")
    migrate_mode.add_argument("--apply", action="store_true", help="Apply a previously generated migration plan.")
    migrate_mode.add_argument("--rollback", action="store_true", help="Rollback a migration receipt.")
    taxonomy_migrate.add_argument("--plan", help="Plan JSON path. Required with --apply.")
    taxonomy_migrate.add_argument("--plan-output", help="Write generated dry-run plan to this path.")
    taxonomy_migrate.add_argument("--receipt", help="Receipt path for --apply output or --rollback input.")

    taxonomy_resolve = sub.add_parser("taxonomy-resolve", help="Validate and canonicalize one taxonomy against the existing wiki tree.")
    _add_common(taxonomy_resolve, suppress_defaults=True)
    taxonomy_resolve.add_argument("--taxonomy", required=True)
    taxonomy_resolve.add_argument("--title", help="Optional note title; rejects taxonomy/title duplication when provided.")
    _add_taxonomy_creation_mode(taxonomy_resolve)

    triage = sub.add_parser("triage", help="Mark one raw chat as triaged.")
    _add_common(triage, suppress_defaults=True)
    triage.add_argument("--raw-file", required=True)
    triage.add_argument("--tipo", default="medicina")
    triage.add_argument("--titulo", required=True)
    triage.add_argument("--fonte-id", default="")
    triage.add_argument("--dry-run", action="store_true")
    triage.add_argument("--backup", action="store_true", help="Create a .bak file before mutating raw chat frontmatter.")

    discard = sub.add_parser("discard", help="Mark one raw chat as discarded.")
    _add_common(discard, suppress_defaults=True)
    discard.add_argument("--raw-file", required=True)
    discard.add_argument("--reason", required=True)
    discard.add_argument("--dry-run", action="store_true")
    discard.add_argument("--backup", action="store_true", help="Create a .bak file before mutating raw chat frontmatter.")

    stage = sub.add_parser("stage-note", help="Append a generated note to a manifest.")
    _add_common(stage, suppress_defaults=True)
    stage.add_argument("--manifest", required=True)
    stage.add_argument("--raw-file", required=True)
    stage.add_argument("--taxonomy", required=True)
    stage.add_argument("--title", required=True)
    stage.add_argument("--content", required=True)
    stage.add_argument("--dry-run", action="store_true")
    _add_taxonomy_creation_mode(stage)

    publish = sub.add_parser("publish-batch", help="Publish all notes from a manifest, then mark raw files processed.")
    _add_common(publish, suppress_defaults=True)
    publish.add_argument("--manifest", required=True)
    publish.add_argument("--dry-run", action="store_true")
    publish.add_argument("--backup", action="store_true", help="Create .bak files before mutating raw chat frontmatter.")
    publish.add_argument("--collision", choices=("abort", "suffix"), default="abort")
    _add_taxonomy_creation_mode(publish)

    commit = sub.add_parser("commit-batch", help="Compatibility alias for publish-batch.")
    _add_common(commit, suppress_defaults=True)
    commit.add_argument("--manifest", required=True)
    commit.add_argument("--dry-run", action="store_true")
    commit.add_argument("--backup", action="store_true", help="Create .bak files before mutating raw chat frontmatter.")
    commit.add_argument("--collision", choices=("abort", "suffix"), default="abort")
    _add_taxonomy_creation_mode(commit)

    linker = sub.add_parser("run-linker", help="Run configured semantic linker once.")
    _add_common(linker, suppress_defaults=True)
    linker.add_argument("--dry-run", action="store_true")
    linker.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    graph = sub.add_parser("graph-audit", help="Audit Wiki_Medicina link graph health without writing files.")
    _add_common(graph, suppress_defaults=True)
    graph.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    validate_note = sub.add_parser("validate-note", help="Validate one generated Wiki_Medicina note style.")
    _add_common(validate_note, suppress_defaults=True)
    validate_note.add_argument("--content", required=True, help="Generated Markdown note to validate.")
    validate_note.add_argument("--title", required=True, help="Expected note title / level-1 heading.")
    validate_note.add_argument("--raw-file", help="Optional raw chat file for exact Chat Original validation.")
    validate_note.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    fix_note = sub.add_parser("fix-note", help="Apply deterministic style fixes to one generated Wiki_Medicina note.")
    _add_common(fix_note, suppress_defaults=True)
    fix_note.add_argument("--content", required=True, help="Generated Markdown note to fix.")
    fix_note.add_argument("--title", required=True, help="Expected note title / level-1 heading.")
    fix_note.add_argument("--raw-file", help="Optional raw chat file for exact Chat Original validation.")
    fix_note.add_argument("--output", required=True, help="Write fixed Markdown to this path.")
    fix_note.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    validate_wiki = sub.add_parser("validate-wiki", help="Audit all Markdown notes under Wiki_Medicina without writing files.")
    _add_common(validate_wiki, suppress_defaults=True)
    validate_wiki.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    fix_wiki = sub.add_parser("fix-wiki", help="Audit/fix Wiki_Medicina style and graph health.")
    _add_common(fix_wiki, suppress_defaults=True)
    fix_wiki.add_argument("--apply", action="store_true", help="Write changes in-place. Without this, only reports what would change.")
    fix_wiki.add_argument("--backup", action="store_true", help="Create .bak files before mutating notes when --apply is used.")
    fix_wiki.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    apply_rewrite = sub.add_parser("apply-style-rewrite", help="Validate and apply an LLM-rewritten Wiki_Medicina note.")
    _add_common(apply_rewrite, suppress_defaults=True)
    apply_rewrite.add_argument("--target", required=True, help="Existing Wiki_Medicina note to replace.")
    apply_rewrite.add_argument("--content", required=True, help="Temporary rewritten Markdown note.")
    apply_rewrite.add_argument("--dry-run", action="store_true", help="Validate and report without writing.")
    apply_rewrite.add_argument("--backup", action="store_true", help="Create a .bak file before replacing the target note.")
    apply_rewrite.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")

    validate = sub.add_parser("validate", help="Print resolved paths and existence checks.")
    _add_common(validate, suppress_defaults=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = resolve_config(args)
        if args.command == "list-pending":
            _json(list_by_status(config.raw_dir, "pending"))
        elif args.command == "list-triados":
            _json(list_by_status(config.raw_dir, "triados"))
        elif args.command == "plan-subagents":
            _json(
                plan_subagents(
                    config,
                    args.phase,
                    max_concurrency=args.max_concurrency or None,
                    temp_root=_path(args.temp_root) if args.temp_root else None,
                )
            )
        elif args.command == "taxonomy-canonical":
            _json(canonical_taxonomy_tree())
        elif args.command == "taxonomy-tree":
            _json(taxonomy_tree(config.wiki_dir, max_depth=args.max_depth))
        elif args.command == "taxonomy-audit":
            _json(taxonomy_audit(config.wiki_dir))
        elif args.command == "taxonomy-migrate":
            if args.rollback:
                if not args.receipt:
                    raise ValidationError("--receipt is required with --rollback")
                _json(rollback_taxonomy_migration(_path(args.receipt), config))
            elif args.apply:
                if not args.plan:
                    raise ValidationError("--plan is required with --apply")
                _json(apply_taxonomy_migration(_path(args.plan), config, receipt_path=_path(args.receipt) if args.receipt else None))
            else:
                plan = taxonomy_migration_plan(config.wiki_dir)
                if args.plan_output:
                    output = _path(args.plan_output)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    _write_json_atomic(output, plan)
                    plan["plan_path"] = str(output)
                _json(plan)
        elif args.command == "taxonomy-resolve":
            resolved = resolve_taxonomy(
                config.wiki_dir,
                args.taxonomy,
                title=args.title,
                allow_new_leaf=args.allow_new_taxonomy_leaf,
            )
            _json(resolved.to_json(config.wiki_dir, title=args.title))
        elif args.command == "triage":
            _json(
                mutate_raw_frontmatter(
                    _path(args.raw_file),
                    {
                        "tipo": args.tipo,
                        "status": "triado",
                        "data_importacao": date.today().isoformat(),
                        "fonte_id": args.fonte_id,
                        "titulo_triagem": args.titulo,
                    },
                    dry_run=args.dry_run,
                    backup=getattr(args, "backup", False),
                )
            )
        elif args.command == "discard":
            _json(
                mutate_raw_frontmatter(
                    _path(args.raw_file),
                    {"status": "descartado", "discard_reason": args.reason, "discarded_at": _now_iso()},
                    dry_run=args.dry_run,
                    backup=getattr(args, "backup", False),
                )
            )
        elif args.command == "stage-note":
            _json(
                stage_note(
                    _path(args.manifest),
                    _path(args.raw_file),
                    args.taxonomy,
                    args.title,
                    _path(args.content),
                    args.dry_run,
                    config=config,
                    allow_new_taxonomy_leaf=args.allow_new_taxonomy_leaf,
                )
            )
        elif args.command in {"publish-batch", "commit-batch"}:
            _json(
                publish_batch(
                    _path(args.manifest),
                    config,
                    collision=args.collision,
                    dry_run=args.dry_run,
                    backup=args.backup,
                    allow_new_taxonomy_leaf=args.allow_new_taxonomy_leaf,
                )
            )
        elif args.command == "run-linker":
            result = run_linker(config, dry_run=args.dry_run)
            _json(result)
            if not result.get("dry_run") and result.get("returncode", 0) != 0:
                return EXIT_LINKER
        elif args.command == "graph-audit":
            report = graph_audit(config)
            _json(report)
            if report.get("error_count", 0):
                return EXIT_VALIDATION
        elif args.command == "validate-note":
            report = validate_note_style_file(
                _path(args.content),
                args.title,
                raw_file=_path(args.raw_file) if args.raw_file else None,
            )
            _json(report)
            if report["errors"]:
                return EXIT_VALIDATION
        elif args.command == "fix-note":
            report = fix_note_style_file(
                _path(args.content),
                args.title,
                _path(args.output),
                raw_file=_path(args.raw_file) if args.raw_file else None,
            )
            _json(report)
            if report["errors"]:
                return EXIT_VALIDATION
        elif args.command == "validate-wiki":
            audit = validate_wiki_style(config.wiki_dir)
            _json(audit)
            if audit["error_count"]:
                return EXIT_VALIDATION
        elif args.command == "fix-wiki":
            report = fix_wiki_health(config, apply=args.apply, backup=args.backup)
            _json(report)
            if report["error_count"] or report.get("graph_error_count", 0) or report.get("taxonomy_action_required"):
                return EXIT_VALIDATION
            linker_apply = report.get("linker_apply")
            if isinstance(linker_apply, dict) and linker_apply.get("returncode", 0) != 0:
                return EXIT_LINKER
        elif args.command == "apply-style-rewrite":
            result = apply_style_rewrite(
                _path(args.target),
                _path(args.content),
                dry_run=args.dry_run,
                backup=args.backup,
            )
            _json(result)
            if result["validation"]["errors"]:
                return EXIT_VALIDATION
        elif args.command == "validate":
            _json(validate_config(config))
        else:  # pragma: no cover - argparse prevents this
            parser.print_help()
            return EXIT_USAGE
        return EXIT_OK
    except MedOpsError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
