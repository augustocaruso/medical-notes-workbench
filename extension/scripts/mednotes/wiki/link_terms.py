"""Shared term, alias, and catalog helpers for Wiki graph/linker code."""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL | re.MULTILINE)
CATALOG_CONTAINER_KEYS = ("entities", "entidades", "notes", "notas", "items", "catalog", "catalogo")
TARGET_KEYS = ("target", "target_file", "arquivo", "file", "filename", "nota", "note", "path", "caminho")
ALIAS_KEYS = ("aliases", "alias", "sinonimos", "sinônimos", "synonyms", "siglas", "acronyms", "termos", "terms")
TITLE_KEYS = ("titulo", "title", "nome", "name")
INDEX_TARGET_KEYS = {"_indice_medicina"}


def normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().casefold()


def is_index_target(value: str) -> bool:
    return normalize_key(Path(value).stem) in INDEX_TARGET_KEYS


def expand_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


def clean_yaml_scalar(value: str) -> str:
    return value.strip().strip("'\"").strip()


def extract_aliases(content: str) -> list[str]:
    aliases: list[str] = []
    match = FRONTMATTER_RE.search(content)
    if not match:
        return aliases
    yaml_block = match.group(1)

    list_match = re.search(r"aliases:\s*\[(.*?)\]", yaml_block, re.IGNORECASE)
    if list_match:
        aliases.extend(clean_yaml_scalar(item) for item in list_match.group(1).split(",") if item.strip())

    multi_line_match = re.search(r"aliases:\s*\n((?:\s*-\s*.*(?:\n|$))+)", yaml_block, re.IGNORECASE)
    if multi_line_match:
        for line in multi_line_match.group(1).strip().split("\n"):
            item = re.sub(r"^\s*-\s*", "", line).strip()
            if item:
                aliases.append(clean_yaml_scalar(item))

    return [alias for alias in aliases if alias]


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def string_values(value: Any) -> list[str]:
    return [item.strip() for item in as_list(value) if isinstance(item, str) and item.strip()]


def catalog_entries(data: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(data, list):
        return [("", item) for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    for key in CATALOG_CONTAINER_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            return [("", item) for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [(str(k), item) for k, item in value.items() if isinstance(item, dict)]

    return [(str(key), value) for key, value in data.items() if isinstance(value, dict)]


def target_from_entry(entry: dict[str, Any], fallback_key: str = "") -> str | None:
    for key in TARGET_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return Path(value.strip()).stem
    if fallback_key:
        return Path(fallback_key).stem
    for key in TITLE_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def aliases_from_entry(entry: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in ALIAS_KEYS:
        aliases.extend(string_values(entry.get(key)))
    return aliases


def terms_from_entry(entry: dict[str, Any], target: str) -> list[str]:
    terms = [target]
    terms.extend(aliases_from_entry(entry))
    for key in TITLE_KEYS:
        terms.extend(string_values(entry.get(key)))
    return terms
