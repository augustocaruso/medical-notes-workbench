"""Adapter de busca web genérica via SerpAPI (engine ``google_images``).

Pra cobrir o que Wikimedia/fontes médicas curadas não têm. Pago — usuário
fornece ``SERPAPI_KEY`` no ambiente. Sem a chave, ``search`` devolve ``[]``
silenciosamente (contrato: falha de fonte não derruba o resto do agente).
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from enricher.sources import ImageCandidate


NAME = "web_search"

_ENDPOINT = "https://serpapi.com/search.json"


_LANGUAGE_TO_GOOGLE_PARAMS = {
    "pt-br": {"hl": "pt-br", "gl": "br"},
    "en": {"hl": "en", "gl": "us"},
}


def search(
    query: str,
    visual_type: str,
    *,
    top_k: int = 4,
    client: httpx.Client | None = None,
    api_key: str | None = None,
    language: str | None = None,
) -> list[ImageCandidate]:
    """Busca imagens via SerpAPI (Google Images).

    Sem ``SERPAPI_KEY`` em env e sem ``api_key`` explícito, devolve ``[]``.
    ``visual_type`` é aceito por uniformidade com outros adapters mas não
    é mapeado em facets do SerpAPI.

    ``language`` é mapeado para os params ``hl`` (UI language) e ``gl``
    (geolocation) do Google Images. Aceita ``"pt-br"`` e ``"en"``;
    qualquer outro valor (inclusive ``"any"`` e ``None``) → sem param.
    """
    key = api_key or os.environ.get("SERPAPI_KEY")
    if not key:
        return []

    params: dict[str, str] = {
        "engine": "google_images",
        "q": query,
        "api_key": key,
        "num": str(max(top_k * 2, top_k)),
    }
    lang_params = _LANGUAGE_TO_GOOGLE_PARAMS.get((language or "").lower())
    if lang_params:
        params.update(lang_params)

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=15.0)
    try:
        resp = client.get(_ENDPOINT, params=params)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns_client:
            client.close()

    return _parse(data, top_k=top_k)


def _parse(data: dict[str, Any], *, top_k: int) -> list[ImageCandidate]:
    results = data.get("images_results") or []
    out: list[ImageCandidate] = []
    for r in results:
        image_url = r.get("original") or r.get("thumbnail")
        if not image_url:
            continue
        # `link` é a página onde a imagem aparece; `source` é o domínio.
        source_url = r.get("link") or image_url
        title = r.get("title", "") or ""
        description = r.get("snippet") or r.get("source") or title
        out.append(
            ImageCandidate(
                source=NAME,
                source_url=source_url,
                image_url=image_url,
                title=title,
                description=description,
                width=r.get("original_width"),
                height=r.get("original_height"),
                license=None,  # SerpAPI não devolve licença
                score=None,
            )
        )
        if len(out) >= top_k:
            break
    return out
