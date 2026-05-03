"""Raw chat frontmatter and filesystem helpers."""
from __future__ import annotations

import errno
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from wiki.common import FileWriteError, MissingPathError, ValidationError
from wiki.note_plan import note_plan_summary, parse_triage_note_plan

_FRONTMATTER_DELIM = "---"
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
BACKUP_CLEANUP_SCHEMA = "medical-notes-workbench.backup-cleanup.v1"
_NOTE_BACKUP_RE = re.compile(r"^(?P<original>.+\.md)\.bak(?:\.\d+)?$")
_ATOMIC_WRITE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)
_WINDOWS_LOCK_WINERRORS = {5, 32, 33}


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
        try:
            parsed = json.loads(value)
            if isinstance(parsed, str):
                return parsed
        except json.JSONDecodeError:
            pass
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


def prune_backup_files(root: Path, *, max_per_file: int = 3, retention_days: int = 14) -> dict[str, Any]:
    """Prune adjacent Markdown backup files created by med_ops.

    Backups are grouped by original note name, e.g. ``A.md.bak`` and
    ``A.md.bak.1``. The newest ``max_per_file`` backups are retained unless they
    are older than ``retention_days``. Pass a negative retention to disable
    age-based pruning.
    """

    if not root.exists():
        raise MissingPathError(f"Backup cleanup root not found: {root}")
    if max_per_file < 0:
        raise ValidationError("max_per_file must be >= 0")

    groups: dict[Path, list[Path]] = {}
    for path in root.rglob("*.bak*"):
        if not path.is_file():
            continue
        match = _NOTE_BACKUP_RE.match(path.name)
        if not match:
            continue
        groups.setdefault(path.with_name(match.group("original")), []).append(path)

    cutoff = time.time() - (retention_days * 86400) if retention_days >= 0 else None
    deleted: list[str] = []
    kept: list[str] = []
    for _original, backups in sorted(groups.items(), key=lambda item: item[0].as_posix()):
        ordered = sorted(backups, key=lambda item: item.stat().st_mtime, reverse=True)
        for idx, backup in enumerate(ordered):
            mtime = backup.stat().st_mtime
            too_many = idx >= max_per_file
            too_old = cutoff is not None and mtime < cutoff
            if too_many or too_old:
                backup.unlink()
                deleted.append(str(backup))
            else:
                kept.append(str(backup))

    return {
        "schema": BACKUP_CLEANUP_SCHEMA,
        "root": str(root),
        "max_per_file": max_per_file,
        "retention_days": retention_days,
        "group_count": len(groups),
        "kept_count": len(kept),
        "deleted_count": len(deleted),
        "deleted": deleted,
    }


def _is_retryable_replace_error(exc: OSError) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if getattr(exc, "winerror", None) in _WINDOWS_LOCK_WINERRORS:
        return True
    return getattr(exc, "errno", None) in {errno.EACCES, errno.EPERM, errno.EBUSY}


def _replace_with_retries(path: Path, tmp: Path, retry_delays: tuple[float, ...]) -> None:
    attempts = len(retry_delays) + 1
    last_error: OSError | None = None
    for attempt_idx in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except OSError as exc:
            last_error = exc
            if attempt_idx >= len(retry_delays) or not _is_retryable_replace_error(exc):
                break
            time.sleep(retry_delays[attempt_idx])

    raise FileWriteError(
        f"Could not atomically replace {path} after {attempts} attempts. "
        f"The file may be locked by Obsidian, iCloud Drive, antivirus, or another process. "
        f"Original error: {last_error}"
    ) from last_error


def atomic_write_text(path: Path, text: str, *, retry_delays: tuple[float, ...] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        _replace_with_retries(path, tmp, _ATOMIC_WRITE_RETRY_DELAYS if retry_delays is None else retry_delays)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


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
    result = {
        "path": str(path),
        "status": meta.get("status", ""),
        "tipo": meta.get("tipo", ""),
        "titulo_triagem": meta.get("titulo_triagem", ""),
        "fonte_id": meta.get("fonte_id", ""),
    }
    raw_plan = meta.get("note_plan", "")
    if raw_plan:
        try:
            result.update({key: str(value) for key, value in note_plan_summary(parse_triage_note_plan(raw_plan, path)).items()})
        except ValidationError as exc:
            result["note_plan_error"] = str(exc)
    return result


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
