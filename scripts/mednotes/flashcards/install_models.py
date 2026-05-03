#!/usr/bin/env python3
"""Compute Anki model install/update payloads from local templates.

Os templates HTML/CSS dos modelos `Medicina` (Q&A) e `Medicina Cloze` vivem em
`extension/knowledge/anki-templates/`. Este script lê esses arquivos e emite
payloads determinísticos que o agente entrega ao Anki MCP:

- `mcp_anki-mcp_createModel` quando o modelo não existe;
- `mcp_anki-mcp_updateModelTemplates` + `mcp_anki-mcp_updateModelStyling` quando
  o modelo existe mas o HTML/CSS divergiu.

O agente continua chamando o MCP; este script só normaliza o que mandar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


SCHEMA = "medical-notes-workbench.flashcard-install-models.v1"
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_IO = 5

DEFAULT_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[3] / "knowledge" / "anki-templates"
)

QA_MODEL_NAME = "Medicina"
QA_FIELDS = ("Frente", "Verso", "Verso Extra", "Obsidian")
CLOZE_MODEL_NAME = "Medicina Cloze"
CLOZE_FIELDS = ("Texto", "Verso Extra", "Obsidian")

QA_CARD_NAME = "Card 1"
CLOZE_CARD_NAME = "Cloze"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _digest(*parts: str) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part.encode("utf-8"))
        hasher.update(b"\x1f")
    return hasher.hexdigest()


def load_templates(templates_dir: Path) -> dict[str, Any]:
    """Lê os arquivos do diretório de templates e devolve as specs dos modelos."""

    css = _read(templates_dir / "style.css")
    qa_front = _read(templates_dir / "qa.front.html")
    qa_back = _read(templates_dir / "qa.back.html")
    cloze_front = _read(templates_dir / "cloze.front.html")
    cloze_back = _read(templates_dir / "cloze.back.html")

    return {
        "qa": {
            "modelName": QA_MODEL_NAME,
            "isCloze": False,
            "inOrderFields": list(QA_FIELDS),
            "css": css,
            "cardTemplates": [
                {
                    "Name": QA_CARD_NAME,
                    "Front": qa_front,
                    "Back": qa_back,
                }
            ],
            "fingerprint": _digest(qa_front, qa_back, css, "qa"),
        },
        "cloze": {
            "modelName": CLOZE_MODEL_NAME,
            "isCloze": True,
            "inOrderFields": list(CLOZE_FIELDS),
            "css": css,
            "cardTemplates": [
                {
                    "Name": CLOZE_CARD_NAME,
                    "Front": cloze_front,
                    "Back": cloze_back,
                }
            ],
            "fingerprint": _digest(cloze_front, cloze_back, css, "cloze"),
        },
    }


def _create_payload(spec: dict[str, Any]) -> dict[str, Any]:
    """Argumentos canônicos para `mcp_anki-mcp_createModel`."""

    return {
        "modelName": spec["modelName"],
        "isCloze": spec["isCloze"],
        "inOrderFields": list(spec["inOrderFields"]),
        "css": spec["css"],
        "cardTemplates": [
            {
                "Name": tpl["Name"],
                "Front": tpl["Front"],
                "Back": tpl["Back"],
            }
            for tpl in spec["cardTemplates"]
        ],
    }


def _update_templates_payload(spec: dict[str, Any]) -> dict[str, Any]:
    """Argumentos para `mcp_anki-mcp_updateModelTemplates`."""

    templates = {tpl["Name"]: {"Front": tpl["Front"], "Back": tpl["Back"]} for tpl in spec["cardTemplates"]}
    return {"model": {"name": spec["modelName"], "templates": templates}}


def _update_styling_payload(spec: dict[str, Any]) -> dict[str, Any]:
    """Argumentos para `mcp_anki-mcp_updateModelStyling`."""

    return {"model": {"name": spec["modelName"], "css": spec["css"]}}


def _existing_model_status(
    spec: dict[str, Any], existing_models: list[str], existing_fields: dict[str, list[str]]
) -> str:
    if spec["modelName"] not in existing_models:
        return "missing"
    fields = existing_fields.get(spec["modelName"])
    if fields is None:
        return "unknown"
    required = list(spec["inOrderFields"])
    if list(fields) != required and not set(required).issubset(set(fields)):
        return "incompatible"
    return "present"


def build_install_plan(
    templates_dir: Path,
    *,
    existing_models: list[str] | None = None,
    existing_fields: dict[str, list[str]] | None = None,
    existing_fingerprints: dict[str, str] | None = None,
) -> dict[str, Any]:
    existing_models = existing_models or []
    existing_fields = existing_fields or {}
    existing_fingerprints = existing_fingerprints or {}
    specs = load_templates(templates_dir)

    actions: list[dict[str, Any]] = []
    statuses: dict[str, Any] = {}
    fingerprints: dict[str, str] = {}

    for kind, spec in specs.items():
        status = _existing_model_status(spec, existing_models, existing_fields)
        fingerprint = spec["fingerprint"]
        fingerprints[spec["modelName"]] = fingerprint
        previous_fingerprint = existing_fingerprints.get(spec["modelName"])
        templates_changed = previous_fingerprint != fingerprint

        if status == "missing":
            actions.append(
                {
                    "kind": kind,
                    "model": spec["modelName"],
                    "operation": "createModel",
                    "tool": "mcp_anki-mcp_createModel",
                    "arguments": _create_payload(spec),
                    "fingerprint": fingerprint,
                }
            )
        elif status == "incompatible":
            actions.append(
                {
                    "kind": kind,
                    "model": spec["modelName"],
                    "operation": "blocked",
                    "reason": (
                        f"Modelo {spec['modelName']!r} existe mas com campos diferentes."
                        " Renomeie ou apague no Anki Desktop antes de rodar /flashcards."
                    ),
                    "expected_fields": list(spec["inOrderFields"]),
                    "actual_fields": list(existing_fields.get(spec["modelName"], [])),
                }
            )
        elif templates_changed:
            actions.append(
                {
                    "kind": kind,
                    "model": spec["modelName"],
                    "operation": "updateModelTemplates",
                    "tool": "mcp_anki-mcp_updateModelTemplates",
                    "arguments": _update_templates_payload(spec),
                    "fingerprint": fingerprint,
                }
            )
            actions.append(
                {
                    "kind": kind,
                    "model": spec["modelName"],
                    "operation": "updateModelStyling",
                    "tool": "mcp_anki-mcp_updateModelStyling",
                    "arguments": _update_styling_payload(spec),
                    "fingerprint": fingerprint,
                }
            )

        statuses[spec["modelName"]] = {
            "kind": kind,
            "status": status,
            "fingerprint": fingerprint,
            "previous_fingerprint": previous_fingerprint,
            "templates_changed": templates_changed,
        }

    blocked = any(action.get("operation") == "blocked" for action in actions)
    return {
        "schema": SCHEMA,
        "templates_dir": str(templates_dir),
        "models": {
            "qa": {
                "name": QA_MODEL_NAME,
                "fields": list(QA_FIELDS),
                "isCloze": False,
            },
            "cloze": {
                "name": CLOZE_MODEL_NAME,
                "fields": list(CLOZE_FIELDS),
                "isCloze": True,
            },
        },
        "statuses": statuses,
        "fingerprints": fingerprints,
        "actions": actions,
        "blocked": blocked,
    }


def _read_json(path: str) -> Any:
    if path == "-":
        return json.loads(sys.stdin.read())
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, data: Any) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    if path == "-":
        print(text)
        return
    Path(path).write_text(text + "\n", encoding="utf-8")


def _normalize_existing(payload: Any) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    """Aceita várias formas que o agente pode passar do Anki MCP."""

    if not isinstance(payload, dict):
        return [], {}, {}
    raw_models = payload.get("models")
    fields_map: dict[str, list[str]] = {}
    if isinstance(raw_models, dict):
        models = list(raw_models.keys())
        for name, fields in raw_models.items():
            if isinstance(fields, list):
                fields_map[str(name)] = [str(field) for field in fields]
    elif isinstance(raw_models, list):
        models = []
        for entry in raw_models:
            if isinstance(entry, str):
                models.append(entry)
            elif isinstance(entry, dict):
                name = str(entry.get("name") or "")
                if not name:
                    continue
                models.append(name)
                fields = entry.get("fields")
                if isinstance(fields, list):
                    fields_map[name] = [str(field) for field in fields]
    else:
        models = []

    fingerprints_raw = payload.get("fingerprints") or payload.get("template_fingerprints") or {}
    fingerprints = {
        str(name): str(value) for name, value in fingerprints_raw.items() if isinstance(value, str)
    }
    return models, fields_map, fingerprints


def _cmd_ensure(args: argparse.Namespace) -> int:
    templates_dir = Path(args.templates_dir or os.getenv("MED_FLASHCARDS_TEMPLATES_DIR") or DEFAULT_TEMPLATES_DIR)
    if not templates_dir.exists():
        print(f"Templates dir não encontrado: {templates_dir}", file=sys.stderr)
        return EXIT_IO

    existing_payload: Any = {}
    if args.existing:
        existing_payload = _read_json(args.existing)
    existing_models, existing_fields, existing_fingerprints = _normalize_existing(existing_payload)

    plan = build_install_plan(
        templates_dir,
        existing_models=existing_models,
        existing_fields=existing_fields,
        existing_fingerprints=existing_fingerprints,
    )
    _write_json(args.output, plan)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ensure = sub.add_parser(
        "ensure",
        help="emite o plano de createModel/updateModel* para os modelos da skill",
    )
    ensure.add_argument(
        "--templates-dir",
        help=f"override do diretório de templates (default: {DEFAULT_TEMPLATES_DIR})",
    )
    ensure.add_argument(
        "--existing",
        help="JSON com o estado atual dos modelos no Anki (modelNames + modelFieldNames + fingerprints opcional); '-' para stdin",
    )
    ensure.add_argument(
        "--output",
        default="-",
        help="arquivo de saída para o plano JSON; '-' para stdout (default)",
    )
    ensure.set_defaults(func=_cmd_ensure)

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
