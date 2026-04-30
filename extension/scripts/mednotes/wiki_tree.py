#!/usr/bin/env python3
"""Emit the current Wiki_Medicina folder tree with canonical taxonomy context."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import med_ops  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print Wiki_Medicina taxonomy context as JSON.")
    parser.add_argument("--config", help="Optional config.toml. Reads [chat_processor].")
    parser.add_argument("--raw-dir", help="Override Chats_Raw directory.")
    parser.add_argument("--wiki-dir", help="Override Wiki_Medicina directory.")
    parser.add_argument("--linker-path", help="Override med-auto-linker script path.")
    parser.add_argument("--catalog-path", help="Override CATALOGO_WIKI.json path.")
    parser.add_argument("--max-depth", type=int, default=4, help="Current tree depth; 0 means all depths.")
    parser.add_argument("--audit", action="store_true", help="Include dry-run audit against the canonical taxonomy.")
    return parser


def taxonomy_context(args: argparse.Namespace) -> dict[str, Any]:
    config = med_ops.resolve_config(args)
    payload = {
        "wiki_dir": str(config.wiki_dir),
        "canonical_taxonomy": med_ops.canonical_taxonomy_tree(),
        "current_tree": med_ops.taxonomy_tree(config.wiki_dir, max_depth=args.max_depth),
    }
    if args.audit:
        payload["audit"] = med_ops.taxonomy_audit(config.wiki_dir)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        print(json.dumps(taxonomy_context(args), ensure_ascii=False, indent=2))
        return med_ops.EXIT_OK
    except med_ops.MedOpsError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
