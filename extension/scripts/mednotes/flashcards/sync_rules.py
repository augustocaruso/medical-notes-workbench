#!/usr/bin/env python3
"""Domain wrapper for syncing the local Anki Twenty Rules copy."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sync_anki_twenty_rules import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

