"""Deterministic style contract for Wiki_Medicina notes."""
from __future__ import annotations

from wiki.note_style.fixes import fix_note_style
from wiki.note_style.frontmatter import (
    chat_original_url,
    infer_title,
    parse_frontmatter,
    raw_meta_from_file,
    split_frontmatter,
)
from wiki.note_style.models import (
    PREFERRED_H2_EMOJIS,
    REQUIRED_SECTION_LINES,
    REWRITE_REQUIRED_CODES,
    STYLE_AUDIT_SCHEMA,
    STYLE_FIX_SCHEMA,
    STYLE_REPORT_SCHEMA,
    StyleIssue,
    WIKI_INDEX_LINK,
)
from wiki.note_style.prompts import rewrite_prompt
from wiki.note_style.tables import check_tables, escape_wikilink_alias_pipes_in_tables, normalize_markdown_tables
from wiki.note_style.validate import index_style_report, validate_note_style, validate_wiki_dir


__all__ = [
    "PREFERRED_H2_EMOJIS",
    "REQUIRED_SECTION_LINES",
    "REWRITE_REQUIRED_CODES",
    "STYLE_AUDIT_SCHEMA",
    "STYLE_FIX_SCHEMA",
    "STYLE_REPORT_SCHEMA",
    "StyleIssue",
    "WIKI_INDEX_LINK",
    "chat_original_url",
    "check_tables",
    "escape_wikilink_alias_pipes_in_tables",
    "fix_note_style",
    "infer_title",
    "index_style_report",
    "normalize_markdown_tables",
    "parse_frontmatter",
    "raw_meta_from_file",
    "rewrite_prompt",
    "split_frontmatter",
    "validate_note_style",
    "validate_wiki_dir",
]
