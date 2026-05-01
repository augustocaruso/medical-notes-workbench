"""Semantic linker and graph-audit orchestration used by med_ops."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import wiki_graph
from wiki.common import MissingPathError
from wiki.config import MedConfig


def run_linker(config: MedConfig, dry_run: bool = False) -> dict[str, Any]:
    linker = config.linker_path
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
        "--json",
        "--no-verify",
    ]
    if dry_run:
        command.append("--dry-run")
    result = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"ok": False, "parse_error": "linker stdout was not JSON"}
    if not isinstance(payload, dict):
        payload = {"ok": False, "parse_error": "linker stdout JSON was not an object"}
    payload.update(
        {
            "dry_run": dry_run,
            "linker_path": str(linker),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )
    return payload


def graph_audit(config: MedConfig) -> dict[str, Any]:
    return wiki_graph.audit_wiki_graph(config.wiki_dir, catalog_path=config.catalog_path)
