#!/usr/bin/env python3
"""Semantic linker for Wiki_Medicina notes.

The original workflow depended on a curated `CATALOGO_WIKI.json`. This linker
uses that catalog as the primary vocabulary source, falls back to note titles and
YAML aliases when the catalog is unavailable, and can emit an auditable dry-run
plan before mutating notes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_MEDNOTES_DIR = _SCRIPT_DIR.parent
if str(_MEDNOTES_DIR) not in sys.path:
    sys.path.insert(0, str(_MEDNOTES_DIR))

from wiki import graph as wiki_graph  # noqa: E402
from wiki.link_terms import (  # noqa: E402
    catalog_entries as _catalog_entries,
    expand_path,
    extract_aliases,
    is_index_target,
    normalize_key,
    target_from_entry as _target_from_entry,
    terms_from_entry as _terms_from_entry,
)


DEFAULT_WIKI_DIR = r"C:\Users\leona\iCloudDrive\iCloud~md~obsidian\Wiki_Medicina"
DEFAULT_CATALOG_PATH = "~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json"
DEFAULT_INDEX_FILENAME = "_Índice_Medicina.md"
INDEX_START_MARKER = "<!-- mednotes:index:start -->"
INDEX_END_MARKER = "<!-- mednotes:index:end -->"
INDEX_HEADING = "# Índice Medicina"

STOPWORDS = {
    "diagnóstico",
    "diagnostico",
    "tratamento",
    "manejo",
    "clínica",
    "clinica",
    "fisiopatologia",
    "epidemiologia",
    "paciente",
    "doença",
    "doenca",
    "síndrome",
    "sindrome",
    "aguda",
    "agudo",
    "crônica",
    "cronica",
    "sinais",
    "sintomas",
    "tipos",
    "fases",
    "conceitos",
    "decisão",
    "decisao",
    "avaliação",
    "avaliacão",
    "quadro",
    "prevenção",
    "prevencao",
    "complicações",
    "complicacoes",
    "geral",
    "indicação",
    "indicacao",
    "exames",
    "exame",
    "laboratório",
    "imagem",
    "clínico",
    "terapia",
    "terapêutica",
    "terapeutica",
    "medicamento",
    "cirurgia",
    "resumo",
    "foco",
}


@dataclass(frozen=True)
class LinkTerm:
    term: str
    target: str
    source: str
    priority: int = 0
    canonical: str = ""

    @property
    def normalized(self) -> str:
        return normalize_key(self.term)


@dataclass
class Insertion:
    term: str
    matched_text: str
    target: str
    replacement: str
    start: int
    end: int
    source: str


@dataclass
class LinkRewrite:
    raw: str
    old_target: str
    new_target: str
    display_text: str
    replacement: str
    start: int
    end: int
    source: str


@dataclass
class LinkPlan:
    file: str
    insertions: list[Insertion] = field(default_factory=list)
    rewrites: list[LinkRewrite] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    index_updated: bool = False
    index_entries: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.insertions) or bool(self.rewrites) or self.index_updated

    def as_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "changed": self.changed,
            "insertions": [item.__dict__ for item in self.insertions],
            "rewrites": [item.__dict__ for item in self.rewrites],
            "skipped": self.skipped,
            "index_updated": self.index_updated,
            "index_entries": self.index_entries,
        }


def _is_good_term(term: str) -> bool:
    normalized = normalize_key(term)
    if not normalized or normalized in STOPWORDS:
        return False
    if len(term) < 4 and not term.isupper():
        return False
    return True


def load_catalog_terms(catalog_path: Path) -> list[LinkTerm]:
    """Load terms from flexible CATALOGO_WIKI.json shapes."""
    if not catalog_path.exists():
        return []
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    terms: list[LinkTerm] = []
    for fallback_key, entry in _catalog_entries(data):
        target = _target_from_entry(entry, fallback_key=fallback_key)
        if not target:
            continue
        priority_raw = entry.get("priority", entry.get("prioridade", 100))
        try:
            priority = int(priority_raw)
        except (TypeError, ValueError):
            priority = 100
        for term in _terms_from_entry(entry, target):
            if _is_good_term(term):
                terms.append(LinkTerm(term=term, target=target, source="catalog", priority=priority, canonical=target))
    return terms


def load_dynamic_terms(wiki_dir: Path) -> list[LinkTerm]:
    """Build fallback vocabulary from note filenames and YAML aliases."""
    terms: list[LinkTerm] = []
    for filepath in wiki_dir.rglob("*.md"):
        if filepath.name.startswith("_"):
            continue
        target = filepath.stem
        if _is_good_term(target):
            terms.append(LinkTerm(term=target, target=target, source="dynamic", priority=500, canonical=target))
        try:
            content = filepath.read_text(encoding="utf-8")[:4000]
        except OSError:
            continue
        for alias in extract_aliases(content):
            if _is_good_term(alias):
                terms.append(LinkTerm(term=alias, target=target, source="dynamic", priority=500, canonical=target))
    return terms


def build_vocabulary(wiki_dir: Path, catalog_path: Path | None = None) -> list[LinkTerm]:
    """Build linker vocabulary with catalog as primary source and YAML as fallback."""
    terms: list[LinkTerm] = []
    if catalog_path:
        terms.extend(load_catalog_terms(catalog_path))
    terms.extend(load_dynamic_terms(wiki_dir))

    by_key: dict[tuple[str, str], LinkTerm] = {}
    for term in terms:
        key = (term.normalized, normalize_key(term.target))
        previous = by_key.get(key)
        if previous is None or (term.source == "catalog" and previous.source != "catalog"):
            by_key[key] = term

    return sorted(
        by_key.values(),
        key=lambda item: (item.priority, -len(item.normalized), 0 if item.source == "catalog" else 1),
    )


def _split_frontmatter(content: str) -> tuple[str, str]:
    parts = re.split(r"^---\s*$", content, maxsplit=2, flags=re.MULTILINE)
    if len(parts) >= 3:
        return f"---{parts[1]}---\n", parts[2]
    return "", content


def _find_index_file(wiki_dir: Path) -> Path | None:
    for path in sorted(wiki_dir.rglob("*.md")):
        if path.is_file() and is_index_target(path.stem):
            return path
    return None


def _files_to_link(wiki_dir: Path) -> list[Path]:
    files = sorted(path for path in wiki_dir.rglob("*.md") if path.is_file())
    index_path = _find_index_file(wiki_dir) or (wiki_dir / DEFAULT_INDEX_FILENAME)
    if not any(path == index_path for path in files):
        files.append(index_path)
    return sorted(files, key=lambda path: path.as_posix())


def _index_note_paths(wiki_dir: Path, index_path: Path) -> list[Path]:
    paths: list[Path] = []
    for path in wiki_dir.rglob("*.md"):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path == index_path or is_index_target(path.stem):
            continue
        paths.append(path)
    return sorted(paths, key=lambda path: tuple(normalize_key(part) for part in path.relative_to(wiki_dir).parts))


def _render_index_block(wiki_dir: Path, index_path: Path) -> tuple[str, int]:
    note_paths = _index_note_paths(wiki_dir, index_path)
    lines = [
        INDEX_START_MARKER,
        "## 🔗 Notas Indexadas",
        "",
        f"Total: {len(note_paths)} notas.",
        "",
    ]
    current_dirs: tuple[str, ...] = ()
    for path in note_paths:
        rel = path.relative_to(wiki_dir)
        dirs = rel.parent.parts
        common = 0
        for left, right in zip(current_dirs, dirs):
            if left != right:
                break
            common += 1
        for depth, dirname in enumerate(dirs[common:], start=common):
            lines.append(f"{'  ' * depth}- {dirname}")
        lines.append(f"{'  ' * len(dirs)}- [[{path.stem}]]")
        current_dirs = dirs
    if not note_paths:
        lines.append("- Nenhuma nota médica encontrada.")
    lines.extend(["", INDEX_END_MARKER, ""])
    return "\n".join(lines), len(note_paths)


def plan_index_file(filepath: Path, wiki_dir: Path) -> tuple[str, LinkPlan]:
    content = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
    yaml_part, _body = _split_frontmatter(content)
    block, entry_count = _render_index_block(wiki_dir, filepath)
    new_content = f"{yaml_part}{INDEX_HEADING}\n\nMapa automático das notas publicadas em `Wiki_Medicina`.\n\n{block}"
    plan = LinkPlan(file=str(filepath), index_entries=entry_count, index_updated=new_content != content)
    return new_content, plan


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in (
        r"```.*?```",
        r"`[^`\n]+`",
        r"https?://\S+",
        r"!\[[^\]]*\]\([^)]+\)",
        r"\[[^\]]+\]\([^)]+\)",
        r"\[\[.*?\]\]",
    ):
        spans.extend((m.start(), m.end()) for m in re.finditer(pattern, text, re.DOTALL))
    spans.extend(_section_spans(text, "Notas Relacionadas"))
    return sorted(spans)


def _section_spans(text: str, heading_text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pattern = re.compile(rf"(?m)^##\s+(?:🔗\s+)?{re.escape(heading_text)}\s*$")
    next_h2 = re.compile(r"(?m)^##\s+")
    for match in pattern.finditer(text):
        next_match = next_h2.search(text, match.end())
        spans.append((match.start(), next_match.start() if next_match else len(text)))
    return spans


def _inside_spans(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _line_prefix(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start)
    return text[line_start + 1 : start] if line_start != -1 else text[:start]


def _is_heading_match(text: str, start: int) -> bool:
    return _line_prefix(text, start).lstrip().startswith("#")


def _line_bounds(text: str, start: int) -> tuple[int, int]:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end == -1:
        line_end = len(text)
    return line_start, line_end


def _is_table_match(text: str, start: int) -> bool:
    line_start, line_end = _line_bounds(text, start)
    line = text[line_start:line_end]
    return "|" in line and not line.lstrip().startswith(">")


def _term_pattern(term: str) -> re.Pattern[str]:
    left = r"(?<![\wÀ-ÖØ-öø-ÿ])"
    right = r"(?![\wÀ-ÖØ-öø-ÿ])"
    return re.compile(left + f"({re.escape(term)})" + right, re.IGNORECASE)


def _replacement(target: str, matched_text: str, *, in_table: bool) -> str:
    if normalize_key(matched_text) == normalize_key(target):
        return f"[[{target}]]"
    separator = r"\|" if in_table else "|"
    return f"[[{target}{separator}{matched_text}]]"


_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")


def _wikilink_target(raw: str) -> str:
    return Path(raw.split("|", 1)[0].split("#", 1)[0].strip()).stem


def _wikilink_display(raw: str) -> str:
    if "|" in raw:
        return raw.rsplit("|", 1)[1].strip()
    return _wikilink_target(raw)


def _catalog_rewrite_targets(vocabulary: list[LinkTerm]) -> dict[str, LinkTerm]:
    by_term: dict[str, list[LinkTerm]] = {}
    for term in vocabulary:
        if term.source != "catalog":
            continue
        by_term.setdefault(term.normalized, []).append(term)

    mapping: dict[str, LinkTerm] = {}
    for normalized, terms in by_term.items():
        target_keys = {normalize_key(term.target) for term in terms}
        if len(target_keys) == 1:
            mapping[normalized] = terms[0]
    return mapping


def _rewrite_existing_links(body: str, vocabulary: list[LinkTerm], current_stem: str) -> tuple[str, list[LinkRewrite]]:
    rewrite_targets = _catalog_rewrite_targets(vocabulary)
    rewrites: list[LinkRewrite] = []

    def replace(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        if "#" in raw:
            return match.group(0)
        old_target = _wikilink_target(raw)
        if not old_target or is_index_target(old_target):
            return match.group(0)
        term = rewrite_targets.get(normalize_key(old_target))
        if term is None:
            return match.group(0)
        new_target = term.target.replace(".md", "")
        if normalize_key(new_target) in {normalize_key(old_target), normalize_key(current_stem)}:
            return match.group(0)

        display_text = _wikilink_display(raw)
        replacement = _replacement(new_target, display_text, in_table=_is_table_match(body, match.start()))
        rewrites.append(
            LinkRewrite(
                raw=raw,
                old_target=old_target,
                new_target=new_target,
                display_text=display_text,
                replacement=replacement,
                start=match.start(),
                end=match.end(),
                source=term.source,
            )
        )
        return replacement

    return _WIKILINK_RE.sub(replace, body), rewrites


def plan_file(
    filepath: Path,
    vocabulary: list[LinkTerm],
    max_links: int = 20,
    wiki_dir: Path | None = None,
) -> tuple[str, LinkPlan]:
    if is_index_target(filepath.stem):
        return plan_index_file(filepath, wiki_dir or filepath.parent)

    content = filepath.read_text(encoding="utf-8")
    yaml_part, body = _split_frontmatter(content)
    plan = LinkPlan(file=str(filepath))
    body, plan.rewrites = _rewrite_existing_links(body, vocabulary, filepath.stem)
    protected = _protected_spans(body)
    used_targets: set[str] = set()
    used_ranges: list[tuple[int, int]] = []

    for term in vocabulary:
        if len(plan.insertions) >= max_links:
            plan.skipped.append({"reason": "max_links_reached", "term": term.term})
            break
        target = term.target.replace(".md", "")
        if normalize_key(target) == normalize_key(filepath.stem):
            plan.skipped.append({"reason": "self_link", "term": term.term})
            continue
        if target in used_targets:
            plan.skipped.append({"reason": "target_already_linked", "term": term.term})
            continue

        pattern = _term_pattern(term.term)
        for match in pattern.finditer(body):
            start, end = match.start(), match.end()
            if _inside_spans(start, end, protected) or _inside_spans(start, end, used_ranges):
                plan.skipped.append({"reason": "protected_span", "term": term.term})
                continue
            if _is_heading_match(body, start):
                plan.skipped.append({"reason": "heading", "term": term.term})
                continue

            matched_text = match.group(1)
            replacement = _replacement(target, matched_text, in_table=_is_table_match(body, start))
            plan.insertions.append(
                Insertion(
                    term=term.term,
                    matched_text=matched_text,
                    target=target,
                    replacement=replacement,
                    start=start,
                    end=end,
                    source=term.source,
                )
            )
            used_targets.add(target)
            used_ranges.append((start, end))
            break

    linked_body = apply_insertions(body, plan.insertions)
    return yaml_part + linked_body, plan


def apply_insertions(body: str, insertions: list[Insertion]) -> str:
    updated = body
    for item in sorted(insertions, key=lambda insertion: insertion.start, reverse=True):
        updated = updated[: item.start] + item.replacement + updated[item.end :]
    return updated


def link_file(
    filepath: Path,
    vocabulary: list[LinkTerm],
    max_links: int = 20,
    dry_run: bool = False,
    wiki_dir: Path | None = None,
) -> LinkPlan:
    new_content, plan = plan_file(filepath, vocabulary, max_links=max_links, wiki_dir=wiki_dir)
    if plan.changed and not dry_run:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(new_content, encoding="utf-8")
    return plan


def run(
    wiki_dir: Path,
    target: Path | None = None,
    catalog_path: Path | None = None,
    verify: bool = True,
    dry_run: bool = False,
    audit: bool = False,
    json_output: bool = False,
    max_links: int = 20,
) -> int:
    if not json_output:
        print("Iniciando Med-Auto-Linker (Catalog High Precision)...")
    if not wiki_dir.exists():
        message = f"Wiki dir não encontrado: {wiki_dir}"
        if json_output:
            print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))
        else:
            print(message, file=sys.stderr)
        return 4

    before_audit = wiki_graph.audit_wiki_graph(wiki_dir, catalog_path=catalog_path)
    if audit:
        if json_output:
            print(json.dumps(before_audit, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(before_audit, ensure_ascii=False, indent=2))
        return 0 if before_audit.get("ok") else 3

    vocabulary = build_vocabulary(wiki_dir, catalog_path=catalog_path)
    source_counts = {
        "catalog": sum(1 for term in vocabulary if term.source == "catalog"),
        "dynamic": sum(1 for term in vocabulary if term.source == "dynamic"),
    }
    if not json_output:
        print(f"Vocabulário construído: {len(vocabulary)} termos ({source_counts}).")
        if catalog_path and not catalog_path.exists():
            print(f"Aviso: catálogo não encontrado, usando fallback dinâmico: {catalog_path}")

    if target and target.is_file():
        files = [target]
    elif target and is_index_target(target.stem):
        files = [target]
    else:
        files = _files_to_link(wiki_dir)

    blockers = list(before_audit.get("errors", []))
    blocked = bool(blockers) and not dry_run
    plan_only = dry_run or blocked
    plans: list[LinkPlan] = []
    for path in files:
        is_index_file = is_index_target(path.stem)
        plans.append(
            link_file(
                path,
                vocabulary,
                max_links=max_links,
                dry_run=plan_only and not (blocked and is_index_file),
                wiki_dir=wiki_dir,
            )
        )
    changed = [plan for plan in plans if plan.changed]
    if blocked:
        # Graph blockers should prevent semantic link mutations, but the
        # generated index is deterministic and must stay fresh after publishes.
        changed = [plan for plan in plans if plan.index_updated]
    summary = {
        "ok": not blockers,
        "blocked": blocked,
        "dry_run": dry_run,
        "wiki_dir": str(wiki_dir),
        "catalog_path": str(catalog_path) if catalog_path else None,
        "catalog_exists": bool(catalog_path and catalog_path.exists()),
        "vocabulary_count": len(vocabulary),
        "source_counts": source_counts,
        "files_scanned": len(files),
        "files_changed": len(changed),
        "links_planned": sum(len(plan.insertions) for plan in plans),
        "links_rewritten": sum(len(plan.rewrites) for plan in plans),
        "index_files_changed": sum(1 for plan in changed if plan.index_updated),
        "index_entries_planned": sum(plan.index_entries for plan in plans),
        "index_refreshed_while_blocked": bool(blocked and any(plan.index_updated for plan in changed)),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "graph_audit_before": before_audit,
        "plans": [plan.as_dict() for plan in plans if plan.changed or plan.skipped],
    }

    if blocked:
        summary["links_planned"] = sum(len(plan.insertions) for plan in plans)
        summary["links_rewritten"] = sum(len(plan.rewrites) for plan in plans)
    elif not dry_run:
        summary["graph_audit_after"] = wiki_graph.audit_wiki_graph(wiki_dir, catalog_path=catalog_path)

    if json_output:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for plan in changed:
            print(
                f"{'Planejado' if dry_run else 'Linkado'}: {Path(plan.file).name} "
                f"({len(plan.insertions)} links, {len(plan.rewrites)} reescritas)"
            )
        print(f"Fim. {len(changed)} notas {'seriam interconectadas' if dry_run else 'foram interconectadas'}.")

    if verify and not dry_run:
        _run_optional_verify()
    return 3 if blocked else 0


def _run_optional_verify() -> None:
    print("\nExecutando validação de integridade do grafo...")
    try:
        from verify_links import clean_dangling_links  # type: ignore

        clean_dangling_links()
    except ImportError:
        verify_path = Path(os.getenv("MED_VERIFY_LINKS_PATH", r"C:\Users\leona\verify_links.py"))
        if verify_path.exists():
            subprocess.run([sys.executable, str(verify_path)], check=False)
        else:
            print("verify_links não encontrado; validação externa ignorada.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="High-precision semantic linker for Wiki_Medicina.")
    parser.add_argument("target", nargs="?", help="Optional single note path to link.")
    parser.add_argument("--wiki-dir", default=os.getenv("MED_WIKI_DIR", DEFAULT_WIKI_DIR))
    parser.add_argument("--catalog", "--catalog-path", default=os.getenv("MED_CATALOG_PATH", DEFAULT_CATALOG_PATH))
    parser.add_argument("--dry-run", action="store_true", help="Plan links without writing files.")
    parser.add_argument("--audit", action="store_true", help="Audit graph health without planning or writing links.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON report.")
    parser.add_argument("--max-links", type=int, default=20, help="Maximum inserted links per note.")
    parser.add_argument("--no-verify", action="store_true", help="Skip optional dangling-link verification.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = expand_path(args.target) if args.target else None
    catalog_path = expand_path(args.catalog) if args.catalog else None
    return run(
        expand_path(args.wiki_dir),
        target=target,
        catalog_path=catalog_path,
        verify=not args.no_verify,
        dry_run=args.dry_run,
        audit=args.audit,
        json_output=args.json,
        max_links=args.max_links,
    )


if __name__ == "__main__":
    raise SystemExit(main())
