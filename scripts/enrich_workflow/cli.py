"""CLI entrypoint for the image enrichment workflow."""
from __future__ import annotations

import argparse
from pathlib import Path

from enricher.config import load as load_config

from enrich_workflow.inputs import _resolve_note_inputs
from enrich_workflow.models import NoteResult, _EXIT_SOURCE_QUOTA
from enrich_workflow.runner import _log_run_header, _print_summary, _process_note, _resolve_vault
from enrich_workflow.utils import _log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="enrich_notes",
        description="Orquestrador end-to-end (gemini CLI + enricher toolbox).",
    )
    parser.add_argument(
        "notes",
        nargs="+",
        type=Path,
        help="Caminho(s) da(s) nota(s) .md",
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-enriquece mesmo se images_enriched já é true.",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    vault = _resolve_vault(cfg)
    if vault is None:
        _log("erro: configure [vault].path no config.toml.", err=True)
        return 4

    notes, input_errors = _resolve_note_inputs(args.notes)
    _log_run_header(
        cfg=cfg,
        config_path=args.config,
        vault=vault,
        notes_count=len(notes),
    )

    results: list[NoteResult] = list(input_errors)
    for result in input_errors:
        _log(f"erro: {result.message}", err=True)
    for index, note in enumerate(notes, start=1):
        if index > 1:
            _log("")
        result = _process_note(
            note,
            cfg=cfg,
            vault=vault,
            force=args.force,
            index=index,
            total=len(notes),
        )
        results.append(result)
        if result.code == _EXIT_SOURCE_QUOTA:
            break

    _print_summary(results)
    for result in results:
        if result.code != 0:
            return result.code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
