"""Vault hygiene checks and cleanup for ``fix-wiki``."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from wiki.link_terms import is_index_target, normalize_key

WIKI_HYGIENE_SCHEMA = "medical-notes-workbench.wiki-hygiene.v1"
WIKI_HYGIENE_CLEANUP_SCHEMA = "medical-notes-workbench.wiki-hygiene-cleanup.v1"
IGNORED_EMPTY_DIR_NAMES = {"attachments", "_Mock_Embeds"}


def collect_wiki_hygiene(wiki_dir: Path, *, sample_limit: int = 20) -> dict[str, Any]:
    backup_files = _backup_or_temp_files(wiki_dir, kind="backup")
    rewrite_files = _backup_or_temp_files(wiki_dir, kind="rewrite")
    empty_dirs = _empty_dirs(wiki_dir)
    duplicate_hash_groups = _duplicate_hash_groups(wiki_dir)
    duplicate_filename_groups = _duplicate_filename_groups(wiki_dir)
    depth_issues = _note_depth_issues(wiki_dir)

    return {
        "schema": WIKI_HYGIENE_SCHEMA,
        "wiki_dir": str(wiki_dir),
        "bak_or_rewrite": len(backup_files) + len(rewrite_files),
        "backup_files": _rel_sample(wiki_dir, backup_files, sample_limit),
        "rewrite_files": _rel_sample(wiki_dir, rewrite_files, sample_limit),
        "backup_file_count": len(backup_files),
        "rewrite_file_count": len(rewrite_files),
        "empty_dirs": len(empty_dirs),
        "empty_dir_paths": _rel_sample(wiki_dir, empty_dirs, sample_limit),
        "duplicate_hash_groups": len(duplicate_hash_groups),
        "duplicate_hash_samples": duplicate_hash_groups[:sample_limit],
        "duplicate_filename_groups": len(duplicate_filename_groups),
        "duplicate_filename_samples": duplicate_filename_groups[:sample_limit],
        "note_depth_issues": len(depth_issues),
        "note_depth_samples": depth_issues[:sample_limit],
    }


def cleanup_wiki_hygiene(
    wiki_dir: Path,
    *,
    archive_root: Path,
    archive_backups: bool = True,
    remove_rewrites: bool = True,
    remove_empty_dirs: bool = True,
    sample_limit: int = 20,
) -> dict[str, Any]:
    archive_root.mkdir(parents=True, exist_ok=True)
    archived: list[dict[str, str]] = []
    removed_rewrites: list[str] = []
    removed_empty_dirs: list[str] = []
    errors: list[dict[str, str]] = []

    if archive_backups:
        for path in _backup_or_temp_files(wiki_dir, kind="backup"):
            try:
                archived.append(_archive_file(wiki_dir, path, archive_root))
            except OSError as exc:
                errors.append({"path": str(path), "operation": "archive_backup", "error": str(exc)})

    if remove_rewrites:
        for path in _backup_or_temp_files(wiki_dir, kind="rewrite"):
            try:
                archived.append(_archive_file(wiki_dir, path, archive_root))
                removed_rewrites.append(path.relative_to(wiki_dir).as_posix())
            except OSError as exc:
                errors.append({"path": str(path), "operation": "archive_rewrite", "error": str(exc)})

    if remove_empty_dirs:
        for path in sorted(_empty_dirs(wiki_dir), key=lambda item: len(item.relative_to(wiki_dir).parts), reverse=True):
            try:
                path.rmdir()
                removed_empty_dirs.append(path.relative_to(wiki_dir).as_posix())
            except OSError as exc:
                errors.append({"path": str(path), "operation": "remove_empty_dir", "error": str(exc)})

    return {
        "schema": WIKI_HYGIENE_CLEANUP_SCHEMA,
        "wiki_dir": str(wiki_dir),
        "archive_root": str(archive_root),
        "archived_count": len(archived),
        "archived": archived[:sample_limit],
        "removed_rewrite_count": len(removed_rewrites),
        "removed_rewrites": removed_rewrites[:sample_limit],
        "removed_empty_dir_count": len(removed_empty_dirs),
        "removed_empty_dirs": removed_empty_dirs[:sample_limit],
        "error_count": len(errors),
        "errors": errors[:sample_limit],
    }


def _backup_or_temp_files(wiki_dir: Path, *, kind: str) -> list[Path]:
    if not wiki_dir.exists():
        return []
    files: list[Path] = []
    for path in wiki_dir.rglob("*"):
        if not path.is_file() or any(part.startswith(".") for part in path.relative_to(wiki_dir).parts):
            continue
        name = path.name
        if kind == "backup" and ".bak" in name:
            files.append(path)
        elif kind == "rewrite" and ".rewrite" in name:
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(wiki_dir).as_posix())


def _empty_dirs(wiki_dir: Path) -> list[Path]:
    if not wiki_dir.exists():
        return []
    empty: list[Path] = []
    for path in sorted((item for item in wiki_dir.rglob("*") if item.is_dir()), key=lambda item: item.as_posix()):
        rel = path.relative_to(wiki_dir)
        if not rel.parts or any(part.startswith(".") for part in rel.parts):
            continue
        if path.name in IGNORED_EMPTY_DIR_NAMES:
            continue
        try:
            if not any(path.iterdir()):
                empty.append(path)
        except OSError:
            continue
    return empty


def _duplicate_hash_groups(wiki_dir: Path) -> list[dict[str, Any]]:
    by_hash: dict[str, list[str]] = {}
    for path in _note_files(wiki_dir):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        by_hash.setdefault(digest, []).append(path.relative_to(wiki_dir).as_posix())
    return [
        {"sha256": digest, "files": sorted(files), "count": len(files)}
        for digest, files in sorted(by_hash.items())
        if len(files) > 1
    ]


def _duplicate_filename_groups(wiki_dir: Path) -> list[dict[str, Any]]:
    by_name: dict[str, list[str]] = {}
    for path in _note_files(wiki_dir):
        if is_index_target(path.stem):
            continue
        by_name.setdefault(normalize_key(path.stem), []).append(path.relative_to(wiki_dir).as_posix())
    return [
        {"key": key, "files": sorted(files), "count": len(files)}
        for key, files in sorted(by_name.items())
        if len(files) > 1
    ]


def _note_depth_issues(wiki_dir: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for path in _note_files(wiki_dir):
        rel = path.relative_to(wiki_dir)
        if is_index_target(path.stem):
            continue
        if len(rel.parts) != 4:
            issues.append({"file": rel.as_posix(), "depth": len(rel.parts)})
    return issues


def _note_files(wiki_dir: Path) -> list[Path]:
    if not wiki_dir.exists():
        return []
    return sorted(
        path
        for path in wiki_dir.rglob("*.md")
        if path.is_file() and not path.name.startswith(".") and ".bak" not in path.name and ".rewrite" not in path.name
    )


def _archive_file(wiki_dir: Path, path: Path, archive_root: Path) -> dict[str, str]:
    rel = path.relative_to(wiki_dir)
    destination = _unique_destination(archive_root / rel)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(destination))
    return {"source": rel.as_posix(), "destination": str(destination)}


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(1, 1000):
        candidate = path.with_name(f"{path.name}.{idx}")
        if not candidate.exists():
            return candidate
    raise OSError(f"Too many archived files with same name: {path}")


def _rel_sample(wiki_dir: Path, paths: list[Path], limit: int) -> list[str]:
    return [path.relative_to(wiki_dir).as_posix() for path in paths[:limit]]
