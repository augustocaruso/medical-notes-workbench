#!/usr/bin/env python3
"""Local idempotency index for /flashcards candidate cards.

This script does not talk to Anki. It owns a deterministic local index used by
the Gemini command before/after Anki MCP writes:

- `check` filters candidate cards into new vs duplicate.
- `record` stores cards that Anki accepted.
- `summary` reports the current index.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


SCHEMA = "medical-notes-workbench.flashcards-index.v1"
CHECK_SCHEMA = "medical-notes-workbench.flashcards-index-check.v1"
SOURCE_STATUS_SCHEMA = "medical-notes-workbench.flashcards-source-status.v1"
DEFAULT_INDEX = "~/.gemini/medical-notes-workbench/FLASHCARDS_INDEX.json"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_IO = 5


class IndexErrorWithCode(Exception):
    exit_code = EXIT_IO


class UsageError(IndexErrorWithCode):
    exit_code = EXIT_USAGE


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser()


def _index_path(value: str | None = None) -> Path:
    return _path(value or os.getenv("MED_FLASHCARDS_INDEX") or DEFAULT_INDEX)


def _read_json(path: str | Path) -> Any:
    if str(path) == "-":
        return json.loads(sys.stdin.read())
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "version": 1, "updated_at": None, "cards": {}, "sources": {}}
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise UsageError(f"Unsupported flashcards index schema in {path}")
    data.setdefault("cards", {})
    data.setdefault("sources", {})
    return data


def _json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _field_from(card: dict[str, Any], names: list[str]) -> str:
    fields = card.get("fields") if isinstance(card.get("fields"), dict) else {}
    casefold_fields = {str(key).casefold(): value for key, value in fields.items()}
    casefold_card = {str(key).casefold(): value for key, value in card.items()}
    for name in names:
        if name in fields:
            return _clean_text(fields[name])
        lowered = name.casefold()
        if lowered in casefold_fields:
            return _clean_text(casefold_fields[lowered])
        if lowered in casefold_card:
            return _clean_text(casefold_card[lowered])
    return ""


def normalize_card(card: dict[str, Any]) -> dict[str, str]:
    source_path = str(card.get("source_path") or card.get("source") or card.get("path") or "")
    source_relative_path = str(card.get("source_relative_path") or card.get("vault_relative_path") or "")
    source_sha = str(
        card.get("source_content_sha256")
        or card.get("content_sha256")
        or card.get("note_sha256")
        or ""
    )
    return {
        "source_path": source_path,
        "source_relative_path": source_relative_path,
        "source_content_sha256": source_sha,
        "source_excerpt": _clean_text(card.get("source_excerpt") or card.get("trecho") or ""),
        "deck": _clean_text(card.get("deck")),
        "note_model": _clean_text(card.get("note_model") or card.get("model")),
        "front": _field_from(card, ["Frente", "Front", "front", "pergunta"]),
        "back": _field_from(card, ["Verso", "Back", "back", "resposta"]),
        "extra": _field_from(card, ["Verso Extra", "Extra", "extra", "verso_extra"]),
        "obsidian": _field_from(card, ["Obsidian", "obsidian"]),
    }


def card_hash(card: dict[str, Any]) -> str:
    normalized = normalize_card(card)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _source_notes(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    manifest = payload.get("source_manifest") if isinstance(payload.get("source_manifest"), dict) else payload
    notes = manifest.get("notes") if isinstance(manifest, dict) else None
    if not isinstance(notes, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for note in notes:
        if not isinstance(note, dict):
            continue
        path = str(note.get("path") or "")
        if path:
            result[path] = note
    return result


def _candidate_cards(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        cards = payload
    elif isinstance(payload, dict):
        cards = (
            payload.get("candidate_cards")
            or payload.get("accepted_cards")
            or payload.get("new_cards")
            or payload.get("cards")
            or []
        )
    else:
        raise UsageError("Expected candidate cards JSON object or list")
    if not isinstance(cards, list):
        raise UsageError("Expected candidate_cards/cards to be a list")

    source_notes = _source_notes(payload)
    normalized_cards: list[dict[str, Any]] = []
    for raw_card in cards:
        if not isinstance(raw_card, dict):
            raise UsageError("Each candidate card must be an object")
        card = dict(raw_card)
        source_path = str(card.get("source_path") or card.get("source") or card.get("path") or "")
        source_note = source_notes.get(source_path)
        if source_note:
            card.setdefault("source_content_sha256", source_note.get("content_sha256"))
            card.setdefault("source_relative_path", source_note.get("vault_relative_path"))
            card.setdefault("deck", source_note.get("deck"))
            fields = card.setdefault("fields", {})
            if isinstance(fields, dict):
                fields.setdefault("Obsidian", source_note.get("deeplink"))
        normalized_cards.append(card)
    return normalized_cards


def check_candidates(payload: Any, index: dict[str, Any]) -> dict[str, Any]:
    known = index.get("cards", {})
    new_cards: list[dict[str, Any]] = []
    duplicate_cards: list[dict[str, Any]] = []
    for card in _candidate_cards(payload):
        digest = str(card.get("card_hash") or card_hash(card))
        record = {**card, "card_hash": digest}
        if digest in known:
            duplicate_cards.append({**record, "duplicate_of": digest})
        else:
            new_cards.append(record)
    return {
        "schema": CHECK_SCHEMA,
        "summary": {
            "candidate_count": len(new_cards) + len(duplicate_cards),
            "new_count": len(new_cards),
            "duplicate_count": len(duplicate_cards),
        },
        "new_cards": new_cards,
        "duplicate_cards": duplicate_cards,
    }


def record_cards(payload: Any, index: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    cards = _candidate_cards(payload)
    now = _now_iso()
    added = 0
    already_present = 0
    for card in cards:
        digest = str(card.get("card_hash") or card_hash(card))
        normalized = normalize_card(card)
        if digest in index["cards"]:
            already_present += 1
        else:
            added += 1
        index["cards"][digest] = {
            "card_hash": digest,
            "recorded_at": now,
            **normalized,
        }
        source_key = normalized["source_path"] or normalized["source_relative_path"] or "__unknown__"
        source = index["sources"].setdefault(
            source_key,
            {
                "path": normalized["source_path"],
                "vault_relative_path": normalized["source_relative_path"],
                "content_sha256": normalized["source_content_sha256"],
                "card_hashes": [],
                "updated_at": now,
            },
        )
        source["content_sha256"] = normalized["source_content_sha256"]
        source["updated_at"] = now
        if digest not in source["card_hashes"]:
            source["card_hashes"].append(digest)
    index["updated_at"] = now
    return index, {"accepted_count": len(cards), "added_count": added, "already_present_count": already_present}


def source_status(payload: Any, index: dict[str, Any]) -> dict[str, Any]:
    notes = _source_notes(payload)
    records: list[dict[str, Any]] = []
    summary = {"new_count": 0, "unchanged_count": 0, "changed_count": 0}
    sources = index.get("sources", {})

    for path, note in sorted(notes.items()):
        relative = str(note.get("vault_relative_path") or "")
        current_sha = str(note.get("content_sha256") or "")
        existing = sources.get(path) or sources.get(relative)
        if not existing:
            status = "new"
        elif str(existing.get("content_sha256") or "") == current_sha:
            status = "unchanged"
        else:
            status = "changed"
        summary[f"{status}_count"] += 1
        records.append(
            {
                "path": path,
                "vault_relative_path": relative,
                "status": status,
                "current_content_sha256": current_sha,
                "indexed_content_sha256": str(existing.get("content_sha256") or "") if existing else "",
                "indexed_card_count": len(existing.get("card_hashes", [])) if existing else 0,
            }
        )

    return {"schema": SOURCE_STATUS_SCHEMA, "summary": summary, "sources": records}


def _cmd_check(args: argparse.Namespace) -> int:
    path = _index_path(args.index)
    result = check_candidates(_read_json(args.candidates), _load_index(path))
    result["index_path"] = str(path)
    _json(result)
    return EXIT_OK


def _cmd_source_status(args: argparse.Namespace) -> int:
    path = _index_path(args.index)
    result = source_status(_read_json(args.manifest), _load_index(path))
    result["index_path"] = str(path)
    _json(result)
    return EXIT_OK


def _cmd_record(args: argparse.Namespace) -> int:
    path = _index_path(args.index)
    index = _load_index(path)
    updated, summary = record_cards(_read_json(args.accepted), index)
    result = {
        "schema": SCHEMA,
        "index_path": str(path),
        "dry_run": args.dry_run,
        "summary": summary,
    }
    if not args.dry_run:
        _write_json_atomic(path, updated)
    _json(result)
    return EXIT_OK


def _cmd_summary(args: argparse.Namespace) -> int:
    path = _index_path(args.index)
    index = _load_index(path)
    _json(
        {
            "schema": SCHEMA,
            "index_path": str(path),
            "updated_at": index.get("updated_at"),
            "card_count": len(index.get("cards", {})),
            "source_count": len(index.get("sources", {})),
        }
    )
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="split candidate cards into new and duplicate")
    check.add_argument("--candidates", required=True, help="candidate-card JSON file, or '-' for stdin")
    check.add_argument("--index", help=f"index path; default {DEFAULT_INDEX}")
    check.set_defaults(func=_cmd_check)

    status = sub.add_parser("source-status", help="compare source note hashes against the index")
    status.add_argument("--manifest", required=True, help="source manifest JSON file, or '-' for stdin")
    status.add_argument("--index", help=f"index path; default {DEFAULT_INDEX}")
    status.set_defaults(func=_cmd_source_status)

    record = sub.add_parser("record", help="record cards accepted by Anki")
    record.add_argument("--accepted", required=True, help="accepted-card JSON file, or '-' for stdin")
    record.add_argument("--index", help=f"index path; default {DEFAULT_INDEX}")
    record.add_argument("--dry-run", action="store_true", help="report without writing the index")
    record.set_defaults(func=_cmd_record)

    summary = sub.add_parser("summary", help="summarize the local flashcards index")
    summary.add_argument("--index", help=f"index path; default {DEFAULT_INDEX}")
    summary.set_defaults(func=_cmd_summary)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except IndexErrorWithCode as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except (OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_IO


if __name__ == "__main__":
    raise SystemExit(main())
