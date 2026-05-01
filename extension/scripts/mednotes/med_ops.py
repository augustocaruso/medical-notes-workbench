#!/usr/bin/env python3
"""Compatibility shim for deterministic Wiki workflow operations.

The real CLI lives in ``wiki.cli`` and the stable import surface lives in
``wiki.api``. Keep this file small because commands, hooks and older habits
still call ``med_ops.py`` directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wiki import api as _api  # noqa: E402
from wiki.api import *  # noqa: F403,E402
from wiki.cli import build_parser, main  # noqa: E402

__all__ = [*_api.__all__, "build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
