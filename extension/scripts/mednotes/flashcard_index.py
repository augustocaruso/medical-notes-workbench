#!/usr/bin/env python3
"""Compatibility shim for the local flashcards idempotency index.

The implementation lives in `flashcards.index`; keep this public script name
stable for existing docs, commands, and local automation.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from flashcards import index as _impl  # noqa: E402

globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})
main = _impl.main


if __name__ == "__main__":
    raise SystemExit(main())
