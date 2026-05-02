"""Semantic linker and graph-audit orchestration for the Wiki CLI."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from typing import Any

from wiki import graph as wiki_graph
from wiki import linker as wiki_linker
from wiki.common import MissingPathError
from wiki.config import MedConfig


def run_linker(config: MedConfig, dry_run: bool = False) -> dict[str, Any]:
    linker = config.linker_path
    if not linker.exists():
        raise MissingPathError(f"Semantic linker not found: {linker}")
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        returncode = wiki_linker.run(
            config.wiki_dir,
            catalog_path=config.catalog_path,
            dry_run=dry_run,
            json_output=True,
            verify=False,
        )
    stdout_text = stdout.getvalue()
    stderr_text = stderr.getvalue()
    try:
        payload = json.loads(stdout_text) if stdout_text.strip() else {}
    except json.JSONDecodeError:
        payload = {"ok": False, "parse_error": "linker stdout was not JSON"}
    if not isinstance(payload, dict):
        payload = {"ok": False, "parse_error": "linker stdout JSON was not an object"}
    payload.update(
        {
            "dry_run": dry_run,
            "linker_path": str(linker),
            "returncode": returncode,
            "stderr": stderr_text,
        }
    )
    if payload.get("parse_error"):
        payload["stdout"] = stdout_text
    return payload


def graph_audit(config: MedConfig) -> dict[str, Any]:
    return wiki_graph.audit_wiki_graph(config.wiki_dir, catalog_path=config.catalog_path)
