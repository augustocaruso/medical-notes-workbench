"""Taxonomy resolution against the existing Wiki tree."""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from wiki.common import MissingPathError, ValidationError
from wiki.taxonomy.normalize import _fold_taxonomy_segment, normalize_taxonomy, safe_title
from wiki.taxonomy.schema import (
    CANONICAL_TAXONOMY,
    TaxonomyResolution,
    _canonical_area_aliases_by_fold,
    _canonical_specialties_by_fold,
    _canonical_specialties_for_root,
)

_NEAR_DUPLICATE_CUTOFF = 0.9

def _canonicalize_taxonomy_parts(parts: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[dict[str, str], ...]]:
    roots = _canonical_area_aliases_by_fold()
    specialties = _canonical_specialties_by_fold()
    first = parts[0]
    first_folded = _fold_taxonomy_segment(first)
    canonicalized: list[dict[str, str]] = []

    if first_folded in roots:
        root = roots[first_folded]
        if len(parts) == 1:
            raise ValidationError(f"Taxonomy must include a specialty under canonical area: {root}")
        root_specialties = _canonical_specialties_for_root(root)
        second = parts[1]
        second_folded = _fold_taxonomy_segment(second)
        if second_folded not in root_specialties:
            raise ValidationError(f"Unknown specialty under {root}: {second}")
        specialty = root_specialties[second_folded]
        canonical_parts = (root, specialty, *parts[2:])
        if canonical_parts[:2] != parts[:2]:
            canonicalized.append({"from": "/".join(parts[:2]), "to": "/".join(canonical_parts[:2]), "under": ""})
        return canonical_parts, tuple(canonicalized)

    if first_folded in specialties:
        root, specialty = specialties[first_folded]
        canonical_parts = (root, specialty, *parts[1:])
        canonicalized.append({"from": first, "to": "/".join(canonical_parts[:2]), "under": ""})
        return canonical_parts, tuple(canonicalized)

    root_names = ", ".join(root for root, _specialties in CANONICAL_TAXONOMY)
    raise ValidationError(
        f"Taxonomy must start with a canonical area or known specialty. Got: {first}. "
        f"Canonical areas: {root_names}"
    )


def _visible_child_dirs(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(
        (child for child in path.iterdir() if child.is_dir() and not child.name.startswith(".")),
        key=lambda child: _fold_taxonomy_segment(child.name),
    )


def _suggest_existing_segments(siblings: list[Path], requested: str) -> list[str]:
    folded_to_names: dict[str, list[str]] = {}
    for sibling in siblings:
        folded_to_names.setdefault(_fold_taxonomy_segment(sibling.name), []).append(sibling.name)
    requested_folded = _fold_taxonomy_segment(requested)
    close = difflib.get_close_matches(requested_folded, list(folded_to_names), n=4, cutoff=_NEAR_DUPLICATE_CUTOFF)
    suggestions: list[str] = []
    for folded in close:
        suggestions.extend(folded_to_names[folded])
    return suggestions


def _format_suggestions(suggestions: list[str]) -> str:
    if not suggestions:
        return ""
    return " Sugestões existentes: " + ", ".join(suggestions)


def _match_existing_segment(parent: Path, requested: str) -> tuple[str | None, list[str]]:
    siblings = _visible_child_dirs(parent)
    exact = [sibling.name for sibling in siblings if sibling.name == requested]
    if exact:
        return exact[0], []

    requested_folded = _fold_taxonomy_segment(requested)
    folded_matches = [sibling.name for sibling in siblings if _fold_taxonomy_segment(sibling.name) == requested_folded]
    if len(folded_matches) == 1:
        return folded_matches[0], []
    if len(folded_matches) > 1:
        raise ValidationError(
            f"Taxonomy segment is ambiguous under {parent}: {requested}. Matches: {', '.join(folded_matches)}"
        )
    return None, _suggest_existing_segments(siblings, requested)


def _validate_taxonomy_not_title(parts: tuple[str, ...], title: str) -> None:
    title_key = _fold_taxonomy_segment(safe_title(title))
    if parts and _fold_taxonomy_segment(parts[-1]) == title_key:
        raise ValidationError(
            "Taxonomy must be the folder/category path only; do not repeat the note title "
            f"as the final folder: taxonomy {'/'.join(parts)} + title {title}"
        )


def resolve_taxonomy(
    wiki_dir: Path,
    taxonomy: str,
    *,
    title: str | None = None,
    allow_new_leaf: bool = True,
) -> TaxonomyResolution:
    requested_parts = normalize_taxonomy(taxonomy)
    canonical_request_parts, alias_canonicalized = _canonicalize_taxonomy_parts(requested_parts)
    if title is not None:
        _validate_taxonomy_not_title(canonical_request_parts, title)
    if not wiki_dir.exists():
        raise MissingPathError(f"Wiki dir not found: {wiki_dir}")
    if not wiki_dir.is_dir():
        raise ValidationError(f"Wiki dir is not a directory: {wiki_dir}")

    canonical_parts: list[str] = []
    canonicalized: list[dict[str, str]] = list(alias_canonicalized)
    new_dirs: list[str] = []
    parent = wiki_dir

    for idx, requested in enumerate(canonical_request_parts):
        is_leaf = idx == len(canonical_request_parts) - 1
        matched, suggestions = _match_existing_segment(parent, requested)
        if matched is None:
            if idx < 2:
                canonical_parts.append(requested)
                new_dirs.append("/".join(canonical_parts))
                parent = parent / requested
                continue
            if is_leaf and allow_new_leaf and canonical_parts:
                if suggestions:
                    raise ValidationError(
                        f"New taxonomy leaf '{requested}' under {'/'.join(canonical_parts)} is too similar to "
                        f"an existing folder.{_format_suggestions(suggestions)}"
                    )
                canonical_parts.append(requested)
                new_dirs.append("/".join(canonical_parts))
                parent = parent / requested
                continue
            location = "/".join(canonical_parts) if canonical_parts else "<wiki-root>"
            raise ValidationError(
                f"Taxonomy segment must already exist under {location}: {requested}."
                f"{_format_suggestions(suggestions)}"
            )

        if matched != requested:
            canonicalized.append({"from": requested, "to": matched, "under": "/".join(canonical_parts)})
        canonical_parts.append(matched)
        parent = parent / matched

    resolved_parts = tuple(canonical_parts)
    if title is not None:
        _validate_taxonomy_not_title(resolved_parts, title)
    return TaxonomyResolution(
        requested_taxonomy="/".join(requested_parts),
        taxonomy="/".join(resolved_parts),
        parts=resolved_parts,
        canonicalized=tuple(canonicalized),
        new_dirs=tuple(new_dirs),
    )


def resolve_target_for_note(
    wiki_dir: Path,
    taxonomy: str,
    title: str,
    *,
    allow_new_taxonomy_leaf: bool = True,
) -> tuple[Path, TaxonomyResolution]:
    resolution = resolve_taxonomy(wiki_dir, taxonomy, title=title, allow_new_leaf=allow_new_taxonomy_leaf)
    return wiki_dir.joinpath(*resolution.parts, f"{safe_title(title)}.md"), resolution


def target_for_note(
    wiki_dir: Path,
    taxonomy: str,
    title: str,
    *,
    allow_new_taxonomy_leaf: bool = True,
) -> Path:
    target, _resolution = resolve_target_for_note(
        wiki_dir,
        taxonomy,
        title,
        allow_new_taxonomy_leaf=allow_new_taxonomy_leaf,
    )
    return target
