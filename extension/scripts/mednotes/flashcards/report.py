#!/usr/bin/env python3
"""Generate deterministic reports and previews for /flashcards runs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA = "medical-notes-workbench.flashcard-report.v1"
PREVIEW_SCHEMA = "medical-notes-workbench.flashcard-card-preview.v1"
EXIT_OK = 0
EXIT_IO = 5


def _read_json(path: str) -> Any:
    if path == "-":
        return json.loads(sys.stdin.read())
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _cards(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _nested_cards(payload: dict[str, Any], container: str, key: str) -> list[dict[str, Any]]:
    value = payload.get(container)
    if isinstance(value, dict):
        return _cards(value, key)
    return []


def _field(card: dict[str, Any], name: str) -> str:
    fields = card.get("fields") if isinstance(card.get("fields"), dict) else {}
    return str(fields.get(name) or "")


def _preview_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return (
        _cards(payload, "new_cards")
        or _nested_cards(payload, "index_check", "new_cards")
        or _cards(payload, "candidate_cards", "cards")
    )


def build_report(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = payload.get("source_manifest") if isinstance(payload.get("source_manifest"), dict) else {}
    index_check = payload.get("index_check") if isinstance(payload.get("index_check"), dict) else {}
    model_validation = (
        payload.get("model_validation") if isinstance(payload.get("model_validation"), dict) else {}
    )
    accepted_cards = _cards(payload, "accepted_cards", "created_cards")
    duplicate_cards = _cards(index_check, "duplicate_cards") or _cards(payload, "duplicate_cards")
    skipped_notes = _cards(manifest, "skipped_notes") or _cards(payload, "skipped_notes")
    anki_errors = payload.get("anki_errors") if isinstance(payload.get("anki_errors"), list) else []

    processed_sources = sorted(
        {
            str(card.get("source_path") or card.get("source") or "")
            for card in accepted_cards
            if card.get("source_path") or card.get("source")
        }
    )
    model_error = None
    if model_validation and not model_validation.get("ok", False):
        model_error = {
            "required_fields": model_validation.get("required_fields", []),
            "checked_models": model_validation.get("checked_models", []),
        }

    return {
        "schema": SCHEMA,
        "summary": {
            "processed_note_count": len(processed_sources),
            "created_card_count": len(accepted_cards),
            "duplicate_card_count": len(duplicate_cards),
            "skipped_note_count": len(skipped_notes),
            "model_error_count": 1 if model_error else 0,
            "anki_error_count": len(anki_errors),
        },
        "processed_sources": processed_sources,
        "duplicate_cards": duplicate_cards,
        "skipped_notes": skipped_notes,
        "model_error": model_error,
        "anki_errors": anki_errors,
    }


def format_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "Flashcards final report",
        f"- Notas processadas: {summary['processed_note_count']}",
        f"- Cards criados: {summary['created_card_count']}",
        f"- Cards pulados por duplicidade: {summary['duplicate_card_count']}",
        f"- Notas puladas: {summary['skipped_note_count']}",
        f"- Erros de modelo/campos: {summary['model_error_count']}",
        f"- Erros do Anki MCP: {summary['anki_error_count']}",
    ]
    if report["processed_sources"]:
        lines.append("")
        lines.append("Fontes com cards criados:")
        lines.extend(f"- {source}" for source in report["processed_sources"])
    if report["skipped_notes"]:
        lines.append("")
        lines.append("Notas puladas:")
        for note in report["skipped_notes"]:
            label = note.get("vault_relative_path") or note.get("path") or "nota"
            reason = note.get("skip_reason") or "skip"
            lines.append(f"- {label} ({reason})")
    if report["model_error"]:
        lines.append("")
        lines.append("Modelo Anki incompleto:")
        required = ", ".join(report["model_error"].get("required_fields", []))
        lines.append(f"- Campos exigidos: {required}")
    return "\n".join(lines) + "\n"


def build_card_preview(payload: dict[str, Any]) -> dict[str, Any]:
    index_check = payload.get("index_check") if isinstance(payload.get("index_check"), dict) else {}
    cards = _preview_cards(payload)
    duplicate_cards = _cards(payload, "duplicate_cards") or _cards(index_check, "duplicate_cards")
    return {
        "schema": PREVIEW_SCHEMA,
        "summary": {
            "card_count": len(cards),
            "duplicate_card_count": len(duplicate_cards),
        },
        "cards": cards,
        "duplicate_cards": duplicate_cards,
    }


def format_card_preview(preview: dict[str, Any]) -> str:
    summary = preview["summary"]
    lines = [
        "Flashcards preview",
        f"- Cards candidatos para criar: {summary['card_count']}",
        f"- Cards pulados por duplicidade local: {summary['duplicate_card_count']}",
    ]
    for index, card in enumerate(preview["cards"], start=1):
        source = card.get("source_path") or card.get("source") or card.get("source_relative_path") or ""
        deck = card.get("deck") or ""
        model = card.get("note_model") or card.get("model") or ""
        lines.extend(
            [
                "",
                f"Card {index}",
                f"Deck: {deck}",
                f"Modelo: {model}",
            ]
        )
        if source:
            lines.append(f"Fonte: {source}")
        lines.extend(
            [
                f"Frente: {_field(card, 'Frente')}",
                f"Verso: {_field(card, 'Verso')}",
            ]
        )
        extra = _field(card, "Verso Extra")
        if extra:
            lines.append(f"Verso Extra: {extra}")
        obsidian = _field(card, "Obsidian")
        if obsidian:
            lines.append(f"Obsidian: {obsidian}")
    return "\n".join(lines) + "\n"


def _cmd_final(args: argparse.Namespace) -> int:
    payload = _read_json(args.input)
    report = build_report(payload if isinstance(payload, dict) else {})
    if args.json:
        _json(report)
    else:
        print(format_report(report), end="")
    return EXIT_OK


def _cmd_preview_cards(args: argparse.Namespace) -> int:
    payload = _read_json(args.input)
    preview = build_card_preview(payload if isinstance(payload, dict) else {})
    if args.json:
        _json(preview)
    else:
        print(format_card_preview(preview), end="")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    final = sub.add_parser("final", help="format a final /flashcards report")
    final.add_argument("--input", required=True, help="run-result JSON file, or '-' for stdin")
    final.add_argument("--json", action="store_true", help="emit structured JSON")
    final.set_defaults(func=_cmd_final)

    preview = sub.add_parser("preview-cards", help="format candidate cards before Anki writes")
    preview.add_argument("--input", required=True, help="candidate/write-plan JSON file, or '-' for stdin")
    preview.add_argument("--json", action="store_true", help="emit structured JSON")
    preview.set_defaults(func=_cmd_preview_cards)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_IO


if __name__ == "__main__":
    raise SystemExit(main())
