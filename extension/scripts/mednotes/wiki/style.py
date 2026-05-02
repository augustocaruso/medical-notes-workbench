"""Wiki_Medicina style validation and deterministic fixes."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from wiki import note_style
from wiki.common import MissingPathError, ValidationError
from wiki.link_terms import is_index_target
from wiki.raw_chats import atomic_write_text, create_backup, read_note_meta


def _style_report_error_message(report: dict[str, Any]) -> str:
    messages = [str(item.get("message", item.get("code", ""))) for item in report.get("errors", [])]
    return "Generated Wiki note does not match the Wiki_Medicina style contract: " + "; ".join(messages)


def validate_wiki_note_contract(content: str, *, title: str, raw_file: Path) -> dict[str, Any]:
    """Reject generated Wiki_Medicina notes that drift from the house style."""

    report = note_style.validate_note_style(
        content,
        title=title,
        raw_meta=read_note_meta(raw_file),
        path=str(raw_file),
    )
    if report["errors"]:
        raise ValidationError(_style_report_error_message(report))
    return report


def validate_note_style_file(content_path: Path, title: str, raw_file: Path | None = None) -> dict[str, Any]:
    if not content_path.exists():
        raise MissingPathError(f"Content file not found: {content_path}")
    if raw_file is not None and not raw_file.exists():
        raise MissingPathError(f"Raw file not found: {raw_file}")
    raw_meta = note_style.raw_meta_from_file(raw_file) if raw_file is not None else {}
    return note_style.validate_note_style(
        content_path.read_text(encoding="utf-8"),
        title=title,
        raw_meta=raw_meta,
        path=str(content_path),
    )


def fix_note_style_file(
    content_path: Path,
    title: str,
    output_path: Path,
    raw_file: Path | None = None,
) -> dict[str, Any]:
    if not content_path.exists():
        raise MissingPathError(f"Content file not found: {content_path}")
    if raw_file is not None and not raw_file.exists():
        raise MissingPathError(f"Raw file not found: {raw_file}")
    raw_meta = note_style.raw_meta_from_file(raw_file) if raw_file is not None else {}
    fixed_content, report = note_style.fix_note_style(
        content_path.read_text(encoding="utf-8"),
        title=title,
        raw_meta=raw_meta,
        path=str(content_path),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output_path, fixed_content)
    report["output_path"] = str(output_path)
    report["wrote_output"] = True
    return report


def validate_wiki_style(wiki_dir: Path) -> dict[str, Any]:
    if not wiki_dir.exists():
        raise MissingPathError(f"Wiki dir not found: {wiki_dir}")
    if not wiki_dir.is_dir():
        raise ValidationError(f"Wiki dir is not a directory: {wiki_dir}")
    return note_style.validate_wiki_dir(wiki_dir)


def fix_wiki_style(wiki_dir: Path, apply: bool = False, backup: bool = False) -> dict[str, Any]:
    if not wiki_dir.exists():
        raise MissingPathError(f"Wiki dir not found: {wiki_dir}")
    if not wiki_dir.is_dir():
        raise ValidationError(f"Wiki dir is not a directory: {wiki_dir}")
    files = sorted(path for path in wiki_dir.rglob("*.md") if path.is_file())
    reports: list[dict[str, Any]] = []
    changed_count = 0
    written_count = 0
    backup_paths: list[str] = []
    for path in files:
        original = path.read_text(encoding="utf-8")
        title = note_style.infer_title(original, path)
        if is_index_target(path.stem):
            report = note_style.index_style_report(original, title=title, path=str(path))
            report["changed"] = False
            report["would_write"] = False
            report["wrote"] = False
            report["backup"] = None
            reports.append(report)
            continue
        fixed, report = note_style.fix_note_style(original, title=title, path=str(path))
        changed = fixed != original
        report["changed"] = changed
        report["would_write"] = changed
        report["wrote"] = False
        report["backup"] = None
        if changed:
            changed_count += 1
        if apply and changed:
            backup_path = create_backup(path) if backup else None
            atomic_write_text(path, fixed)
            report["wrote"] = True
            report["backup"] = str(backup_path) if backup_path else None
            if backup_path:
                backup_paths.append(str(backup_path))
            written_count += 1
        reports.append(report)
    return {
        "schema": note_style.STYLE_FIX_SCHEMA,
        "wiki_dir": str(wiki_dir),
        "dry_run": not apply,
        "apply": apply,
        "backup": backup,
        "file_count": len(files),
        "changed_count": changed_count,
        "written_count": written_count,
        "error_count": sum(1 for item in reports if item["errors"]),
        "warning_count": sum(1 for item in reports if item["warnings"]),
        "backup_paths": backup_paths,
        "reports": reports,
    }


def _requires_style_rewrite(audit: dict[str, Any]) -> bool:
    return any(report.get("requires_llm_rewrite") for report in audit.get("reports", []))


def apply_style_rewrite(
    target_path: Path,
    content_path: Path,
    *,
    dry_run: bool = False,
    backup: bool = False,
) -> dict[str, Any]:
    if not target_path.exists():
        raise MissingPathError(f"Target note not found: {target_path}")
    if not content_path.exists():
        raise MissingPathError(f"Rewritten content file not found: {content_path}")
    original = target_path.read_text(encoding="utf-8")
    rewritten = content_path.read_text(encoding="utf-8")
    title = note_style.infer_title(rewritten, target_path)
    original_title = note_style.infer_title(original, target_path)
    if original_title != target_path.stem and title != original_title:
        raise ValidationError(f"Rewritten note title changed from {original_title!r} to {title!r}")
    report = note_style.validate_note_style(rewritten, title=title, path=str(target_path))
    result: dict[str, Any] = {
        "target_path": str(target_path),
        "content_path": str(content_path),
        "title": title,
        "dry_run": dry_run,
        "backup": backup,
        "backup_path": None,
        "changed": rewritten != original,
        "written": False,
        "validation": report,
    }
    if report["errors"]:
        return result
    if not dry_run and rewritten != original:
        backup_path = create_backup(target_path) if backup else None
        atomic_write_text(target_path, rewritten)
        result["written"] = True
        result["backup_path"] = str(backup_path) if backup_path else None
    return result
