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
DEFAULT_REQUIRED_FIELDS = ("Frente", "Verso", "Verso Extra", "Obsidian")

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

    return parser


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
