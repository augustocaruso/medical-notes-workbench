#!/usr/bin/env python3
"""Deterministic Obsidian note metadata helpers for Gemini extension agents.

The flashcard agent owns card reasoning. This script owns small, auditable note
metadata operations: creating Obsidian deeplinks and adding/removing frontmatter
tags after Anki writes succeed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_MISSING = 4
EXIT_IO = 5

_DELIM = "---"
_TAG_KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<key>tags?|Tags?)\s*:\s*(?P<value>.*)$")
_LIST_ITEM_RE = re.compile(r"^\s*-\s*(?P<value>.*?)\s*$")
_VALID_TAG_RE = re.compile(r"^[A-Za-z0-9_/-]+$")


class NoteUtilsError(Exception):
    exit_code = EXIT_IO


class UsageError(NoteUtilsError):
    exit_code = EXIT_USAGE


class MissingPathError(NoteUtilsError):
    exit_code = EXIT_MISSING


def _path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


def _resolve_existing_file(value: str | os.PathLike[str]) -> Path:
    path = _path(value)
    if not path.exists():
        raise MissingPathError(f"File not found: {path}")
    if not path.is_file():
        raise UsageError(f"Expected a file path, got: {path}")
    return path.resolve()


def _backup_path(path: Path) -> Path:
    base = path.with_name(path.name + ".bak")
    if not base.exists():
        return base
    for idx in range(1, 1000):
        candidate = path.with_name(f"{path.name}.bak.{idx}")
        if not candidate.exists():
            return candidate
    raise UsageError(f"Too many backups already exist for {path}")


def _atomic_write_text(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        finally:
            raise


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _candidate_vault_roots(path: Path, explicit_root: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_root:
        candidates.append(_path(explicit_root).resolve())

    env_wiki = os.getenv("MED_WIKI_DIR")
    if env_wiki:
        candidates.append(_path(env_wiki).resolve())

    for parent in (path.parent, *path.parents):
        if (parent / ".obsidian").is_dir():
            candidates.append(parent.resolve())
        if parent.name == "Wiki_Medicina":
            candidates.append(parent.resolve())

    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        if candidate not in seen and _is_relative_to(path, candidate):
            roots.append(candidate)
            seen.add(candidate)
    return roots


def infer_vault_root(path: Path, explicit_root: str | None = None) -> Path | None:
    roots = _candidate_vault_roots(path, explicit_root)
    if not roots:
        return None
    return max(roots, key=lambda root: len(root.parts))


def obsidian_deeplink(
    path: Path,
    *,
    vault_root: str | None = None,
    vault_name: str | None = None,
    pane_type: str | None = None,
    absolute_path: bool = False,
) -> str:
    """Return an Obsidian URI for a note path.

    By default, use `vault` + vault-relative `file` so the link works across
    devices that store the same vault in different filesystem locations.
    """
    resolved = path.resolve()
    if absolute_path:
        encoded_path = quote(str(resolved), safe="")
        uri = f"obsidian://open?path={encoded_path}"
    else:
        root = infer_vault_root(resolved, explicit_root=vault_root)
        if root is None:
            raise UsageError(
                "Could not infer the Obsidian vault root. Pass --vault-root or create a .obsidian "
                "directory in the vault."
            )
        name = vault_name or root.name
        file_path = resolved.relative_to(root).as_posix()
        uri = f"obsidian://open?vault={quote(name, safe='')}&file={quote(file_path, safe='')}"
    if pane_type:
        uri += f"&paneType={quote(pane_type, safe='')}"
    return uri


def _split_frontmatter(text: str) -> tuple[list[str] | None, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _DELIM:
        return None, text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _DELIM:
            return lines[1:idx], "".join(lines[idx + 1 :])
    return None, text


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _strip_inline_comment(value: str) -> str:
    quote_char: str | None = None
    bracket_depth = 0
    for idx, char in enumerate(value):
        if char in {"'", '"'}:
            quote_char = None if quote_char == char else char
        elif char == "[" and quote_char is None:
            bracket_depth += 1
        elif char == "]" and quote_char is None and bracket_depth:
            bracket_depth -= 1
        if (
            char == "#"
            and quote_char is None
            and bracket_depth == 0
            and idx > 0
            and value[idx - 1].isspace()
        ):
            return value[:idx].rstrip()
    return value.strip()


def normalize_tag(tag: str) -> str:
    normalized = tag.strip().lstrip("#").strip()
    if not normalized:
        raise UsageError("Tag cannot be empty")
    if not _VALID_TAG_RE.match(normalized):
        raise UsageError(
            f"Unsupported tag {tag!r}; use Obsidian-style tags with letters, numbers, _, / or -"
        )
    return normalized


def _parse_inline_tags(value: str) -> list[str]:
    value = _strip_inline_comment(value).strip()
    if not value:
        return []
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    raw_items = [part.strip() for part in value.split(",")] if "," in value else [value]
    return [normalize_tag(_strip_quotes(item)) for item in raw_items if _strip_quotes(item)]


def _find_tags_block(frontmatter: list[str]) -> tuple[int, int] | None:
    for idx, line in enumerate(frontmatter):
        match = _TAG_KEY_RE.match(line)
        if not match or match.group("indent"):
            continue
        value = _strip_inline_comment(match.group("value"))
        if value:
            return idx, idx + 1
        end = idx + 1
        while end < len(frontmatter) and _LIST_ITEM_RE.match(frontmatter[end]):
            end += 1
        return idx, end
    return None


def _read_tags_from_block(block: list[str]) -> list[str]:
    if not block:
        return []
    first = _TAG_KEY_RE.match(block[0])
    if not first:
        return []
    value = _strip_inline_comment(first.group("value"))
    raw_tags: list[str] = []
    if value:
        raw_tags.extend(_parse_inline_tags(value))
    else:
        for line in block[1:]:
            item = _LIST_ITEM_RE.match(line)
            if item:
                raw_tags.append(normalize_tag(_strip_quotes(_strip_inline_comment(item.group("value")))))

    seen: set[str] = set()
    tags: list[str] = []
    for tag in raw_tags:
        if tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags


def _format_yaml_tag(tag: str) -> str:
    if _VALID_TAG_RE.match(tag):
        return tag
    return json.dumps(tag, ensure_ascii=False)


def _format_tags_block(tags: list[str]) -> list[str]:
    return ["tags:\n", *(f"  - {_format_yaml_tag(tag)}\n" for tag in tags)]


def _mutate_frontmatter_tags(text: str, tag: str, action: str) -> tuple[str, list[str]]:
    target = normalize_tag(tag)
    frontmatter, body = _split_frontmatter(text)

    if frontmatter is None:
        if action == "remove-tag":
            return text, []
        frontmatter = _format_tags_block([target])
        return "---\n" + "".join(frontmatter) + "---\n" + text, [target]

    block_range = _find_tags_block(frontmatter)
    existing = _read_tags_from_block(frontmatter[block_range[0] : block_range[1]]) if block_range else []
    tags = list(existing)

    if action == "add-tag" and target not in tags:
        tags.append(target)
    elif action == "remove-tag":
        tags = [item for item in tags if item != target]

    if block_range:
        start, end = block_range
        replacement = _format_tags_block(tags) if tags else []
        frontmatter = [*frontmatter[:start], *replacement, *frontmatter[end:]]
    elif tags:
        frontmatter = [*frontmatter, *_format_tags_block(tags)]

    if not any(line.strip() for line in frontmatter):
        return body, tags
    return "---\n" + "".join(frontmatter) + "---\n" + body, tags


def mutate_note_tag(path: Path, tag: str, action: str, *, dry_run: bool = False, backup: bool = False) -> dict[str, object]:
    old_text = path.read_text(encoding="utf-8")
    new_text, tags = _mutate_frontmatter_tags(old_text, tag, action)
    changed = new_text != old_text
    backup_file: Path | None = None

    if changed and not dry_run:
        if backup:
            backup_file = _backup_path(path)
            shutil.copy2(path, backup_file)
        _atomic_write_text(path, new_text)

    return {
        "path": str(path),
        "action": action,
        "tag": normalize_tag(tag),
        "changed": changed,
        "dry_run": dry_run,
        "backup": str(backup_file) if backup_file else None,
        "tags": tags,
    }


def _cmd_deeplink(args: argparse.Namespace) -> int:
    records = []
    for raw_path in args.paths:
        path = _resolve_existing_file(raw_path)
        records.append(
            {
                "path": str(path),
                "deeplink": obsidian_deeplink(
                    path,
                    vault_root=args.vault_root,
                    vault_name=args.vault_name,
                    pane_type=args.pane_type,
                    absolute_path=args.absolute_path,
                ),
            }
        )
    print(json.dumps(records, ensure_ascii=False, indent=2))
    return EXIT_OK


def _cmd_tag(args: argparse.Namespace) -> int:
    records = []
    for raw_path in args.paths:
        path = _resolve_existing_file(raw_path)
        records.append(
            mutate_note_tag(path, args.tag, args.action, dry_run=args.dry_run, backup=args.backup)
        )
    print(json.dumps(records, ensure_ascii=False, indent=2))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    deeplink = subparsers.add_parser("deeplink", help="emit Obsidian deeplink JSON for note paths")
    deeplink.add_argument("paths", nargs="+", help="Markdown note paths")
    deeplink.add_argument(
        "--vault-root",
        default=None,
        help="vault root path; defaults to MED_WIKI_DIR, nearest .obsidian parent, or Wiki_Medicina",
    )
    deeplink.add_argument(
        "--vault-name",
        default=None,
        help="vault name to encode in the URI; defaults to the inferred vault root folder name",
    )
    deeplink.add_argument(
        "--absolute-path",
        action="store_true",
        help="emit obsidian://open?path=... instead of portable vault+file links",
    )
    deeplink.add_argument(
        "--pane-type",
        choices=("tab", "split", "window"),
        default=None,
        help="optional Obsidian paneType parameter",
    )
    deeplink.set_defaults(func=_cmd_deeplink)

    for action in ("add-tag", "remove-tag"):
        tag_parser = subparsers.add_parser(action, help=f"{action} in note frontmatter")
        tag_parser.add_argument("paths", nargs="+", help="Markdown note paths")
        tag_parser.add_argument("--tag", default="anki", help="frontmatter tag, default: anki")
        tag_parser.add_argument("--dry-run", action="store_true", help="report changes without writing")
        tag_parser.add_argument("--backup", action="store_true", help="write .bak before changing a file")
        tag_parser.set_defaults(func=_cmd_tag)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NoteUtilsError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_IO


if __name__ == "__main__":
    raise SystemExit(main())
