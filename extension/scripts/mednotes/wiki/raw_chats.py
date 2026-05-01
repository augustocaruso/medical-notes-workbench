"""Raw chat frontmatter and filesystem helpers."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from wiki.common import MissingPathError, ValidationError

_FRONTMATTER_DELIM = "---"
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")


def split_frontmatter(text: str) -> tuple[list[str] | None, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return None, text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_DELIM:
            return lines[1:idx], "".join(lines[idx + 1 :])
    return None, text


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> dict[str, str]:
    frontmatter, _body = split_frontmatter(text)
    if frontmatter is None:
        return {}
    parsed: dict[str, str] = {}
    for line in frontmatter:
        match = _KEY_RE.match(line.strip())
        if match:
            parsed[match.group(1)] = _strip_quotes(match.group(2))
    return parsed


def _format_yaml_value(value: str) -> str:
    if value == "":
        return '""'
    if re.match(r"^[A-Za-z0-9_./@+-]+$", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def update_frontmatter(text: str, updates: dict[str, str]) -> str:
    frontmatter, body = split_frontmatter(text)
    formatted = {key: f"{key}: {_format_yaml_value(value)}\n" for key, value in updates.items()}
    if frontmatter is None:
        return "---\n" + "".join(formatted.values()) + "---\n" + text

    seen: set[str] = set()
    out: list[str] = []
    for line in frontmatter:
        match = _KEY_RE.match(line.strip())
        if match and match.group(1) in formatted:
            key = match.group(1)
            out.append(formatted[key])
            seen.add(key)
        else:
            out.append(line)
    for key, line in formatted.items():
        if key not in seen:
            out.append(line)
    return "---\n" + "".join(out) + "---\n" + body


def read_note_meta(path: Path) -> dict[str, str]:
    try:
        return parse_frontmatter(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MissingPathError(f"File not found: {path}") from exc


def _backup_path(path: Path) -> Path:
    base = path.with_name(path.name + ".bak")
    if not base.exists():
        return base
    for idx in range(1, 1000):
        candidate = path.with_name(f"{path.name}.bak.{idx}")
        if not candidate.exists():
            return candidate
    raise ValidationError(f"Too many backups already exist for {path}")


def create_backup(path: Path) -> Path:
    if not path.exists():
        raise MissingPathError(f"File not found: {path}")
    backup = _backup_path(path)
    shutil.copy2(path, backup)
    return backup


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def mutate_raw_frontmatter(raw_file: Path, updates: dict[str, str], dry_run: bool = False, backup: bool = False) -> dict[str, Any]:
    if not raw_file.exists():
        raise MissingPathError(f"Raw file not found: {raw_file}")
    original = raw_file.read_text(encoding="utf-8")
    updated = update_frontmatter(original, updates)
    if dry_run:
        return {"raw_file": str(raw_file), "backup": None, "updated": False, "updates": updates}
    backup_path = create_backup(raw_file) if backup else None
    atomic_write_text(raw_file, updated)
    return {"raw_file": str(raw_file), "backup": str(backup_path) if backup_path else None, "updated": True, "updates": updates}


def list_raw_files(raw_dir: Path) -> list[Path]:
    if not raw_dir.exists():
        raise MissingPathError(f"Raw dir not found: {raw_dir}")
    return sorted(path for path in raw_dir.glob("*.md") if path.is_file())


def raw_summary(path: Path) -> dict[str, str]:
    meta = read_note_meta(path)
    return {
        "path": str(path),
        "status": meta.get("status", ""),
        "tipo": meta.get("tipo", ""),
        "titulo_triagem": meta.get("titulo_triagem", ""),
        "fonte_id": meta.get("fonte_id", ""),
    }


def list_by_status(raw_dir: Path, mode: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in list_raw_files(raw_dir):
        item = raw_summary(path)
        status = item["status"].lower()
        tipo = item["tipo"].lower()
        if mode == "pending" and status in {"", "pendente"}:
            rows.append(item)
        elif mode == "triados" and status == "triado" and tipo == "medicina":
            rows.append(item)
    return rows
