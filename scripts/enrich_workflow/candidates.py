"""Image candidate search and thumbnail preparation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from enricher.download import DownloadError, download as download_image
from enricher.sources import ImageCandidate, SourceQuotaExceeded, web_search, wikimedia

from enrich_workflow.models import CandidateReport
from enrich_workflow.utils import _log

_SOURCE_REGISTRY: dict[str, Any] = {
    wikimedia.NAME: wikimedia,
    web_search.NAME: web_search,
}


def gather_candidates(
    anchor: dict,
    *,
    sources_enabled: list[str],
    top_k_per_source: int,
    max_total: int,
    preferred_language: str = "any",
) -> list[ImageCandidate]:
    return gather_candidate_report(
        anchor,
        sources_enabled=sources_enabled,
        top_k_per_source=top_k_per_source,
        max_total=max_total,
        preferred_language=preferred_language,
    ).candidates


def gather_candidate_report(
    anchor: dict,
    *,
    sources_enabled: list[str],
    top_k_per_source: int,
    max_total: int,
    preferred_language: str = "any",
) -> CandidateReport:
    seen_urls: set[str] = set()
    out: list[ImageCandidate] = []
    counts_by_source = {source_name: 0 for source_name in sources_enabled}
    failed_queries: list[tuple[str, str, str]] = []
    for source_name in sources_enabled:
        adapter = _SOURCE_REGISTRY.get(source_name)
        if adapter is None:
            failed_queries.append((source_name, "(adapter)", "fonte desconhecida"))
            continue
        for query in anchor["search_queries"]:
            try:
                # `language` só é aceito por adapters que suportam (web_search).
                # Outros (wikimedia) ignoram via **kwargs incompatível, então
                # tentamos passar e caímos no fallback se não aceitar.
                kwargs = {"top_k": top_k_per_source}
                if "language" in adapter.search.__code__.co_varnames:
                    kwargs["language"] = preferred_language
                cs = adapter.search(query, anchor["visual_type"], **kwargs)
            except SourceQuotaExceeded:
                raise
            except Exception as e:
                failed_queries.append((source_name, query, str(e)))
                continue
            for c in cs:
                if c.image_url in seen_urls:
                    continue
                seen_urls.add(c.image_url)
                out.append(c)
                counts_by_source[source_name] = (
                    counts_by_source.get(source_name, 0) + 1
                )
                if len(out) >= max_total:
                    return CandidateReport(
                        candidates=out,
                        counts_by_source=counts_by_source,
                        failed_queries=failed_queries,
                        capped=True,
                    )
    return CandidateReport(
        candidates=out,
        counts_by_source=counts_by_source,
        failed_queries=failed_queries,
    )


def _candidate_image_urls(c: ImageCandidate) -> list[str]:
    urls = [c.image_url]
    thumbnail_url = getattr(c, "thumbnail_url", None)
    if thumbnail_url and thumbnail_url not in urls:
        urls.append(thumbnail_url)
    return urls


def fetch_thumbs(
    candidates: list[ImageCandidate],
    *,
    tmp_dir: Path,
    user_agent: str | None = None,
) -> list[Path | None]:
    """Baixa thumbnails (256px) sem usar cache do projeto. Falha por candidata
    é tolerada — devolve None na posição correspondente."""
    out: list[Path | None] = []
    for i, c in enumerate(candidates):
        thumb_path = None
        last_error = None
        for url in _candidate_image_urls(c):
            try:
                res = download_image(
                    url,
                    vault_dir=tmp_dir,
                    max_dim=256,
                    webp_min_savings_pct=0,  # sempre WebP nos thumbs
                    cache=None,
                    source=c.source,
                    source_url=c.source_url,
                    user_agent=user_agent,
                )
                thumb_path = Path(res["path"])
                break
            except DownloadError as e:
                last_error = e
        if thumb_path is None:
            _log(f"    [warn] thumb #{i} falhou: {last_error}", err=True)
        out.append(thumb_path)
    return out
