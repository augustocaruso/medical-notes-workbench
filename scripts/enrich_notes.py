#!/usr/bin/env python3
"""Compatibility facade for the image enrichment orchestrator.

The implementation lives in ``scripts/enrich_workflow/``. Keep this module as
an import-compatible surface for old ``run_agent`` habits and tests.
"""
from __future__ import annotations

import subprocess

from enrich_workflow import candidates as _candidates
from enrich_workflow import gemini as _gemini
from enrich_workflow.candidates import SourceQuotaExceeded, web_search, wikimedia
from enrich_workflow.cli import main as _workflow_main
from enrich_workflow.gemini import GeminiError
from enrich_workflow.inputs import _resolve_note_inputs
from enrich_workflow.models import CandidateReport, NoteResult
from enrich_workflow.parsing import parse_anchors_json, parse_rerank_json
from enrich_workflow.prompts import build_anchors_prompt, build_rerank_prompt

_invoke_gemini = _gemini._invoke_gemini
download_image = _candidates.download_image


def _sync_compat_seams() -> None:
    _gemini._invoke_gemini = _invoke_gemini
    _candidates.download_image = download_image


def call_gemini(*args, **kwargs):
    _sync_compat_seams()
    return _gemini.call_gemini(*args, **kwargs)


def call_gemini_json_with_retry(*args, **kwargs):
    _sync_compat_seams()
    return _gemini.call_gemini_json_with_retry(*args, **kwargs)


def gather_candidates(*args, **kwargs):
    _sync_compat_seams()
    return _candidates.gather_candidates(*args, **kwargs)


def gather_candidate_report(*args, **kwargs):
    _sync_compat_seams()
    return _candidates.gather_candidate_report(*args, **kwargs)


def fetch_thumbs(*args, **kwargs):
    _sync_compat_seams()
    return _candidates.fetch_thumbs(*args, **kwargs)


def main(argv: list[str] | None = None) -> int:
    _sync_compat_seams()
    return _workflow_main(argv)


__all__ = [
    "CandidateReport",
    "GeminiError",
    "NoteResult",
    "SourceQuotaExceeded",
    "_invoke_gemini",
    "_resolve_note_inputs",
    "build_anchors_prompt",
    "build_rerank_prompt",
    "call_gemini",
    "call_gemini_json_with_retry",
    "download_image",
    "fetch_thumbs",
    "gather_candidate_report",
    "gather_candidates",
    "main",
    "parse_anchors_json",
    "parse_rerank_json",
    "subprocess",
    "web_search",
    "wikimedia",
]


if __name__ == "__main__":
    raise SystemExit(main())
