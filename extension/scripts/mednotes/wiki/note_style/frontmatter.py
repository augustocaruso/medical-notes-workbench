"""Frontmatter and provenance helpers for Wiki_Medicina notes."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # Keep med_ops usable even in very small extension runtimes.
    import yaml
except ImportError:  # pragma: no cover - exercised only without project deps
    yaml = None  # type: ignore[assignment]


_FRONTMATTER_DELIM = "---"
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")

_ALIAS_KEYS = {
    "alias",
    "aliases",
    "sinonimo",
    "sinonimos",
    "sinônimo",
    "sinônimos",
    "sigla",
    "siglas",
    "acronym",
    "acronyms",
    "termo",
    "termos",
    "term",
    "terms",
}
_TAG_KEYS = {"tag", "tags"}
_ENRICHER_KEYS = {
    "images_enriched",
    "images_enriched_at",
    "image_count",
    "image_sources",
}


@dataclass(frozen=True)
class FrontmatterBlock:
    key: str
    lines: tuple[str, ...]


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


def normalize_wiki_frontmatter(text: str, *, title: str | None = None) -> tuple[str, list[str]]:
    """Return text with the canonical Wiki_Medicina frontmatter shape.

    Canonical Wiki notes use frontmatter only for exact aliases, Obsidian tags,
    and additive metadata owned by downstream workflows. The enricher owns the
    image metadata keys, so those blocks are preserved verbatim.
    """

    frontmatter, body = split_frontmatter(text)
    if frontmatter is None:
        return text, []

    blocks = _frontmatter_blocks(frontmatter)
    aliases = _canonical_aliases(_extract_aliases(frontmatter), title=title)
    tags = _canonical_tags(_extract_tags(frontmatter))
    preserved = [block for block in blocks if _normalize_key(block.key) in _ENRICHER_KEYS]
    canonical = _format_canonical_frontmatter(aliases, tags, preserved)
    normalized_body = body.lstrip("\n")
    normalized = normalized_body if not canonical else f"{_FRONTMATTER_DELIM}\n{canonical}{_FRONTMATTER_DELIM}\n{normalized_body}"
    if normalized == text:
        return text, []
    fixes: list[str] = []
    if aliases:
        fixes.append("normalize_frontmatter_aliases")
    if tags:
        fixes.append("normalize_frontmatter_tags")
    if preserved:
        fixes.append("preserve_enricher_frontmatter")
    removed_keys = _removed_frontmatter_keys(blocks)
    if removed_keys:
        fixes.append("remove_noncanonical_frontmatter_keys")
    if not canonical:
        fixes.append("remove_empty_frontmatter")
    return normalized, fixes


def wiki_frontmatter_aliases(text: str) -> list[str]:
    frontmatter, _body = split_frontmatter(text)
    if frontmatter is None:
        return []
    return _canonical_aliases(_extract_aliases(frontmatter), title=None)


def _frontmatter_blocks(frontmatter: str) -> list[FrontmatterBlock]:
    lines = frontmatter.splitlines(keepends=True)
    blocks: list[FrontmatterBlock] = []
    idx = 0
    while idx < len(lines):
        match = _top_level_key_match(lines[idx])
        if not match:
            idx += 1
            continue
        start = idx
        idx += 1
        while idx < len(lines) and not _top_level_key_match(lines[idx]):
            idx += 1
        blocks.append(FrontmatterBlock(match.group(1), tuple(lines[start:idx])))
    return blocks


def _load_frontmatter_map(frontmatter: str) -> dict[str, Any]:
    if yaml is not None:
        try:
            loaded = yaml.safe_load(frontmatter) or {}
        except Exception:
            loaded = None
        if isinstance(loaded, dict):
            return {str(key): value for key, value in loaded.items()}

    parsed: dict[str, Any] = {}
    for block in _frontmatter_blocks(frontmatter):
        key, raw = _parse_block_header(block)
        if raw.startswith("[") and raw.endswith("]"):
            parsed[key] = [_strip_quotes(item) for item in raw[1:-1].split(",") if item.strip()]
        elif raw:
            parsed[key] = _strip_quotes(raw)
        else:
            values = []
            for line in block.lines[1:]:
                match = re.match(r"^\s*-\s*(.+?)\s*$", line)
                if match:
                    values.append(_strip_quotes(match.group(1)))
            parsed[key] = values
    return parsed


def _extract_aliases(frontmatter: str) -> list[str]:
    data = _load_frontmatter_map(frontmatter)
    aliases: list[str] = []
    for key, value in data.items():
        if _normalize_key(key) in _ALIAS_KEYS:
            aliases.extend(_coerce_string_list(value))
    return aliases


def _extract_tags(frontmatter: str) -> list[str]:
    data = _load_frontmatter_map(frontmatter)
    tags: list[str] = []
    for key, value in data.items():
        if _normalize_key(key) in _TAG_KEYS:
            tags.extend(_coerce_string_list(value))
    return tags


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _canonical_aliases(values: list[str], *, title: str | None) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    title_key = _normalize_alias(title or "") if title else ""
    for value in values:
        alias = re.sub(r"\s+", " ", _strip_quotes(str(value))).strip()
        if not alias:
            continue
        key = _normalize_alias(alias)
        if not key or key == title_key or key in seen:
            continue
        seen.add(key)
        aliases.append(alias)
    return aliases


def _canonical_tags(values: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = re.sub(r"\s+", " ", _strip_quotes(str(value)).lstrip("#")).strip()
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tags


def _format_canonical_frontmatter(aliases: list[str], tags: list[str], preserved: list[FrontmatterBlock]) -> str:
    lines: list[str] = []
    if aliases:
        lines.append("aliases:\n")
        lines.extend(f"  - {_format_yaml_string(alias)}\n" for alias in aliases)
    if tags:
        lines.append("tags:\n")
        lines.extend(f"  - {_format_yaml_tag(tag)}\n" for tag in tags)
    for block in preserved:
        lines.extend(_ensure_block_newlines(block.lines))
    return "".join(lines)


def _format_yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _format_yaml_tag(value: str) -> str:
    if re.match(r"^[A-Za-z0-9_/-]+$", value):
        return value
    return _format_yaml_string(value)


def _ensure_block_newlines(lines: tuple[str, ...]) -> list[str]:
    fixed: list[str] = []
    for line in lines:
        fixed.append(line if line.endswith("\n") else f"{line}\n")
    return fixed


def _removed_frontmatter_keys(blocks: list[FrontmatterBlock]) -> list[str]:
    removed: list[str] = []
    for block in blocks:
        key = _normalize_key(block.key)
        if key not in _ALIAS_KEYS and key not in _TAG_KEYS and key not in _ENRICHER_KEYS:
            removed.append(block.key)
    return removed


def _parse_block_header(block: FrontmatterBlock) -> tuple[str, str]:
    first = block.lines[0].strip()
    match = _KEY_RE.match(first)
    if not match:
        return block.key, ""
    return match.group(1), match.group(2).strip()


def _top_level_key_match(line: str) -> re.Match[str] | None:
    return _KEY_RE.match(line.rstrip("\r\n"))


def _normalize_key(value: str) -> str:
    return value.strip().lower()


def _normalize_alias(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
