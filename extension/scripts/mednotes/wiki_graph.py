#!/usr/bin/env python3
"""Deterministic graph audit for Wiki_Medicina notes.

This module checks objective Obsidian graph health. It does not judge clinical
semantic quality; LLM agents still choose strong related notes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GRAPH_AUDIT_SCHEMA = "medical-notes-workbench.wiki-graph-audit.v1"
DEFAULT_WIKI_DIR = r"C:\Users\leona\iCloudDrive\iCloud~md~obsidian\Wiki_Medicina"
DEFAULT_CATALOG_PATH = "~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json"
RELATED_HEADING = "## 🔗 Notas Relacionadas"
NO_STRONG_LINKS_MARKER = "Sem conexões fortes no catálogo atual."
INDEX_TARGETS = {"_indice_medicina", "_índice_medicina"}

GENERIC_ALIASES = {
    "diagnóstico",
    "diagnostico",
    "tratamento",
    "manejo",
    "clínica",
    "clinica",
    "paciente",
    "doença",
    "doenca",
    "síndrome",
    "sindrome",
    "sinais",
    "sintomas",
    "exame",
    "exames",
    "terapia",
    "medicamento",
}

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL | re.MULTILINE)
_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")
_RELATED_RE = re.compile(r"(?m)^##\s+(?:🔗\s+)?Notas Relacionadas\s*$")
_NEXT_H2_RE = re.compile(r"(?m)^##\s+")


@dataclass(frozen=True)
class NoteRecord:
    path: Path
    relative_path: str
    stem: str
    aliases: tuple[str, ...]


def normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().casefold()


def expand_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


def _clean_yaml_scalar(value: str) -> str:
    return value.strip().strip("'\"").strip()


def extract_aliases(content: str) -> list[str]:
    aliases: list[str] = []
    match = _FRONTMATTER_RE.search(content)
    if not match:
        return aliases
    yaml_block = match.group(1)

    list_match = re.search(r"aliases:\s*\[(.*?)\]", yaml_block, re.IGNORECASE)
    if list_match:
        aliases.extend(_clean_yaml_scalar(item) for item in list_match.group(1).split(",") if item.strip())

    multi_line_match = re.search(r"aliases:\s*\n((?:\s*-\s*.*(?:\n|$))+)", yaml_block, re.IGNORECASE)
    if multi_line_match:
        for line in multi_line_match.group(1).strip().split("\n"):
            item = re.sub(r"^\s*-\s*", "", line).strip()
            if item:
                aliases.append(_clean_yaml_scalar(item))
    return [alias for alias in aliases if alias]


def _note_files(wiki_dir: Path) -> list[Path]:
    return sorted(path for path in wiki_dir.rglob("*.md") if path.is_file() and not path.name.startswith("."))


def _load_notes(wiki_dir: Path) -> list[NoteRecord]:
    notes: list[NoteRecord] = []
    for path in _note_files(wiki_dir):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        notes.append(
            NoteRecord(
                path=path,
                relative_path=path.relative_to(wiki_dir).as_posix(),
                stem=path.stem,
                aliases=tuple(extract_aliases(content)),
            )
        )
    return notes


def _obsidian_target(raw: str) -> str:
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    return Path(target).stem if target else ""


def _line_number(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


def _related_section_span(text: str) -> tuple[int, int] | None:
    match = _RELATED_RE.search(text)
    if not match:
        return None
    next_match = _NEXT_H2_RE.search(text, match.end())
    return (match.start(), next_match.start() if next_match else len(text))


def _wikilinks(text: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    related_span = _related_section_span(text)
    for match in _WIKILINK_RE.finditer(text):
        raw = match.group(1).strip()
        target = _obsidian_target(raw)
        if not target:
            continue
        links.append(
            {
                "raw": raw,
                "target": target,
                "line": _line_number(text, match.start()),
                "in_related": bool(related_span and related_span[0] <= match.start() < related_span[1]),
            }
        )
    return links


def _issue(code: str, message: str, severity: str, **extra: Any) -> dict[str, Any]:
    data = {"code": code, "message": message, "severity": severity}
    data.update({key: value for key, value in extra.items() if value is not None})
    return data


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_values(value: Any) -> list[str]:
    return [item.strip() for item in _as_list(value) if isinstance(item, str) and item.strip()]


def _catalog_entries(data: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(data, list):
        return [("", item) for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("entities", "entidades", "notes", "notas", "items", "catalog", "catalogo"):
        value = data.get(key)
        if isinstance(value, list):
            return [("", item) for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [(str(k), item) for k, item in value.items() if isinstance(item, dict)]
    return [(str(key), value) for key, value in data.items() if isinstance(value, dict)]


def _entry_target(entry: dict[str, Any], fallback_key: str) -> str | None:
    for key in ("target", "target_file", "arquivo", "file", "filename", "nota", "note", "path", "caminho"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return Path(value.strip()).stem
    if fallback_key:
        return Path(fallback_key).stem
    for key in ("titulo", "title", "nome", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _entry_aliases(entry: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in ("aliases", "alias", "sinonimos", "sinônimos", "synonyms", "siglas", "acronyms", "termos", "terms"):
        aliases.extend(_string_values(entry.get(key)))
    return aliases


def _audit_catalog(catalog_path: Path | None, notes_by_stem: dict[str, list[NoteRecord]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    issues: list[dict[str, Any]] = []
    stats = {"catalog_entries": 0, "catalog_aliases": 0}
    if not catalog_path:
        return issues, stats
    if not catalog_path.exists():
        issues.append(_issue("catalog_missing", f"catalog not found: {catalog_path}", "warning", catalog_path=str(catalog_path)))
        return issues, stats

    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(_issue("catalog_invalid_json", f"invalid catalog JSON: {exc}", "error", catalog_path=str(catalog_path)))
        return issues, stats

    alias_targets: dict[str, set[str]] = {}
    for fallback_key, entry in _catalog_entries(data):
        stats["catalog_entries"] += 1
        target = _entry_target(entry, fallback_key)
        if not target:
            issues.append(_issue("catalog_entry_missing_target", "catalog entry has no target", "error"))
            continue
        matches = notes_by_stem.get(normalize_key(target), [])
        if not matches:
            issues.append(_issue("catalog_target_missing", f"catalog target does not exist: {target}", "error", target=target))
        elif len(matches) > 1:
            issues.append(_issue("catalog_target_ambiguous", f"catalog target is ambiguous: {target}", "error", target=target))
        for alias in _entry_aliases(entry):
            stats["catalog_aliases"] += 1
            alias_key = normalize_key(alias)
            if alias_key in GENERIC_ALIASES:
                issues.append(_issue("generic_alias", f"catalog alias is too generic: {alias}", "warning", alias=alias, target=target))
            if len(alias.strip()) < 4 and not alias.strip().isupper():
                issues.append(_issue("short_alias", f"catalog alias is too short: {alias}", "warning", alias=alias, target=target))
            alias_targets.setdefault(alias_key, set()).add(normalize_key(target))

    for alias_key, targets in sorted(alias_targets.items()):
        if len(targets) > 1:
            issues.append(
                _issue(
                    "alias_conflict",
                    f"alias points to multiple targets: {alias_key}",
                    "error",
                    alias=alias_key,
                    targets=sorted(targets),
                )
            )
    return issues, stats


def audit_wiki_graph(wiki_dir: Path, catalog_path: Path | None = None) -> dict[str, Any]:
    if not wiki_dir.exists():
        return {"schema": GRAPH_AUDIT_SCHEMA, "ok": False, "error": f"Wiki dir not found: {wiki_dir}"}
    notes = _load_notes(wiki_dir)
    notes_by_stem: dict[str, list[NoteRecord]] = {}
    for note in notes:
        notes_by_stem.setdefault(normalize_key(note.stem), []).append(note)

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    inbound: dict[str, int] = {note.relative_path: 0 for note in notes}
    outbound: dict[str, int] = {note.relative_path: 0 for note in notes}

    for stem_key, matches in notes_by_stem.items():
        if len(matches) > 1:
            errors.append(
                _issue(
                    "duplicate_stem",
                    f"multiple notes share the same Obsidian target name: {matches[0].stem}",
                    "error",
                    target=stem_key,
                    files=[item.relative_path for item in matches],
                )
            )

    catalog_issues, catalog_stats = _audit_catalog(catalog_path, notes_by_stem)
    for item in catalog_issues:
        (errors if item["severity"] == "error" else warnings).append(item)

    for note in notes:
        content = note.path.read_text(encoding="utf-8")
        related_span = _related_section_span(content)
        related_links: list[dict[str, Any]] = []
        has_no_strong_marker = bool(related_span and NO_STRONG_LINKS_MARKER in content[related_span[0] : related_span[1]])
        if related_span is None:
            warnings.append(_issue("missing_related_section", "missing ## 🔗 Notas Relacionadas section", "warning", file=note.relative_path))

        for link in _wikilinks(content):
            target = link["target"]
            target_key = normalize_key(target)
            if target_key in INDEX_TARGETS:
                continue
            matches = notes_by_stem.get(target_key, [])
            issue_payload = {"file": note.relative_path, "line": link["line"], "target": target, "raw": link["raw"]}
            if not matches:
                errors.append(_issue("dangling_link", f"wikilink target does not exist: {target}", "error", **issue_payload))
                continue
            if len(matches) > 1:
                errors.append(_issue("ambiguous_link", f"wikilink target is ambiguous: {target}", "error", **issue_payload))
                continue
            target_note = matches[0]
            if target_note.relative_path == note.relative_path:
                errors.append(_issue("self_link", f"note links to itself: {target}", "error", **issue_payload))
                continue
            outbound[note.relative_path] += 1
            inbound[target_note.relative_path] += 1
            if link["in_related"]:
                related_links.append(link)

        if related_span is not None and len(related_links) < 2 and not has_no_strong_marker:
            warnings.append(
                _issue(
                    "few_related_links",
                    "related notes section has fewer than 2 valid links",
                    "warning",
                    file=note.relative_path,
                    valid_related_links=len(related_links),
                )
            )
        if related_span is not None and has_no_strong_marker and related_links:
            warnings.append(
                _issue(
                    "related_marker_with_links",
                    "remove the no-strong-links marker when related links are present",
                    "warning",
                    file=note.relative_path,
                )
            )

    orphan_notes = [
        note.relative_path
        for note in notes
        if inbound[note.relative_path] == 0 and normalize_key(note.stem) not in INDEX_TARGETS
    ]
    for rel_path in orphan_notes:
        warnings.append(_issue("orphan_note", "note has no inbound wiki links", "warning", file=rel_path))

    metrics = {
        "note_count": len(notes),
        "wikilink_count": sum(outbound.values()),
        "orphan_count": len(orphan_notes),
        **catalog_stats,
    }
    return {
        "schema": GRAPH_AUDIT_SCHEMA,
        "ok": not errors,
        "wiki_dir": str(wiki_dir),
        "catalog_path": str(catalog_path) if catalog_path else None,
        "metrics": metrics,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "blocker_count": len(errors),
        "errors": errors,
        "warnings": warnings,
        "orphan_notes": orphan_notes,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Wiki_Medicina graph health.")
    parser.add_argument("--wiki-dir", default=os.getenv("MED_WIKI_DIR", DEFAULT_WIKI_DIR))
    parser.add_argument("--catalog", "--catalog-path", default=os.getenv("MED_CATALOG_PATH", DEFAULT_CATALOG_PATH))
    parser.add_argument("--json", action="store_true", help="Emit JSON report. Accepted for explicitness; output is always JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = audit_wiki_graph(expand_path(args.wiki_dir), catalog_path=expand_path(args.catalog) if args.catalog else None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
