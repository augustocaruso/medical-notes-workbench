#!/usr/bin/env python3
"""Deterministic style contract for Wiki_Medicina notes.

This module validates and fixes Markdown form only. It never invents clinical
content; when content is missing, it emits a rewrite prompt for the LLM layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STYLE_REPORT_SCHEMA = "medical-notes-workbench.wiki-note-style-report.v1"
STYLE_AUDIT_SCHEMA = "medical-notes-workbench.wiki-note-style-audit.v1"
STYLE_FIX_SCHEMA = "medical-notes-workbench.wiki-note-style-fix.v1"
WIKI_INDEX_LINK = "[[_Índice_Medicina]]"

_FRONTMATTER_DELIM = "---"
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
_CHAT_ORIGINAL_RE = re.compile(r"^\[Chat Original\]\(https://gemini\.google\.com/app/[^)\s]+\)$")
_CHAT_ORIGINAL_ANY_RE = re.compile(r"\[Chat Original\]\(([^)\s]+)\)")
_HEADING_EMOJI_RE = re.compile(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/Users/|/home/|/var/|/tmp/)")
_MALFORMED_ALIAS_RE = re.compile(r"\[\[([^\]\|]+)\]\]([A-ZÁÉÍÓÚÇ]{2,12})\b")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_CALLOUT_START_RE = re.compile(r"^>\s*\[![A-Za-z]+]")

PREFERRED_H2_EMOJIS = {"🎯", "🧠", "🔎", "🩺", "⚖️", "⚠️", "🏁", "🔗", "🧬"}

REQUIRED_SECTION_LINES = (
    "## 🏁 Fechamento",
    "### Resumo",
    "### Key Points",
    "### Frase de Prova",
    "## 🔗 Notas Relacionadas",
)

REWRITE_REQUIRED_CODES = {
    "missing_title_heading",
    "missing_h2_sections",
    "missing_required_section",
}

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


@dataclass(frozen=True)
class StyleIssue:
    code: str
    message: str
    severity: str
    line: int | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.line is not None:
            data["line"] = self.line
        return data


def split_frontmatter(text: str) -> tuple[str | None, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return None, text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_DELIM:
            return "".join(lines[1:idx]), "".join(lines[idx + 1 :])
    return None, text


def parse_frontmatter(text: str) -> dict[str, str]:
    frontmatter, _body = split_frontmatter(text)
    if frontmatter is None:
        return {}
    parsed: dict[str, str] = {}
    for line in frontmatter.splitlines():
        match = _KEY_RE.match(line.strip())
        if match:
            parsed[match.group(1)] = _strip_quotes(match.group(2))
    return parsed


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def raw_meta_from_file(raw_file: Path | None) -> dict[str, str]:
    if raw_file is None:
        return {}
    return parse_frontmatter(raw_file.read_text(encoding="utf-8"))


def chat_original_url(raw_meta: dict[str, str] | None) -> str:
    if not raw_meta:
        return ""
    fonte_id = raw_meta.get("fonte_id", "").strip().strip("/")
    if not fonte_id:
        return ""
    if re.match(r"^https?://", fonte_id):
        return fonte_id
    return f"https://gemini.google.com/app/{fonte_id}"


def validate_note_style(
    content: str,
    *,
    title: str,
    raw_meta: dict[str, str] | None = None,
    path: str | None = None,
    fixes_applied: list[str] | None = None,
) -> dict[str, Any]:
    frontmatter, body = split_frontmatter(content)
    errors: list[StyleIssue] = []
    warnings: list[StyleIssue] = []

    _check_title_and_definition(body, title, errors, warnings)
    _check_headings(body, errors, warnings)
    _check_required_sections(body, errors)
    _check_footer(body, raw_meta or {}, errors)
    _check_tables(body, errors)
    _check_style_warnings(body, warnings)

    error_payload = [issue.to_json() for issue in errors]
    warning_payload = [issue.to_json() for issue in warnings]
    requires_llm_rewrite = any(issue.code in REWRITE_REQUIRED_CODES for issue in errors)
    report = {
        "schema": STYLE_REPORT_SCHEMA,
        "path": path,
        "title": title,
        "ok": not errors,
        "errors": error_payload,
        "warnings": warning_payload,
        "fixes_applied": fixes_applied or [],
        "requires_llm_rewrite": requires_llm_rewrite,
        "rewrite_prompt": _rewrite_prompt(title, error_payload, warning_payload) if requires_llm_rewrite else None,
        "frontmatter_present": frontmatter is not None,
    }
    return report


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

    heading_fixed = _fix_heading_emojis(fixed)
    if heading_fixed != fixed:
        fixed = heading_fixed
        fixes.append("add_known_heading_emojis")

    alias_fixed = _fix_malformed_alias_links(fixed)
    if alias_fixed != fixed:
        fixed = alias_fixed
        fixes.append("fix_wikilink_alias_suffixes")

    table_link_fixed = _escape_wikilink_alias_pipes_in_tables(fixed)
    if table_link_fixed != fixed:
        fixed = table_link_fixed
        fixes.append("escape_wikilink_pipes_in_tables")

    table_fixed = _normalize_markdown_tables(fixed)
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


def validate_wiki_dir(wiki_dir: Path) -> dict[str, Any]:
    files = sorted(path for path in wiki_dir.rglob("*.md") if path.is_file())
    reports = []
    for path in files:
        content = path.read_text(encoding="utf-8")
        title = _infer_title(content, path)
        reports.append(validate_note_style(content, title=title, path=str(path)))
    return {
        "schema": STYLE_AUDIT_SCHEMA,
        "wiki_dir": str(wiki_dir),
        "file_count": len(files),
        "ok_count": sum(1 for item in reports if item["ok"]),
        "error_count": sum(1 for item in reports if item["errors"]),
        "warning_count": sum(1 for item in reports if item["warnings"]),
        "reports": reports,
    }


def infer_title(content: str, path: Path) -> str:
    return _infer_title(content, path)


def _check_title_and_definition(
    body: str,
    title: str,
    errors: list[StyleIssue],
    warnings: list[StyleIssue],
) -> None:
    title_pattern = re.compile(rf"(?m)^#\s+{re.escape(title)}\s*$")
    title_match = title_pattern.search(body)
    if not title_match:
        errors.append(StyleIssue("missing_title_heading", f"use a level-1 heading exactly as '# {title}'", "error"))
        return

    after_title = body[title_match.end() :]
    before_first_h2 = re.split(r"(?m)^##\s+", after_title, maxsplit=1)[0]
    definition_lines = [
        line.strip()
        for line in before_first_h2.splitlines()
        if line.strip() and not line.lstrip().startswith((">", "-", "|"))
    ]
    if not definition_lines:
        warnings.append(StyleIssue("missing_definition", "add a short 2-4 line definition after the title", "warning"))
    elif len(definition_lines) > 4:
        warnings.append(StyleIssue("long_definition", "keep the opening definition to 2-4 lines", "warning"))


def _check_headings(body: str, errors: list[StyleIssue], warnings: list[StyleIssue]) -> None:
    h2_matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", body))
    if not h2_matches:
        errors.append(StyleIssue("missing_h2_sections", "include level-2 sections with emoji-prefixed headings", "error"))
        return

    for match in h2_matches:
        heading = match.group(1).strip()
        line = body.count("\n", 0, match.start()) + 1
        if not _HEADING_EMOJI_RE.match(heading):
            errors.append(
                StyleIssue(
                    "h2_missing_emoji",
                    f"prefix this level-2 heading with a semantic emoji: ## {heading}",
                    "error",
                    line=line,
                )
            )
            continue
        emoji = heading.split(maxsplit=1)[0]
        if emoji not in PREFERRED_H2_EMOJIS:
            warnings.append(
                StyleIssue(
                    "non_preferred_h2_emoji",
                    f"prefer the fixed semantic emoji set for this heading: ## {heading}",
                    "warning",
                    line=line,
                )
            )


def _check_required_sections(body: str, errors: list[StyleIssue]) -> None:
    for line in REQUIRED_SECTION_LINES:
        if not re.search(rf"(?m)^{re.escape(line)}\s*$", body):
            errors.append(StyleIssue("missing_required_section", f"include the required section line '{line}'", "error"))


def _check_footer(body: str, raw_meta: dict[str, str], errors: list[StyleIssue]) -> None:
    nonempty_lines = [line.strip() for line in body.splitlines() if line.strip()]
    tail = nonempty_lines[-6:]
    if any(line.startswith("obsidian://") or _LOCAL_PATH_RE.search(line) for line in tail):
        errors.append(
            StyleIssue(
                "invalid_footer_link",
                "do not use obsidian deeplinks or local absolute paths in the final footer",
                "error",
            )
        )

    if len(nonempty_lines) < 3 or nonempty_lines[-3] != "---" or nonempty_lines[-1] != WIKI_INDEX_LINK:
        errors.append(
            StyleIssue(
                "invalid_footer",
                f"end the note with exactly '---', Chat Original, and {WIKI_INDEX_LINK}",
                "error",
            )
        )
        return

    expected_url = chat_original_url(raw_meta)
    if expected_url:
        expected_chat = f"[Chat Original]({expected_url})"
        if nonempty_lines[-2] != expected_chat:
            errors.append(
                StyleIssue("invalid_chat_original", f"use the exact final provenance link '{expected_chat}'", "error")
            )
    elif not _CHAT_ORIGINAL_RE.match(nonempty_lines[-2]):
        errors.append(
            StyleIssue(
                "invalid_chat_original",
                "include '[Chat Original](https://gemini.google.com/app/<fonte_id>)' before the index link",
                "error",
            )
        )


def _check_style_warnings(body: str, warnings: list[StyleIssue]) -> None:
    if re.search(r"\n{3,}## 🔗 Notas Relacionadas", body):
        warnings.append(
            StyleIssue(
                "extra_blank_lines_before_related",
                "use a single blank line before '## 🔗 Notas Relacionadas'",
                "warning",
            )
        )

    callout_count = len(re.findall(r"(?m)^>\s*\[!", body))
    if callout_count > 2:
        warnings.append(
            StyleIssue("excessive_callouts", "use callouts rarely; keep only the strongest 1-2 per note", "warning")
        )

    lines = body.splitlines()
    for idx, line in enumerate(lines):
        if not _CALLOUT_START_RE.match(line.strip()):
            continue
        previous = lines[idx - 1].strip() if idx > 0 else ""
        if previous:
            warnings.append(
                StyleIssue(
                    "missing_blank_line_before_callout",
                    "add one blank line before standalone callouts",
                    "warning",
                    line=idx + 1,
                )
            )

    for match in _MALFORMED_ALIAS_RE.finditer(body):
        line = body.count("\n", 0, match.start()) + 1
        warnings.append(
            StyleIssue(
                "malformed_wikilink_alias",
                f"use '[[{match.group(1)}|{match.group(2)}]]' instead of '[[{match.group(1)}]]{match.group(2)}'",
                "warning",
                line=line,
            )
        )

    for paragraph, start_line in _paragraphs(body):
        if len(paragraph) > 650:
            warnings.append(
                StyleIssue(
                    "long_paragraph",
                    "split long paragraphs into shorter 2-4 line review blocks",
                    "warning",
                    line=start_line,
                )
            )


def _paragraphs(body: str) -> list[tuple[str, int]]:
    paragraphs: list[tuple[str, int]] = []
    current: list[str] = []
    start_line = 1
    in_code = False
    for idx, line in enumerate(body.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        skip = (
            in_code
            or not stripped
            or stripped.startswith(("#", "-", ">", "|", "1.", "2.", "3.", "4.", "5.", "---"))
        )
        if skip:
            if current:
                paragraphs.append((" ".join(current), start_line))
                current = []
            continue
        if not current:
            start_line = idx
        current.append(stripped)
    if current:
        paragraphs.append((" ".join(current), start_line))
    return paragraphs


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


def _check_tables(body: str, errors: list[StyleIssue]) -> None:
    for block_lines, start_line in _iter_table_blocks(body.splitlines()):
        if len(block_lines) < 2:
            continue
        protected_lines = [_escape_wikilink_alias_pipes_in_table_line(line) for line in block_lines]
        parsed = [_split_table_cells(line) for line in protected_lines]
        separator_index = _first_separator_index(parsed)
        if separator_index is None:
            errors.append(
                StyleIssue(
                    "malformed_markdown_table",
                    "markdown table is missing a separator row",
                    "error",
                    line=start_line,
                )
            )
            continue

        if any(_table_line_has_unescaped_wikilink_pipe(line) for line in block_lines):
            errors.append(
                StyleIssue(
                    "unescaped_wikilink_pipe_in_table",
                    "escape Obsidian wikilink alias pipes inside markdown tables",
                    "error",
                    line=start_line,
                )
            )

        expected_columns = len(_trim_trailing_empty_cells(parsed[0]))
        if expected_columns == 0:
            errors.append(
                StyleIssue("malformed_markdown_table", "markdown table header has no columns", "error", line=start_line)
            )
            continue

        for offset, cells in enumerate(parsed):
            if offset == separator_index:
                if len(cells) != expected_columns:
                    errors.append(
                        StyleIssue(
                            "malformed_markdown_table",
                            "markdown table separator column count does not match the header",
                            "error",
                            line=start_line + offset,
                        )
                    )
                continue
            if len(_trim_trailing_empty_cells(cells)) != expected_columns:
                errors.append(
                    StyleIssue(
                        "malformed_markdown_table",
                        "markdown table row column count does not match the header",
                        "error",
                        line=start_line + offset,
                    )
                )


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


def _escape_wikilink_alias_pipes_in_tables(text: str) -> str:
    fixed_lines: list[str] = []
    for line in text.splitlines():
        if _is_table_line(line):
            fixed_lines.append(_escape_wikilink_alias_pipes_in_table_line(line))
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)


def _escape_wikilink_alias_pipes_in_table_line(line: str) -> str:
    def replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "|" not in inner:
            return match.group(0)
        inner = re.sub(r"\s*(?<!\\)\|\s*", r"\\|", inner)
        inner = re.sub(r"\s*\\\|\s*", r"\\|", inner)
        return f"[[{inner}]]"

    return _WIKILINK_RE.sub(replace, line)


def _table_line_has_unescaped_wikilink_pipe(line: str) -> bool:
    for match in _WIKILINK_RE.finditer(line):
        if re.search(r"(?<!\\)\|", match.group(1)):
            return True
    return False


def _normalize_markdown_tables(text: str) -> str:
    lines = text.splitlines()
    normalized: list[str] = []
    cursor = 0
    for block_lines, start_line in _iter_table_blocks(lines):
        start_index = start_line - 1
        normalized.extend(lines[cursor:start_index])
        normalized.extend(_normalize_table_block(block_lines))
        cursor = start_index + len(block_lines)
    normalized.extend(lines[cursor:])
    return "\n".join(normalized)


def _iter_table_blocks(lines: list[str]) -> list[tuple[list[str], int]]:
    blocks: list[tuple[list[str], int]] = []
    idx = 0
    while idx < len(lines):
        if not _is_table_line(lines[idx]):
            idx += 1
            continue
        start = idx
        block: list[str] = []
        while idx < len(lines) and _is_table_line(lines[idx]):
            block.append(lines[idx])
            idx += 1
        if len(block) >= 2:
            blocks.append((block, start + 1))
    return blocks


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _normalize_table_block(lines: list[str]) -> list[str]:
    parsed = [_split_table_cells(line) for line in lines]
    separator_index = _first_separator_index(parsed)
    if separator_index is None:
        return lines

    expected_columns = len(_trim_trailing_empty_cells(parsed[0]))
    if expected_columns == 0:
        return lines

    normalized_rows: list[list[str]] = []
    for idx, cells in enumerate(parsed):
        if idx == separator_index:
            row = cells[:expected_columns]
            row.extend(["---"] * (expected_columns - len(row)))
        else:
            row = _trim_trailing_empty_cells(cells)
            if len(row) > expected_columns:
                return lines
            row.extend([""] * (expected_columns - len(row)))
        normalized_rows.append([cell.strip() for cell in row])

    widths = [3] * expected_columns
    for row in normalized_rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    rendered: list[str] = []
    for idx, row in enumerate(normalized_rows):
        if idx == separator_index:
            rendered.append(_render_separator_row(row, widths))
        else:
            rendered.append(_render_table_row(row, widths))
    return rendered


def _split_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]

    cells: list[str] = []
    current: list[str] = []
    for idx, char in enumerate(stripped):
        if char == "|" and (idx == 0 or stripped[idx - 1] != "\\"):
            cells.append("".join(current))
            current = []
        else:
            current.append(char)
    cells.append("".join(current))
    return cells


def _first_separator_index(rows: list[list[str]]) -> int | None:
    for idx, cells in enumerate(rows[:3]):
        if _is_separator_row(cells):
            return idx
    return None


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _trim_trailing_empty_cells(cells: list[str]) -> list[str]:
    trimmed = list(cells)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def _render_table_row(cells: list[str], widths: list[int]) -> str:
    return "| " + " | ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(cells)) + " |"


def _render_separator_row(cells: list[str], widths: list[int]) -> str:
    tokens = [_separator_token(cell, widths[idx]) for idx, cell in enumerate(cells)]
    return "| " + " | ".join(tokens) + " |"


def _separator_token(cell: str, width: int) -> str:
    stripped = cell.strip()
    left = stripped.startswith(":")
    right = stripped.endswith(":")
    dash_count = max(3, width - int(left) - int(right))
    token = "-" * dash_count
    if left:
        token = ":" + token
    if right:
        token = token + ":"
    return token.ljust(width)


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


def _infer_title(content: str, path: Path) -> str:
    _frontmatter, body = split_frontmatter(content)
    match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
    return match.group(1).strip() if match else path.stem


def _rewrite_prompt(title: str, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> str:
    issue_lines = "\n".join(f"- {item['code']}: {item['message']}" for item in errors + warnings)
    return (
        "Reescreva a nota temporária abaixo para cumprir o Modelo Wiki_Medicina "
        "de estudo para residência, sem inventar fatos novos além do material-fonte. "
        f"Preserve o título '# {title}', use headings ## com emoji semântico, inclua "
        "'## 🏁 Fechamento' com '### Resumo', '### Key Points' e "
        "'### Frase de Prova', inclua '## 🔗 Notas Relacionadas' e finalize com "
        f"'---', '[Chat Original](https://gemini.google.com/app/<fonte_id>)' e '{WIKI_INDEX_LINK}'. "
        "Problemas encontrados:\n"
        f"{issue_lines}"
    )
