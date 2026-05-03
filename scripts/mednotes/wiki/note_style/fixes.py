"""Deterministic style fixes for Wiki_Medicina notes."""
from __future__ import annotations

import re
from typing import Any

from wiki.note_style.frontmatter import chat_original_url, normalize_wiki_frontmatter, split_frontmatter
from wiki.note_style.models import WIKI_INDEX_LINK
from wiki.note_style.tables import escape_wikilink_alias_pipes_in_tables, normalize_markdown_tables
from wiki.note_style.validate import validate_note_style


_CHAT_ORIGINAL_ANY_RE = re.compile(r"\[Chat Original\]\(([^)\s]+)\)")
_HEADING_EMOJI_RE = re.compile(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/Users/|/home/|/var/|/tmp/)")
_MALFORMED_ALIAS_RE = re.compile(r"\[\[([^\]\|]+)\]\]([A-ZÁÉÍÓÚÇ]{2,12})\b")
_CALLOUT_START_RE = re.compile(r"^>\s*\[![A-Za-z]+]")

_HEADING_EMOJI_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"quando\s+(pensar|suspeitar|usar)", re.I), "🎯"),
    (re.compile(r"(ideia\s+central|fisiopatologia|mecanismo|etiologia|anatomia|fisiologia)", re.I), "🧠"),
    (re.compile(r"(diagn[oó]stico|exames?|achados?|avalia[cç][aã]o)", re.I), "🔎"),
    (re.compile(r"(conduta|tratamento|manejo|terap[eê]utica)", re.I), "🩺"),
    (re.compile(r"(estratifica[cç][aã]o|classifica[cç][aã]o|risco|escore|componentes)", re.I), "⚖️"),
    (re.compile(r"(pegadinhas?|armadilhas?|pontos?\s+de\s+prova)", re.I), "⚠️"),
    (re.compile(r"fechamento", re.I), "🏁"),
    (re.compile(r"notas?\s+relacionadas?", re.I), "🔗"),
)


def fix_note_style(
    content: str,
    *,
    title: str,
    raw_meta: dict[str, str] | None = None,
    path: str | None = None,
) -> tuple[str, dict[str, Any]]:
    fixed = content.replace("\r\n", "\n").replace("\r", "\n")
    fixes: list[str] = []

    stripped_lines = [line.rstrip() for line in fixed.split("\n")]
    stripped = "\n".join(stripped_lines)
    if stripped != fixed:
        fixed = stripped
        fixes.append("trim_trailing_whitespace")

    frontmatter_fixed, frontmatter_fixes = normalize_wiki_frontmatter(fixed, title=title)
    if frontmatter_fixed != fixed:
        fixed = frontmatter_fixed
        fixes.extend(frontmatter_fixes or ["normalize_frontmatter"])

    heading_fixed = _fix_heading_emojis(fixed)
    if heading_fixed != fixed:
        fixed = heading_fixed
        fixes.append("add_known_heading_emojis")

    alias_fixed = _fix_malformed_alias_links(fixed)
    if alias_fixed != fixed:
        fixed = alias_fixed
        fixes.append("fix_wikilink_alias_suffixes")

    table_link_fixed = escape_wikilink_alias_pipes_in_tables(fixed)
    if table_link_fixed != fixed:
        fixed = table_link_fixed
        fixes.append("escape_wikilink_pipes_in_tables")

    table_fixed = normalize_markdown_tables(fixed)
    if table_fixed != fixed:
        fixed = table_fixed
        fixes.append("normalize_markdown_tables")

    spacing_fixed = _normalize_blank_lines(fixed)
    if spacing_fixed != fixed:
        fixed = spacing_fixed
        fixes.append("normalize_blank_lines")

    footer_fixed = _fix_footer(fixed, raw_meta or {})
    if footer_fixed != fixed:
        fixed = footer_fixed
        fixes.append("normalize_footer")

    if not fixed.endswith("\n"):
        fixed += "\n"
        fixes.append("ensure_trailing_newline")

    report = validate_note_style(
        fixed,
        title=title,
        raw_meta=raw_meta,
        path=path,
        fixes_applied=fixes,
    )
    return fixed, report


def _fix_heading_emojis(text: str) -> str:
    fixed_lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(##)\s+(.+?)\s*$", line)
        if not match:
            fixed_lines.append(line)
            continue
        heading = match.group(2).strip()
        if _HEADING_EMOJI_RE.match(heading):
            fixed_lines.append(line)
            continue
        emoji = _emoji_for_heading(heading)
        fixed_lines.append(f"## {emoji} {heading}" if emoji else line)
    return "\n".join(fixed_lines)


def _emoji_for_heading(heading: str) -> str:
    for pattern, emoji in _HEADING_EMOJI_RULES:
        if pattern.search(heading):
            return emoji
    return ""


def _fix_malformed_alias_links(text: str) -> str:
    return _MALFORMED_ALIAS_RE.sub(r"[[\1|\2]]", text)


def _normalize_blank_lines(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\n+(## 🔗 Notas Relacionadas)", r"\n\n\1", text)
    text = _normalize_callout_spacing(text)
    return text


def _normalize_callout_spacing(text: str) -> str:
    normalized: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        is_callout_start = bool(_CALLOUT_START_RE.match(stripped))
        is_quote = stripped.startswith(">")
        previous_is_quote = bool(normalized and normalized[-1].lstrip().startswith(">"))
        if is_callout_start and normalized and normalized[-1].strip():
            normalized.append("")
        elif stripped and not is_quote and previous_is_quote:
            normalized.append("")
        normalized.append(line)
    return "\n".join(normalized)


def _fix_footer(text: str, raw_meta: dict[str, str]) -> str:
    expected_url = chat_original_url(raw_meta)
    existing = _CHAT_ORIGINAL_ANY_RE.search(text)
    source_url = expected_url or (existing.group(1) if existing and existing.group(1).startswith("https://gemini.google.com/app/") else "")
    if not source_url:
        return text

    frontmatter, body = split_frontmatter(text)
    body_lines = body.rstrip().splitlines()
    body_lines = _remove_trailing_footerish_lines(body_lines)
    new_body = "\n".join(body_lines).rstrip()
    new_body += f"\n\n---\n[Chat Original]({source_url})\n{WIKI_INDEX_LINK}\n"
    if frontmatter is None:
        return new_body
    return f"---\n{frontmatter}---\n{new_body}"


def _remove_trailing_footerish_lines(lines: list[str]) -> list[str]:
    result = list(lines)
    while result and not result[-1].strip():
        result.pop()
    changed = True
    while changed and result:
        changed = False
        tail_start = max(0, len(result) - 8)
        for idx in range(len(result) - 1, tail_start - 1, -1):
            stripped = result[idx].strip()
            footerish = (
                stripped == "---"
                or stripped == WIKI_INDEX_LINK
                or "_Índice_Medicina" in stripped
                or "Indice_Medicina" in stripped
                or stripped.startswith("[Chat Original]")
                or stripped.startswith("obsidian://")
                or bool(_LOCAL_PATH_RE.search(stripped))
            )
            if footerish:
                result.pop(idx)
                changed = True
        while result and not result[-1].strip():
            result.pop()
    return result
