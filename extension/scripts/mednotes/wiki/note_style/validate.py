"""Validation entrypoints for the Wiki_Medicina note style contract."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from wiki.note_style.frontmatter import chat_original_url, infer_title, split_frontmatter
from wiki.note_style.models import (
    PREFERRED_H2_EMOJIS,
    REQUIRED_SECTION_LINES,
    REWRITE_REQUIRED_CODES,
    STYLE_AUDIT_SCHEMA,
    STYLE_REPORT_SCHEMA,
    StyleIssue,
    WIKI_INDEX_LINK,
)
from wiki.note_style.prompts import rewrite_prompt
from wiki.note_style.tables import check_tables
from wiki.link_terms import is_index_target


_CHAT_ORIGINAL_RE = re.compile(r"^\[Chat Original\]\(https://gemini\.google\.com/app/[^)\s]+\)$")
_HEADING_EMOJI_RE = re.compile(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/Users/|/home/|/var/|/tmp/)")
_MALFORMED_ALIAS_RE = re.compile(r"\[\[([^\]\|]+)\]\]([A-ZÁÉÍÓÚÇ]{2,12})\b")
_CALLOUT_START_RE = re.compile(r"^>\s*\[![A-Za-z]+]")


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
    check_tables(body, errors)
    _check_style_warnings(body, warnings)

    error_payload = [issue.to_json() for issue in errors]
    warning_payload = [issue.to_json() for issue in warnings]
    requires_llm_rewrite = any(issue.code in REWRITE_REQUIRED_CODES for issue in errors)
    return {
        "schema": STYLE_REPORT_SCHEMA,
        "path": path,
        "title": title,
        "ok": not errors,
        "errors": error_payload,
        "warnings": warning_payload,
        "fixes_applied": fixes_applied or [],
        "requires_llm_rewrite": requires_llm_rewrite,
        "rewrite_prompt": rewrite_prompt(title, error_payload, warning_payload) if requires_llm_rewrite else None,
        "frontmatter_present": frontmatter is not None,
    }


def validate_wiki_dir(wiki_dir: Path) -> dict[str, Any]:
    files = sorted(path for path in wiki_dir.rglob("*.md") if path.is_file())
    reports = []
    for path in files:
        content = path.read_text(encoding="utf-8")
        title = infer_title(content, path)
        if is_index_target(path.stem):
            reports.append(index_style_report(content, title=title, path=str(path)))
            continue
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


def index_style_report(
    content: str,
    *,
    title: str,
    path: str | None = None,
    fixes_applied: list[str] | None = None,
) -> dict[str, Any]:
    frontmatter, _body = split_frontmatter(content)
    return {
        "schema": STYLE_REPORT_SCHEMA,
        "path": path,
        "title": title,
        "ok": True,
        "errors": [],
        "warnings": [],
        "fixes_applied": fixes_applied or [],
        "requires_llm_rewrite": False,
        "rewrite_prompt": None,
        "frontmatter_present": frontmatter is not None,
        "skipped": True,
        "skip_reason": "wiki_index",
    }


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
