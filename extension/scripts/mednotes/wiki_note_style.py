#!/usr/bin/env python3
"""Compatibility shim for the Wiki_Medicina note style contract.

The implementation lives in `wiki.note_style`; keep this public module name
stable until the final compatibility pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wiki import note_style as _impl  # noqa: E402

__all__ = list(_impl.__all__)
globals().update({name: getattr(_impl, name) for name in __all__})
