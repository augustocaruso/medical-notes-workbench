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
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_WIKI_DIR = r"C:\Users\leona\iCloudDrive\iCloud~md~obsidian\Wiki_Medicina"
DEFAULT_CATALOG_PATH = "~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json"

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
class LinkPlan:
    file: str
    insertions: list[Insertion] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.insertions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "changed": self.changed,
            "insertions": [item.__dict__ for item in self.insertions],
            "skipped": self.skipped,
        }


def normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().casefold()


def expand_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


def extract_aliases(content: str) -> list[str]:
    """Extract aliases from YAML frontmatter."""
    aliases: list[str] = []
    match = re.search(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL | re.MULTILINE)
    if not match:
        return aliases

    yaml_block = match.group(1)
    list_match = re.search(r"aliases:\s*\[(.*?)\]", yaml_block, re.IGNORECASE)
    if list_match:
        items = list_match.group(1).split(",")
        aliases.extend(_clean_yaml_scalar(item) for item in items if item.strip())

    multi_line_match = re.search(r"aliases:\s*\n((?:\s*-\s*.*(?:\n|$))+)", yaml_block, re.IGNORECASE)
    if multi_line_match:
        lines = multi_line_match.group(1).strip().split("\n")
        for line in lines:
            item = re.sub(r"^\s*-\s*", "", line).strip()
            if item:
                aliases.append(_clean_yaml_scalar(item))

    return [alias for alias in aliases if alias]


def _clean_yaml_scalar(value: str) -> str:
    return value.strip().strip("'\"").strip()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_values(value: Any) -> list[str]:
    out: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _is_good_term(term: str) -> bool:
    normalized = normalize_key(term)
    if not normalized or normalized in STOPWORDS:
        return False
    if len(term) < 4 and not term.isupper():
        return False
    return True


def _target_from_entry(entry: dict[str, Any], fallback_key: str = "") -> str | None:
    for key in ("target", "target_file", "arquivo", "file", "filename", "nota", "note", "path", "caminho"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return Path(value.strip()).stem
    if fallback_key:
        return Path(fallback_key).stem
    title = entry.get("titulo") or entry.get("title") or entry.get("nome") or entry.get("name")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return None


def _terms_from_entry(entry: dict[str, Any], target: str) -> list[str]:
    terms: list[str] = [target]
    for key in (
        "aliases",
        "alias",
        "sinonimos",
        "sinônimos",
        "synonyms",
        "siglas",
        "acronyms",
        "termos",
        "terms",
    ):
        terms.extend(_string_values(entry.get(key)))
    for key in ("titulo", "title", "nome", "name"):
        terms.extend(_string_values(entry.get(key)))
    return terms


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
    return sorted(spans)


def _inside_spans(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _line_prefix(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start)
    return text[line_start + 1 : start] if line_start != -1 else text[:start]


def _is_heading_match(text: str, start: int) -> bool:
    return _line_prefix(text, start).lstrip().startswith("#")


def _term_pattern(term: str) -> re.Pattern[str]:
    left = r"(?<![\wÀ-ÖØ-öø-ÿ])"
    right = r"(?![\wÀ-ÖØ-öø-ÿ])"
    return re.compile(left + f"({re.escape(term)})" + right, re.IGNORECASE)


def plan_file(filepath: Path, vocabulary: list[LinkTerm], max_links: int = 20) -> tuple[str, LinkPlan]:
    content = filepath.read_text(encoding="utf-8")
    yaml_part, body = _split_frontmatter(content)
    plan = LinkPlan(file=str(filepath))
    protected = _protected_spans(body)
    used_targets: set[str] = set()
    used_ranges: list[tuple[int, int]] = []

    if "_Índice_Medicina" in str(filepath):
        plan.skipped.append({"reason": "index_file", "term": filepath.name})
        return content, plan

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
            replacement = f"[[{target}|{matched_text}]]" if normalize_key(matched_text) != normalize_key(target) else f"[[{target}]]"
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


def link_file(filepath: Path, vocabulary: list[LinkTerm], max_links: int = 20, dry_run: bool = False) -> LinkPlan:
    new_content, plan = plan_file(filepath, vocabulary, max_links=max_links)
    if plan.changed and not dry_run:
        filepath.write_text(new_content, encoding="utf-8")
    return plan


def run(
    wiki_dir: Path,
    target: Path | None = None,
    catalog_path: Path | None = None,
    verify: bool = True,
    dry_run: bool = False,
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
    else:
        files = sorted(path for path in wiki_dir.rglob("*.md") if path.is_file())

    plans = [link_file(path, vocabulary, max_links=max_links, dry_run=dry_run) for path in files]
    changed = [plan for plan in plans if plan.changed]
    summary = {
        "ok": True,
        "dry_run": dry_run,
        "wiki_dir": str(wiki_dir),
        "catalog_path": str(catalog_path) if catalog_path else None,
        "catalog_exists": bool(catalog_path and catalog_path.exists()),
        "vocabulary_count": len(vocabulary),
        "source_counts": source_counts,
        "files_scanned": len(files),
        "files_changed": len(changed),
        "links_planned": sum(len(plan.insertions) for plan in plans),
        "plans": [plan.as_dict() for plan in plans if plan.changed or plan.skipped],
    }

    if json_output:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for plan in changed:
            print(f"{'Planejado' if dry_run else 'Linkado'}: {Path(plan.file).name} ({len(plan.insertions)} links)")
        print(f"Fim. {len(changed)} notas {'seriam interconectadas' if dry_run else 'foram interconectadas'}.")

    if verify and not dry_run:
        _run_optional_verify()
    return 0


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
        json_output=args.json,
        max_links=args.max_links,
    )


if __name__ == "__main__":
    raise SystemExit(main())
