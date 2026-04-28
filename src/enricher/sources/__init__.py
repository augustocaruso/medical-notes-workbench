"""Adapters de fontes de imagem.

Cada adapter expõe:
- ``NAME``: identificador curto (``"wikimedia"``, ``"openstax"``, ...).
- ``search(query, visual_type, *, top_k=4, client=None) -> list[ImageCandidate]``.

Falha de um adapter não derruba os outros — a etapa de busca chama todos em
paralelo e ignora exceções individuais.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ImageCandidate:
    source: str               # ex: "wikimedia"
    source_url: str           # URL da página descritiva (rastreabilidade)
    image_url: str            # URL para download direto
    title: str
    description: str
    width: Optional[int]
    height: Optional[int]
    license: Optional[str]    # informativo (uso pessoal/fair use)
    score: Optional[float]    # relevância da fonte, opcional


__all__ = ["ImageCandidate"]
