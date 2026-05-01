#!/usr/bin/env python3
"""Prepare and apply deterministic /flashcards write plans.

This script glues together the local contracts around the LLM-owned card
formulation step. It does not call Anki itself; it prepares the payload the
agent should send to Anki MCP and records/report accepted results afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
MEDNOTES_DIR = SCRIPT_DIR.parent
if str(MEDNOTES_DIR) not in sys.path:
    sys.path.insert(0, str(MEDNOTES_DIR))

from flashcards import index as flashcard_index  # noqa: E402
from flashcards import model as anki_model_validator  # noqa: E402
from flashcards import report as flashcard_report  # noqa: E402


PREPARE_SCHEMA = "medical-notes-workbench.flashcard-write-plan.v1"
APPLY_SCHEMA = "medical-notes-workbench.flashcard-apply-result.v1"
EXIT_OK = 0
EXIT_BLOCKED = 3
EXIT_IO = 5


def _read_json(path: str) -> Any:
    if path == "-":
        return json.loads(sys.stdin.read())
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _index_path(value: str | None = None) -> Path:
    return Path(
        os.path.expandvars(
            value or os.getenv("MED_FLASHCARDS_INDEX") or flashcard_index.DEFAULT_INDEX
        )
    ).expanduser()


def _models_payload(payload: dict[str, Any]) -> Any:
    return payload.get("models") or payload.get("model_fields") or payload.get("anki_models") or {}


def _source_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = payload.get("source_manifest")
    return manifest if isinstance(manifest, dict) else {}


def _field(card: dict[str, Any], name: str) -> str:
    fields = card.get("fields") if isinstance(card.get("fields"), dict) else {}
    return str(fields.get(name) or "")


def _anki_note_for(card: dict[str, Any], model_name: str) -> dict[str, Any]:
    return {
        "deckName": card.get("deck"),
        "modelName": card.get("note_model") or model_name,
        "fields": card.get("fields", {}),
        "tags": [],
        "options": {"allowDuplicate": False},
    }


def _find_query_for(card: dict[str, Any]) -> str:
    obsidian = _field(card, "Obsidian")
    front = _field(card, "Frente")
    deck = str(card.get("deck") or "")
    parts = []
    if deck:
        parts.append(f'deck:"{deck}"')
    if obsidian:
        parts.append(f'Obsidian:"{obsidian}"')
    if front:
        parts.append(f'Frente:"{front}"')
    return " ".join(parts)


def prepare_write_plan(payload: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    model_validation = anki_model_validator.validate_models(
        _models_payload(payload),
        preferred_model=payload.get("preferred_model"),
    )
    source_status = flashcard_index.source_status(_source_manifest(payload), index)
    index_check = flashcard_index.check_candidates(payload, index)
    new_cards = index_check["new_cards"] if model_validation["ok"] else []
    model_name = str(model_validation.get("model") or "")

    changed_sources = [
        item for item in source_status["sources"] if item.get("status") == "changed"
    ]
    anki_notes = [_anki_note_for(card, model_name) for card in new_cards]
    find_queries = [
        {"card_hash": card["card_hash"], "query": _find_query_for(card)} for card in new_cards
    ]

    return {
        "schema": PREPARE_SCHEMA,
        "blocked": not model_validation["ok"],
        "requires_reprocess_confirmation": bool(changed_sources),
        "model_validation": model_validation,
        "source_status": source_status,
        "index_check": index_check,
        "changed_sources": changed_sources,
        "anki_find_queries": find_queries,
        "anki_notes": anki_notes,
        "new_cards": new_cards,
        "duplicate_cards": index_check["duplicate_cards"],
        "summary": {
            "candidate_count": index_check["summary"]["candidate_count"],
            "new_count": index_check["summary"]["new_count"] if model_validation["ok"] else 0,
            "duplicate_count": index_check["summary"]["duplicate_count"],
            "changed_source_count": len(changed_sources),
            "anki_note_count": len(anki_notes),
        },
    }


def apply_accepted(payload: dict[str, Any], index: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    updated, record_summary = flashcard_index.record_cards(payload, index)
    report = flashcard_report.build_report(payload)
    return updated, {
        "schema": APPLY_SCHEMA,
        "summary": record_summary,
        "report": report,
    }


def _cmd_prepare(args: argparse.Namespace) -> int:
    payload = _read_json(args.input)
    path = _index_path(args.index)
    plan = prepare_write_plan(payload if isinstance(payload, dict) else {}, flashcard_index._load_index(path))
    plan["index_path"] = str(path)
    _json(plan)
    return EXIT_BLOCKED if plan["blocked"] else EXIT_OK


def _cmd_apply(args: argparse.Namespace) -> int:
    payload = _read_json(args.input)
    path = _index_path(args.index)
    updated, result = apply_accepted(payload if isinstance(payload, dict) else {}, flashcard_index._load_index(path))
    result["index_path"] = str(path)
    result["dry_run"] = args.dry_run
    if not args.dry_run:
        flashcard_index._write_json_atomic(path, updated)
    _json(result)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="prepare an Anki write plan from candidate cards")
    prepare.add_argument("--input", required=True, help="candidate run JSON, or '-' for stdin")
    prepare.add_argument("--index", help=f"index path; default {flashcard_index.DEFAULT_INDEX}")
    prepare.set_defaults(func=_cmd_prepare)

    apply = sub.add_parser("apply", help="record accepted Anki cards and emit final report")
    apply.add_argument("--input", required=True, help="accepted run JSON, or '-' for stdin")
    apply.add_argument("--index", help=f"index path; default {flashcard_index.DEFAULT_INDEX}")
    apply.add_argument("--dry-run", action="store_true", help="report without writing index")
    apply.set_defaults(func=_cmd_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, json.JSONDecodeError, flashcard_index.IndexErrorWithCode) as exc:
        print(str(exc), file=sys.stderr)
        return getattr(exc, "exit_code", EXIT_IO)


if __name__ == "__main__":
    raise SystemExit(main())
