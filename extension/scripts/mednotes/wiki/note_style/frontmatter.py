"""Frontmatter and provenance helpers for Wiki_Medicina notes."""
from __future__ import annotations

import re
from pathlib import Path


_FRONTMATTER_DELIM = "---"
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")


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


def infer_title(content: str, path: Path) -> str:
    _frontmatter, body = split_frontmatter(content)
    match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
    return match.group(1).strip() if match else path.stem
