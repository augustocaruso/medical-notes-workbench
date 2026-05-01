#!/usr/bin/env python3
"""Compatibility launcher for the image enrichment orchestrator.

The canonical name is now ``scripts/enrich_notes.py``. Keep this tiny wrapper so
older local habits and tests still reach the same implementation while docs and
extension prompts can use the clearer name.
"""
from __future__ import annotations

import sys

import enrich_notes as _impl

sys.modules[__name__] = _impl


if __name__ == "__main__":
    raise SystemExit(_impl.main())
