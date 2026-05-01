"""Carrega config.toml ao lado da raiz do projeto (ou caminho explícito)."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


_DEFAULTS: dict[str, Any] = {
    "vault": {"path": "", "attachments_subdir": "attachments/medicina"},
    "enrichment": {
        "max_anchors_per_note": 5,
        "max_image_dimension": 1600,
        "webp_min_savings_pct": 30,
        # Idioma preferido das figuras retornadas. Afeta:
        #  - queries que o gemini gera (pt-br adiciona 1 query em PT)
        #  - params do SerpAPI (hl/gl)
        #  - regra de desempate no rerank (prefere figuras com texto no idioma)
        # Valores: "pt-br", "en", "any" (default; comportamento herdado).
        "preferred_language": "any",
    },
    "sources": {
        "enabled": [
            "wikimedia",
            "openstax",
            "nih_open_i",
            "radiopaedia",
            "pdf_library",
            "web_search",
        ],
        "top_k_per_source": 4,
    },
    # `[gemini]` é consumido pelo orquestrador (`scripts/enrich_notes.py`),
    # não pelo toolbox em si. O enricher core não invoca LLM.
    "gemini": {
        "binary": "gemini",
        "model_anchors": "gemini-2.5-pro",
        "model_rerank": "gemini-2.5-flash",
        "max_candidates_per_anchor": 8,
        "timeout_seconds": 120,
    },
    "download": {
        # User-Agent pra fetch de bytes em `download.py`.
        # Default: UA browser-like (Chrome/macOS) — destrava osmosis,
        # thehealthy.com, e similares com anti-bot básico. Wikimedia também
        # aceita (qualquer browser legítimo passa). Trocar de volta pra UA
        # identificável (`medical-notes-workbench/0.1 (...)`) é mais
        # respeitoso mas perde fontes; veja config.example.toml.
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    },
    "cache": {
        "path": "~/Documents/medical-notes-workbench/cache.db",
        "candidates_ttl_days": 30,
    },
}


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def find_config(start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        candidate = d / "config.toml"
        if candidate.is_file():
            return candidate
    return None


def load(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        path = find_config()
    if path is None:
        return dict(_DEFAULTS)
    with path.open("rb") as f:
        data = tomllib.load(f)
    return _deep_merge(_DEFAULTS, data)


def expand_path(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))
