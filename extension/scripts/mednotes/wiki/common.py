"""Shared primitives for deterministic Wiki workflow operations."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_MISSING = 4
EXIT_IO = 5
EXIT_LINKER = 6

MIGRATION_PLAN_SCHEMA = "medical-notes-workbench.taxonomy-migration-plan.v1"
MIGRATION_RECEIPT_SCHEMA = "medical-notes-workbench.taxonomy-migration-receipt.v1"
SUBAGENT_PLAN_SCHEMA = "medical-notes-workbench.subagent-plan.v1"
WIKI_HEALTH_FIX_SCHEMA = "medical-notes-workbench.wiki-health-fix.v1"


class MedOpsError(Exception):
    """Base exception carrying a process exit code."""

    exit_code = EXIT_IO


class ValidationError(MedOpsError):
    exit_code = EXIT_VALIDATION


class MissingPathError(MedOpsError):
    exit_code = EXIT_MISSING


class CollisionError(MedOpsError):
    exit_code = EXIT_VALIDATION


class FileWriteError(MedOpsError):
    """Filesystem write failed after local retry/recovery attempts."""

    exit_code = EXIT_IO


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
