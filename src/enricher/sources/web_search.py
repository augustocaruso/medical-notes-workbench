"""Adapter de busca web genérica via SerpAPI (engine ``google_images``).

Pra cobrir o que Wikimedia/fontes médicas curadas não têm. Pago — usuário
fornece ``SERPAPI_KEY`` no ambiente. Sem a chave, ``search`` devolve ``[]``
silenciosamente (contrato: falha de fonte não derruba o resto do agente).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from enricher.sources import ImageCandidate


NAME = "web_search"

_ENDPOINT = "https://serpapi.com/search.json"


_LANGUAGE_TO_GOOGLE_PARAMS = {
    "pt-br": {"hl": "pt-br", "gl": "br"},
    "en": {"hl": "en", "gl": "us"},
}


def _dotenv_value(name: str, *, start: Path | None = None) -> str | None:
    """Busca `name` em um `.env` simples na árvore acima do CWD.

    Não substitui `python-dotenv`: cobre só `KEY=value`, suficiente para a
    configuração local do projeto sem adicionar dependência de runtime.
    """
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        env_path = d / ".env"
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() != name:
                continue
            value = value.strip()
            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in {'"', "'"}
            ):
                value = value[1:-1]
            return value or None
    return None


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

    Sem ``SERPAPI_KEY`` em env/``.env`` e sem ``api_key`` explícito,
    devolve ``[]``.
    ``visual_type`` é aceito por uniformidade com outros adapters mas não
    é mapeado em facets do SerpAPI.

    ``language`` é mapeado para os params ``hl`` (UI language) e ``gl``
    (geolocation) do Google Images. Aceita ``"pt-br"`` e ``"en"``;
    qualquer outro valor (inclusive ``"any"`` e ``None``) → sem param.
    """
    key = api_key or os.environ.get("SERPAPI_KEY") or _dotenv_value("SERPAPI_KEY")
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
        thumbnail_url = r.get("thumbnail")
        image_url = r.get("original") or thumbnail_url
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
                thumbnail_url=thumbnail_url,
            )
        )
        if len(out) >= top_k:
            break
    return out
