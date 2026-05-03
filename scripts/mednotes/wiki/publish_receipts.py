"""Dry-run receipts for destructive publish-batch CLI runs."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from wiki.common import ValidationError, _now_iso
from wiki.config import MedConfig, _path, _user_state_dir
from wiki.raw_chats import atomic_write_text

PUBLISH_DRY_RUN_RECEIPTS_SCHEMA = "medical-notes-workbench.publish-dry-run-receipts.v1"
DEFAULT_PUBLISH_DRY_RUN_TTL_SECONDS = 30 * 60


def publish_receipts_path() -> Path:
    override = os.environ.get("MEDNOTES_PUBLISH_RECEIPTS_PATH")
    if override:
        return _path(override)
    return _user_state_dir() / "publish-dry-run-receipts.json"


def publish_receipt_ttl_seconds() -> int:
    value = os.environ.get("MEDNOTES_PUBLISH_DRY_RUN_TTL_SECONDS")
    if not value:
        return DEFAULT_PUBLISH_DRY_RUN_TTL_SECONDS
    try:
        seconds = int(value)
    except ValueError:
        return DEFAULT_PUBLISH_DRY_RUN_TTL_SECONDS
    return min(24 * 60 * 60, max(1, seconds))


def _manifest_key(manifest: Path) -> str:
    try:
        return str(manifest.resolve())
    except OSError:
        return str(manifest)


def _sha256_file(path: Path) -> str:
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValidationError(f"Manifest not found: {path}") from exc
    return hashlib.sha256(data).hexdigest()


def _load_state(path: Path | None = None) -> dict[str, Any]:
    state_path = path or publish_receipts_path()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"schema": PUBLISH_DRY_RUN_RECEIPTS_SCHEMA, "receipts": {}}
    if not isinstance(data, dict):
        return {"schema": PUBLISH_DRY_RUN_RECEIPTS_SCHEMA, "receipts": {}}
    receipts = data.get("receipts")
    if not isinstance(receipts, dict):
        data["receipts"] = {}
    data["schema"] = PUBLISH_DRY_RUN_RECEIPTS_SCHEMA
    return data


def _save_state(state: dict[str, Any], path: Path | None = None) -> None:
    state_path = path or publish_receipts_path()
    state["schema"] = PUBLISH_DRY_RUN_RECEIPTS_SCHEMA
    atomic_write_text(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _signature(
    manifest: Path,
    config: MedConfig,
    *,
    collision: str,
    allow_new_taxonomy_leaf: bool,
    require_coverage: bool,
) -> dict[str, Any]:
    return {
        "manifest": _manifest_key(manifest),
        "manifest_sha256": _sha256_file(manifest),
        "cwd": str(Path.cwd().resolve()),
        "wiki_dir": str(config.wiki_dir),
        "raw_dir": str(config.raw_dir),
        "collision": collision,
        "allow_new_taxonomy_leaf": bool(allow_new_taxonomy_leaf),
        "require_coverage": bool(require_coverage),
    }


def record_publish_dry_run(
    manifest: Path,
    config: MedConfig,
    *,
    collision: str,
    allow_new_taxonomy_leaf: bool,
    require_coverage: bool,
) -> dict[str, Any]:
    state = _load_state()
    now = int(time.time())
    receipt = {
        **_signature(
            manifest,
            config,
            collision=collision,
            allow_new_taxonomy_leaf=allow_new_taxonomy_leaf,
            require_coverage=require_coverage,
        ),
        "dry_run_at": _now_iso(),
        "expires_at": now + publish_receipt_ttl_seconds(),
    }
    state.setdefault("receipts", {})[_manifest_key(manifest)] = receipt
    _save_state(state)
    return receipt


def require_publish_dry_run(
    manifest: Path,
    config: MedConfig,
    *,
    collision: str,
    allow_new_taxonomy_leaf: bool,
    require_coverage: bool,
) -> dict[str, Any]:
    state = _load_state()
    key = _manifest_key(manifest)
    receipt = state.get("receipts", {}).get(key)
    if not isinstance(receipt, dict):
        raise ValidationError("Bloqueado: rode publish-batch --dry-run para este manifest antes do publish real.")

    if int(time.time()) > int(receipt.get("expires_at") or 0):
        raise ValidationError("Bloqueado: o dry-run desse manifest expirou. Rode publish-batch --dry-run novamente.")

    current = _signature(
        manifest,
        config,
        collision=collision,
        allow_new_taxonomy_leaf=allow_new_taxonomy_leaf,
        require_coverage=require_coverage,
    )
    if receipt.get("manifest_sha256") != current["manifest_sha256"]:
        raise ValidationError("Bloqueado: o manifest mudou desde o dry-run. Rode publish-batch --dry-run novamente.")
    for field in ("cwd", "wiki_dir", "raw_dir", "collision", "allow_new_taxonomy_leaf", "require_coverage"):
        if receipt.get(field) != current[field]:
            raise ValidationError(
                "Bloqueado: caminhos ou opcoes de publish mudaram desde o dry-run. "
                "Rode publish-batch --dry-run novamente."
            )
    return receipt


def clear_publish_dry_run(manifest: Path) -> None:
    state = _load_state()
    receipts = state.setdefault("receipts", {})
    if receipts.pop(_manifest_key(manifest), None) is not None:
        _save_state(state)
