#!/usr/bin/env python3
"""Deterministic file/YAML operations for the Medical Notes Workbench pipeline.

The Gemini agent owns clinical reasoning. This script owns filesystem changes:
frontmatter status updates, non-overwriting note writes, manifest publishing, and
the optional semantic linker call.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None


DEFAULT_RAW_DIR = r"C:\Users\leona\OneDrive\Chats_Raw"
DEFAULT_WIKI_DIR = r"C:\Users\leona\iCloudDrive\iCloud~md~obsidian\Wiki_Medicina"
DEFAULT_CATALOG_PATH = "~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json"
DEFAULT_LINKER_PATH = r"C:\Users\leona\.gemini\skills\med-auto-linker\med_linker.py"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_MISSING = 4
EXIT_IO = 5
EXIT_LINKER = 6

_FRONTMATTER_DELIM = "---"
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_UNSAFE_TITLE_RE = re.compile(r'[\\/*?:"<>|\x00-\x1f]')
_UNSAFE_TAXONOMY_RE = re.compile(r'[<>:"|?*\x00-\x1f]')


class MedOpsError(Exception):
    """Base exception carrying a process exit code."""

    exit_code = EXIT_IO


class ValidationError(MedOpsError):
    exit_code = EXIT_VALIDATION


class MissingPathError(MedOpsError):
    exit_code = EXIT_MISSING


class CollisionError(MedOpsError):
    exit_code = EXIT_VALIDATION


@dataclass(frozen=True)
class MedConfig:
    raw_dir: Path
    wiki_dir: Path
    linker_path: Path
    catalog_path: Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


def _read_toml(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    if tomllib is None:
        raise ValidationError("tomllib unavailable; use Python 3.11+ for config.toml support")
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _find_config(explicit: str | None) -> Path | None:
    if explicit:
        return _path(explicit)
    candidates: list[Path] = []
    cwd = Path.cwd().resolve()
    candidates.extend(parent / "config.toml" for parent in (cwd, *cwd.parents))
    script = Path(__file__).resolve()
    candidates.extend(parent / "config.toml" for parent in script.parents)
    return next((candidate for candidate in candidates if candidate.exists()), None)


def resolve_config(args: argparse.Namespace) -> MedConfig:
    cfg = _read_toml(_find_config(getattr(args, "config", None)))
    section = cfg.get("chat_processor", {}) if isinstance(cfg.get("chat_processor", {}), dict) else {}

    def pick(name: str, env: str, default: str) -> Path:
        cli_value = getattr(args, name, None)
        value = cli_value or os.getenv(env) or section.get(name) or default
        return _path(str(value))

    linker_value = getattr(args, "linker_path", None) or os.getenv("MED_LINKER_PATH") or section.get("linker_path")
    if linker_value:
        linker_path = _path(str(linker_value))
    else:
        bundled = _bundled_linker_path()
        linker_path = bundled if bundled.exists() else _path(DEFAULT_LINKER_PATH)

    return MedConfig(
        raw_dir=pick("raw_dir", "MED_RAW_DIR", DEFAULT_RAW_DIR),
        wiki_dir=pick("wiki_dir", "MED_WIKI_DIR", DEFAULT_WIKI_DIR),
        linker_path=linker_path,
        catalog_path=pick("catalog_path", "MED_CATALOG_PATH", DEFAULT_CATALOG_PATH),
    )


def _bundled_linker_path() -> Path:
    return Path(__file__).resolve().with_name("med_linker.py")


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


def normalize_taxonomy(taxonomy: str) -> tuple[str, ...]:
    taxonomy = taxonomy.strip()
    if not taxonomy:
        raise ValidationError("Taxonomy cannot be empty")
    if _DRIVE_RE.match(taxonomy):
        raise ValidationError(f"Taxonomy must be relative, got drive path: {taxonomy}")
    normalized = taxonomy.replace("\\", "/")
    if normalized.startswith("/") or PureWindowsPath(normalized).is_absolute():
        raise ValidationError(f"Taxonomy must be relative: {taxonomy}")
    parts = tuple(part.strip() for part in normalized.split("/"))
    if any(not part for part in parts):
        raise ValidationError(f"Taxonomy has an empty segment: {taxonomy}")
    if any(part in {".", ".."} for part in parts):
        raise ValidationError(f"Taxonomy cannot contain '.' or '..': {taxonomy}")
    bad = [part for part in parts if _UNSAFE_TAXONOMY_RE.search(part)]
    if bad:
        raise ValidationError(f"Taxonomy has unsafe characters: {bad[0]}")
    return parts


def safe_title(title: str) -> str:
    cleaned = _UNSAFE_TITLE_RE.sub("", title).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise ValidationError("Title produced an empty filename")
    return cleaned


def target_for_note(wiki_dir: Path, taxonomy: str, title: str) -> Path:
    parts = normalize_taxonomy(taxonomy)
    return wiki_dir.joinpath(*parts, f"{safe_title(title)}.md")


def resolve_collision(path: Path, mode: str, reserved: set[Path]) -> Path:
    if mode not in {"abort", "suffix"}:
        raise ValidationError(f"Invalid collision mode: {mode}")
    if mode == "abort":
        if path.exists() or path in reserved:
            raise CollisionError(f"Target note already exists: {path}")
        return path

    candidate = path
    idx = 2
    while candidate.exists() or candidate in reserved:
        candidate = path.with_name(f"{path.stem} ({idx}){path.suffix}")
        idx += 1
    return candidate


def write_new_note(path: Path, content: str, dry_run: bool = False) -> None:
    if dry_run:
        return
    if path.exists():
        raise CollisionError(f"Target note already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        if path.exists():
            raise CollisionError(f"Target note appeared during write: {path}")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MissingPathError(f"Manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid manifest JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("Manifest must be a JSON object")
    return data


def _manifest_batches(data: dict[str, Any]) -> list[dict[str, Any]]:
    if "batches" in data:
        batches = data["batches"]
        if not isinstance(batches, list):
            raise ValidationError("manifest.batches must be a list")
        return batches
    return [data]


def _validate_note_item(item: Any) -> dict[str, str]:
    if not isinstance(item, dict):
        raise ValidationError("Each manifest note must be an object")
    required = ("taxonomy", "title", "content_path")
    missing = [field for field in required if not item.get(field)]
    if missing:
        raise ValidationError(f"Manifest note missing fields: {', '.join(missing)}")
    return {field: str(item[field]) for field in required}


def plan_publish_batch(data: dict[str, Any], config: MedConfig, collision: str) -> list[dict[str, Any]]:
    planned_batches: list[dict[str, Any]] = []
    reserved: set[Path] = set()
    for batch in _manifest_batches(data):
        if not isinstance(batch, dict):
            raise ValidationError("Each manifest batch must be an object")
        raw_file_value = batch.get("raw_file")
        notes_value = batch.get("notes")
        if not raw_file_value:
            raise ValidationError("Manifest batch missing raw_file")
        if not isinstance(notes_value, list) or not notes_value:
            raise ValidationError("Manifest batch must contain at least one note")
        raw_file = _path(str(raw_file_value))
        if not raw_file.exists():
            raise MissingPathError(f"Raw file not found: {raw_file}")
        notes: list[dict[str, Any]] = []
        for raw_item in notes_value:
            item = _validate_note_item(raw_item)
            content_path = _path(item["content_path"])
            if not content_path.exists():
                raise MissingPathError(f"Content file not found: {content_path}")
            target = target_for_note(config.wiki_dir, item["taxonomy"], item["title"])
            target = resolve_collision(target, collision, reserved)
            reserved.add(target)
            notes.append(
                {
                    "taxonomy": "/".join(normalize_taxonomy(item["taxonomy"])),
                    "title": item["title"],
                    "content_path": str(content_path),
                    "target_path": str(target),
                }
            )
        planned_batches.append({"raw_file": str(raw_file), "notes": notes})
    return planned_batches


def publish_batch(
    manifest: Path,
    config: MedConfig,
    collision: str = "abort",
    dry_run: bool = False,
    backup: bool = False,
) -> dict[str, Any]:
    data = _load_manifest(manifest)
    plan = plan_publish_batch(data, config, collision)
    created: list[str] = []
    raw_updates: list[dict[str, Any]] = []
    if dry_run:
        return {
            "dry_run": True,
            "backup": backup,
            "manifest": str(manifest),
            "planned_batches": plan,
            "created": [],
            "raw_updates": [],
        }

    try:
        for batch in plan:
            for item in batch["notes"]:
                content = Path(item["content_path"]).read_text(encoding="utf-8")
                write_new_note(Path(item["target_path"]), content)
                created.append(item["target_path"])
        for batch in plan:
            raw_updates.append(
                mutate_raw_frontmatter(
                    Path(batch["raw_file"]),
                    {"status": "processado", "processed_at": _now_iso()},
                    dry_run=False,
                    backup=backup,
                )
            )
    except Exception as exc:
        raise MedOpsError(
            "Batch publish failed before all raw files were marked processed. "
            f"Created notes before failure: {created}. Error: {exc}"
        ) from exc

    return {
        "dry_run": False,
        "backup": backup,
        "manifest": str(manifest),
        "created": created,
        "raw_updates": raw_updates,
        "created_count": len(created),
        "processed_raw_count": len(raw_updates),
    }


def stage_note(manifest: Path, raw_file: Path, taxonomy: str, title: str, content_path: Path, dry_run: bool = False) -> dict[str, Any]:
    normalize_taxonomy(taxonomy)
    safe_title(title)
    if not raw_file.exists():
        raise MissingPathError(f"Raw file not found: {raw_file}")
    if not content_path.exists():
        raise MissingPathError(f"Content file not found: {content_path}")
    if manifest.exists():
        data = _load_manifest(manifest)
    else:
        data = {"raw_file": str(raw_file), "notes": []}
    if data.get("raw_file") and str(_path(str(data["raw_file"]))) != str(raw_file):
        raise ValidationError("Manifest already belongs to a different raw_file")
    notes = data.setdefault("notes", [])
    if not isinstance(notes, list):
        raise ValidationError("manifest.notes must be a list")
    item = {"taxonomy": taxonomy, "title": title, "content_path": str(content_path)}
    if not dry_run:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        data["raw_file"] = str(raw_file)
        notes.append(item)
        atomic_write_text(manifest, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {"manifest": str(manifest), "dry_run": dry_run, "staged": item, "note_count": len(notes) + (1 if dry_run else 0)}


def run_linker(config: MedConfig, dry_run: bool = False) -> dict[str, Any]:
    linker = config.linker_path
    if dry_run:
        return {"dry_run": True, "linker_path": str(linker), "would_run": linker.exists()}
    if not linker.exists():
        raise MissingPathError(f"Semantic linker not found: {linker}")
    env = os.environ.copy()
    env.setdefault("MED_WIKI_DIR", str(config.wiki_dir))
    env.setdefault("MED_CATALOG_PATH", str(config.catalog_path))
    command = [
        sys.executable,
        str(linker),
        "--wiki-dir",
        str(config.wiki_dir),
        "--catalog",
        str(config.catalog_path),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
    return {
        "dry_run": False,
        "linker_path": str(linker),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def validate_config(config: MedConfig) -> dict[str, Any]:
    return {
        "raw_dir": str(config.raw_dir),
        "raw_dir_exists": config.raw_dir.exists(),
        "wiki_dir": str(config.wiki_dir),
        "wiki_dir_exists": config.wiki_dir.exists(),
        "catalog_path": str(config.catalog_path),
        "catalog_path_exists": config.catalog_path.exists(),
        "linker_path": str(config.linker_path),
        "linker_path_exists": config.linker_path.exists(),
    }


def _json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Optional config.toml. Reads [chat_processor].")
    parser.add_argument("--raw-dir", help="Override Chats_Raw directory.")
    parser.add_argument("--wiki-dir", help="Override Wiki_Medicina directory.")
    parser.add_argument("--linker-path", help="Override med-auto-linker script path.")
    parser.add_argument("--catalog-path", help="Override CATALOGO_WIKI.json path.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Medical Notes Workbench deterministic chat-processing operations.")
    _add_common(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    pending = sub.add_parser("list-pending", help="List raw chats with no status or status=pendente.")
    _add_common(pending)
    triados = sub.add_parser("list-triados", help="List raw chats with status=triado and tipo=medicina.")
    _add_common(triados)

    triage = sub.add_parser("triage", help="Mark one raw chat as triaged.")
    _add_common(triage)
    triage.add_argument("--raw-file", required=True)
    triage.add_argument("--tipo", default="medicina")
    triage.add_argument("--titulo", required=True)
    triage.add_argument("--fonte-id", default="")
    triage.add_argument("--dry-run", action="store_true")
    triage.add_argument("--backup", action="store_true", help="Create a .bak file before mutating raw chat frontmatter.")

    discard = sub.add_parser("discard", help="Mark one raw chat as discarded.")
    _add_common(discard)
    discard.add_argument("--raw-file", required=True)
    discard.add_argument("--reason", required=True)
    discard.add_argument("--dry-run", action="store_true")
    discard.add_argument("--backup", action="store_true", help="Create a .bak file before mutating raw chat frontmatter.")

    stage = sub.add_parser("stage-note", help="Append a generated note to a manifest.")
    _add_common(stage)
    stage.add_argument("--manifest", required=True)
    stage.add_argument("--raw-file", required=True)
    stage.add_argument("--taxonomy", required=True)
    stage.add_argument("--title", required=True)
    stage.add_argument("--content", required=True)
    stage.add_argument("--dry-run", action="store_true")

    publish = sub.add_parser("publish-batch", help="Publish all notes from a manifest, then mark raw files processed.")
    _add_common(publish)
    publish.add_argument("--manifest", required=True)
    publish.add_argument("--dry-run", action="store_true")
    publish.add_argument("--backup", action="store_true", help="Create .bak files before mutating raw chat frontmatter.")
    publish.add_argument("--collision", choices=("abort", "suffix"), default="abort")

    commit = sub.add_parser("commit-batch", help="Compatibility alias for publish-batch.")
    _add_common(commit)
    commit.add_argument("--manifest", required=True)
    commit.add_argument("--dry-run", action="store_true")
    commit.add_argument("--backup", action="store_true", help="Create .bak files before mutating raw chat frontmatter.")
    commit.add_argument("--collision", choices=("abort", "suffix"), default="abort")

    linker = sub.add_parser("run-linker", help="Run configured semantic linker once.")
    _add_common(linker)
    linker.add_argument("--dry-run", action="store_true")

    validate = sub.add_parser("validate", help="Print resolved paths and existence checks.")
    _add_common(validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = resolve_config(args)
        if args.command == "list-pending":
            _json(list_by_status(config.raw_dir, "pending"))
        elif args.command == "list-triados":
            _json(list_by_status(config.raw_dir, "triados"))
        elif args.command == "triage":
            _json(
                mutate_raw_frontmatter(
                    _path(args.raw_file),
                    {
                        "tipo": args.tipo,
                        "status": "triado",
                        "data_importacao": date.today().isoformat(),
                        "fonte_id": args.fonte_id,
                        "titulo_triagem": args.titulo,
                    },
                    dry_run=args.dry_run,
                    backup=getattr(args, "backup", False),
                )
            )
        elif args.command == "discard":
            _json(
                mutate_raw_frontmatter(
                    _path(args.raw_file),
                    {"status": "descartado", "discard_reason": args.reason, "discarded_at": _now_iso()},
                    dry_run=args.dry_run,
                    backup=getattr(args, "backup", False),
                )
            )
        elif args.command == "stage-note":
            _json(stage_note(_path(args.manifest), _path(args.raw_file), args.taxonomy, args.title, _path(args.content), args.dry_run))
        elif args.command in {"publish-batch", "commit-batch"}:
            _json(
                publish_batch(
                    _path(args.manifest),
                    config,
                    collision=args.collision,
                    dry_run=args.dry_run,
                    backup=args.backup,
                )
            )
        elif args.command == "run-linker":
            result = run_linker(config, dry_run=args.dry_run)
            _json(result)
            if not result.get("dry_run") and result.get("returncode", 0) != 0:
                return EXIT_LINKER
        elif args.command == "validate":
            _json(validate_config(config))
        else:  # pragma: no cover - argparse prevents this
            parser.print_help()
            return EXIT_USAGE
        return EXIT_OK
    except MedOpsError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
