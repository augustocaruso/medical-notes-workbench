#!/usr/bin/env python3
"""Validate Anki note model fields captured from Anki MCP calls.

The agent still calls `mcp_anki-mcp_modelNames` and
`mcp_anki-mcp_modelFieldNames`. This script validates the collected result in a
small, testable contract before any card write.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA = "medical-notes-workbench.anki-model-validation.v1"
SET_SCHEMA = "medical-notes-workbench.anki-model-set-validation.v1"
DEFAULT_REQUIRED_FIELDS = ("Frente", "Verso", "Verso Extra", "Obsidian")
QA_REQUIRED_FIELDS = ("Frente", "Verso", "Verso Extra", "Obsidian")
CLOZE_REQUIRED_FIELDS = ("Texto", "Verso Extra", "Obsidian")
DEFAULT_QA_MODEL = "Medicina"
DEFAULT_CLOZE_MODEL = "Medicina Cloze"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_IO = 5


class ValidatorError(Exception):
    exit_code = EXIT_IO


class UsageError(ValidatorError):
    exit_code = EXIT_USAGE


class ValidationError(ValidatorError):
    exit_code = EXIT_VALIDATION


def _read_json(path: str) -> Any:
    if path == "-":
        return json.loads(sys.stdin.read())
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _models_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("models"), list):
        models = payload["models"]
    elif isinstance(payload, dict):
        models = [{"name": name, "fields": fields} for name, fields in payload.items()]
    else:
        raise UsageError("Expected JSON object with models list, or {model_name: fields} map")

    normalized: list[dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            raise UsageError("Each model entry must be an object")
        name = str(model.get("name") or "")
        fields = model.get("fields")
        if not name or not isinstance(fields, list):
            raise UsageError("Each model needs a name and fields list")
        normalized.append({"name": name, "fields": [str(field) for field in fields]})
    return normalized


def validate_models(
    payload: Any,
    *,
    required_fields: tuple[str, ...] = DEFAULT_REQUIRED_FIELDS,
    preferred_model: str | None = None,
) -> dict[str, Any]:
    models = _models_from_payload(payload)
    checked: list[dict[str, Any]] = []

    ordered = models
    if preferred_model:
        ordered = sorted(models, key=lambda item: item["name"] != preferred_model)

    for model in ordered:
        fields = set(model["fields"])
        missing = [field for field in required_fields if field not in fields]
        record = {"name": model["name"], "fields": model["fields"], "missing_fields": missing}
        checked.append(record)
        if not missing and (preferred_model is None or model["name"] == preferred_model or not preferred_model):
            return {
                "schema": SCHEMA,
                "ok": True,
                "model": model["name"],
                "fields": model["fields"],
                "required_fields": list(required_fields),
                "checked_models": checked,
            }

    compatible = [record for record in checked if not record["missing_fields"]]
    if compatible and preferred_model:
        chosen = compatible[0]
        return {
            "schema": SCHEMA,
            "ok": True,
            "model": chosen["name"],
            "fields": chosen["fields"],
            "required_fields": list(required_fields),
            "checked_models": checked,
            "warning": f"Preferred model {preferred_model!r} is missing required fields; using {chosen['name']!r}.",
        }

    return {
        "schema": SCHEMA,
        "ok": False,
        "model": None,
        "fields": [],
        "required_fields": list(required_fields),
        "checked_models": checked,
    }


def validate_model_set(
    payload: Any,
    *,
    qa_required_fields: tuple[str, ...] = QA_REQUIRED_FIELDS,
    cloze_required_fields: tuple[str, ...] = CLOZE_REQUIRED_FIELDS,
    preferred_qa_model: str | None = DEFAULT_QA_MODEL,
    preferred_cloze_model: str | None = DEFAULT_CLOZE_MODEL,
) -> dict[str, Any]:
    """Valida o par Q&A + Cloze a partir de um único payload de modelos.

    O payload aceita as mesmas formas que `validate_models`: dict
    `{nome: [campos]}`, ou `{ "models": [{"name": ..., "fields": [...]}] }`.
    """

    qa_result = validate_models(
        payload,
        required_fields=qa_required_fields,
        preferred_model=preferred_qa_model,
    )
    cloze_result = validate_models(
        payload,
        required_fields=cloze_required_fields,
        preferred_model=preferred_cloze_model,
    )
    ok = bool(qa_result.get("ok")) and bool(cloze_result.get("ok"))
    missing_kinds = [
        kind
        for kind, result in (("qa", qa_result), ("cloze", cloze_result))
        if not result.get("ok")
    ]
    return {
        "schema": SET_SCHEMA,
        "ok": ok,
        "missing_kinds": missing_kinds,
        "qa": {
            "model": qa_result.get("model"),
            "fields": qa_result.get("fields", []),
            "required_fields": list(qa_required_fields),
            "ok": bool(qa_result.get("ok")),
            "checked_models": qa_result.get("checked_models", []),
        },
        "cloze": {
            "model": cloze_result.get("model"),
            "fields": cloze_result.get("fields", []),
            "required_fields": list(cloze_required_fields),
            "ok": bool(cloze_result.get("ok")),
            "checked_models": cloze_result.get("checked_models", []),
        },
    }


def _cmd_validate(args: argparse.Namespace) -> int:
    required_fields = tuple(args.required_field or DEFAULT_REQUIRED_FIELDS)
    result = validate_models(
        _read_json(args.models_json),
        required_fields=required_fields,
        preferred_model=args.preferred_model,
    )
    _json(result)
    if not result["ok"]:
        return EXIT_VALIDATION
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate captured model fields")
    validate.add_argument("--models-json", required=True, help="model fields JSON file, or '-' for stdin")
    validate.add_argument("--preferred-model", help="preferred Anki model name")
    validate.add_argument(
        "--required-field",
        action="append",
        default=None,
        help="required field name; repeatable",
    )
    validate.set_defaults(func=_cmd_validate)

    validate_set = sub.add_parser(
        "validate-set",
        help="valida em conjunto os modelos Q&A e Cloze",
    )
    validate_set.add_argument(
        "--models-json", required=True, help="modelos capturados do Anki, ou '-' para stdin"
    )
    validate_set.add_argument("--qa-model", default=DEFAULT_QA_MODEL)
    validate_set.add_argument("--cloze-model", default=DEFAULT_CLOZE_MODEL)
    validate_set.set_defaults(func=_cmd_validate_set)

    return parser


def _cmd_validate_set(args: argparse.Namespace) -> int:
    result = validate_model_set(
        _read_json(args.models_json),
        preferred_qa_model=args.qa_model,
        preferred_cloze_model=args.cloze_model,
    )
    _json(result)
    return EXIT_OK if result["ok"] else EXIT_VALIDATION


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValidatorError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except (OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_IO


if __name__ == "__main__":
    raise SystemExit(main())
