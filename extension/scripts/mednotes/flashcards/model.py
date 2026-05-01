#!/usr/bin/env python3
"""Domain wrapper for Anki model validation."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from anki_model_validator import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

