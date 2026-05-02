"""Deterministic graph fixes for Wiki_Medicina notes."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from wiki import graph as wiki_graph
from wiki.graph import NO_STRONG_LINKS_MARKER
from wiki.link_terms import is_index_target
from wiki.raw_chats import atomic_write_text, create_backup


GRAPH_FIX_SCHEMA = "medical-notes-workbench.wiki-graph-fix.v1"
_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")


def fix_wiki_graph(
    wiki_dir: Path,
    *,
    catalog_path: Path | None = None,
    apply: bool = False,
    backup: bool = False,
) -> dict[str, Any]:
    audit = wiki_graph.audit_wiki_graph(wiki_dir, catalog_path=catalog_path)
    link_issues = [
        issue
        for issue in audit.get("errors", [])
        if issue.get("code") in {"dangling_link", "self_link", "ambiguous_link"} and issue.get("file")
    ]
    marker_warnings = [
        issue
        for issue in audit.get("warnings", [])
        if issue.get("code") == "related_marker_with_links" and issue.get("file")
    ]
    issues_by_file: dict[str, list[dict[str, Any]]] = {}
    for issue in [*link_issues, *marker_warnings]:
        issues_by_file.setdefault(str(issue["file"]), []).append(issue)

    reports: list[dict[str, Any]] = []
    changed_count = 0
    written_count = 0
    backup_paths: list[str] = []
    for relative_file, issues in sorted(issues_by_file.items()):
        path = wiki_dir / relative_file
        if not path.exists() or not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        fixed, fixes = _fix_note_graph_text(original, issues)
        changed = fixed != original
        report = {
            "path": str(path),
            "relative_path": relative_file,
            "changed": changed,
            "would_write": changed,
            "wrote": False,
            "backup": None,
            "fixes_applied": fixes,
            "issue_codes": sorted({str(issue.get("code", "")) for issue in issues if issue.get("code")}),
        }
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

    duplicate_report = _fix_exact_duplicate_stems(
        wiki_dir,
        audit.get("errors", []),
        apply=apply,
        backup=backup,
    )
    backup_paths.extend(duplicate_report["backup_paths"])

    return {
        "schema": GRAPH_FIX_SCHEMA,
        "wiki_dir": str(wiki_dir),
        "dry_run": not apply,
        "apply": apply,
        "backup": backup,
        "changed_count": changed_count,
        "written_count": written_count,
        "backup_paths": backup_paths,
        "reports": reports,
        "duplicates": duplicate_report,
        "unresolved_blocker_count": duplicate_report["merge_required_count"],
    }


def _fix_note_graph_text(text: str, issues: list[dict[str, Any]]) -> tuple[str, list[str]]:
    invalid_raw_links = {
        str(issue.get("raw", "")).strip()
        for issue in issues
        if issue.get("code") in {"dangling_link", "self_link", "ambiguous_link"} and issue.get("raw")
    }
    fixed = text
    fixes: list[str] = []
    if invalid_raw_links:
        without_link_lines = _remove_invalid_link_only_lines(fixed, invalid_raw_links)
        unlinked = _unlink_invalid_wikilinks(without_link_lines, invalid_raw_links)
        if unlinked != fixed:
            fixed = unlinked
            fixes.append("unlink_invalid_wikilinks")

    if any(issue.get("code") == "related_marker_with_links" for issue in issues):
        marker_fixed = _remove_no_strong_marker(fixed)
        if marker_fixed != fixed:
            fixed = marker_fixed
            fixes.append("remove_related_marker_with_links")

    marker_added = _add_marker_to_empty_related_sections(fixed)
    if marker_added != fixed:
        fixed = marker_added
        fixes.append("mark_empty_related_sections")

    fixed = re.sub(r"\n{3,}", "\n\n", fixed)
    if text.endswith("\n") and not fixed.endswith("\n"):
        fixed += "\n"
    return fixed, fixes


def _remove_invalid_link_only_lines(text: str, invalid_raw_links: set[str]) -> str:
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        should_drop = False
        for raw in invalid_raw_links:
            if re.fullmatch(rf"[-*]\s*\[\[{re.escape(raw)}\]\]\s*\.?", stripped):
                should_drop = True
                break
        if not should_drop:
            lines.append(line)
    return "".join(lines)


def _unlink_invalid_wikilinks(text: str, invalid_raw_links: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        if raw not in invalid_raw_links:
            return match.group(0)
        return _display_text(raw)

    return _WIKILINK_RE.sub(replace, text)


def _display_text(raw: str) -> str:
    if "|" in raw:
        return raw.rsplit("|", 1)[1].strip()
    target = raw.split("#", 1)[0].strip()
    return Path(target).stem if target else raw.strip()


def _remove_no_strong_marker(text: str) -> str:
    lines = [
        line
        for line in text.splitlines(keepends=True)
        if NO_STRONG_LINKS_MARKER not in line
    ]
    return "".join(lines)


def _add_marker_to_empty_related_sections(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        section = match.group(0)
        if NO_STRONG_LINKS_MARKER in section or _WIKILINK_RE.search(section):
            return section
        lines = section.rstrip().splitlines()
        if not lines:
            return section
        return "\n".join([lines[0], f"- {NO_STRONG_LINKS_MARKER}", *lines[1:]]) + "\n"

    return re.sub(r"(?ms)^##\s+🔗\s+Notas Relacionadas\s*$.*?(?=^##\s+|\Z)", replace, text)


def _fix_exact_duplicate_stems(
    wiki_dir: Path,
    errors: list[dict[str, Any]],
    *,
    apply: bool,
    backup: bool,
) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    backup_paths: list[str] = []
    removed_count = 0
    merge_required_count = 0

    for issue in errors:
        if issue.get("code") != "duplicate_stem":
            continue
        files = [str(item) for item in issue.get("files", []) if isinstance(item, str)]
        paths = [wiki_dir / file for file in files]
        existing = [path for path in paths if path.exists() and path.is_file()]
        if len(existing) < 2:
            continue
        existing = sorted(existing, key=lambda path: (len(path.relative_to(wiki_dir).parts), path.relative_to(wiki_dir).as_posix()))
        fingerprints = {_content_fingerprint(path) for path in existing}
        keep = existing[0]
        remove = existing[1:]
        if len(fingerprints) != 1:
            merge_required_count += 1
            reports.append(
                {
                    "target": issue.get("target"),
                    "files": [path.relative_to(wiki_dir).as_posix() for path in existing],
                    "action": "manual_merge_required",
                    "removed": [],
                }
            )
            continue
        removed: list[str] = []
        for path in remove:
            backup_path = create_backup(path) if backup and apply else None
            if apply:
                path.unlink()
            if backup_path:
                backup_paths.append(str(backup_path))
            removed.append(path.relative_to(wiki_dir).as_posix())
            removed_count += 1
        reports.append(
            {
                "target": issue.get("target"),
                "keep": keep.relative_to(wiki_dir).as_posix(),
                "action": "remove_exact_duplicates",
                "removed": removed,
            }
        )

    return {
        "removed_count": removed_count if apply else sum(len(item.get("removed", [])) for item in reports),
        "merge_required_count": merge_required_count,
        "backup_paths": backup_paths,
        "reports": reports,
    }


def _content_fingerprint(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if is_index_target(path.stem):
        return ""
    return re.sub(r"\s+", "\n", text).strip()
