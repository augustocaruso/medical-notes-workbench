"""End-to-end note enrichment runner."""
from __future__ import annotations

import tempfile
from pathlib import Path

from enricher import frontmatter, insert
from enricher.cache import Cache
from enricher.config import expand_path

from enrich_workflow import candidates as candidate_ops
from enrich_workflow import gemini, parsing, prompts
from enrich_workflow.inputs import _validate_note_path
from enrich_workflow.models import NoteResult, _DEFAULT_GEMINI_TIMEOUT_SECONDS, _EXIT_SOURCE_QUOTA
from enrich_workflow.utils import _format_bytes, _format_list, _log, _section_label, _short


def _resolve_vault(cfg: dict) -> Path | None:
    base = cfg["vault"].get("path") or ""
    if not base:
        return None
    return expand_path(base) / cfg["vault"].get("attachments_subdir", "")


def _log_run_header(
    *,
    cfg: dict,
    config_path: Path | None,
    vault: Path,
    notes_count: int,
) -> None:
    pref_lang = cfg["enrichment"].get("preferred_language", "any")
    gemini_timeout = cfg["gemini"].get(
        "timeout_seconds", _DEFAULT_GEMINI_TIMEOUT_SECONDS
    )
    max_anchors = cfg["enrichment"]["max_anchors_per_note"]
    max_candidates = cfg["gemini"]["max_candidates_per_anchor"]
    max_dim = cfg["enrichment"]["max_image_dimension"]

    _log("medical-notes-workbench / enricher")
    _log(f"Config: {config_path if config_path else '(auto)'}")
    _log(f"Vault: {vault}")
    _log(f"Notas: {notes_count}")
    _log(f"Fontes: {_format_list(cfg['sources']['enabled'])}")
    _log(f"Idioma preferido: {pref_lang}")
    _log(
        "Gemini: "
        f"{cfg['gemini']['binary']} "
        f"(anchors={cfg['gemini']['model_anchors']}, "
        f"rerank={cfg['gemini']['model_rerank']}, "
        f"timeout={gemini_timeout}s)"
    )
    _log(
        "Limites: "
        f"até {max_anchors} âncora(s), "
        f"até {max_candidates} candidata(s) por rerank, "
        f"imagem final <= {max_dim}px"
    )
    _log("")


def _process_note(
    note: Path,
    *,
    cfg: dict,
    vault: Path,
    force: bool,
    index: int,
    total: int,
) -> NoteResult:
    _log(f"[nota {index}/{total}] {note}")

    path_error = _validate_note_path(note)
    if path_error:
        _log(f"erro: {path_error}", err=True)
        return NoteResult(note=note, code=2, status="failed", message=path_error)

    try:
        text = note.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        message = f"não foi possível ler a nota: {e}"
        _log(f"erro: {message}", err=True)
        return NoteResult(note=note, code=2, status="failed", message=message)

    meta, _ = frontmatter.read(text)
    if meta.get("images_enriched") and not force:
        message = "nota já enriquecida - use --force pra refazer."
        _log(message, err=True)
        return NoteResult(note=note, code=0, status="skipped", message=message)

    sections = insert.parse_sections(text)
    if not sections:
        message = "nota sem headings - nada a enriquecer."
        _log(f"erro: {message}", err=True)
        return NoteResult(note=note, code=6, status="failed", message=message)

    pref_lang = cfg["enrichment"].get("preferred_language", "any")
    gemini_timeout = cfg["gemini"].get(
        "timeout_seconds", _DEFAULT_GEMINI_TIMEOUT_SECONDS
    )
    max_anchors = cfg["enrichment"]["max_anchors_per_note"]
    max_candidates = cfg["gemini"]["max_candidates_per_anchor"]

    _log("[1/3] Escolhendo pontos da nota que merecem imagem")
    _log(f"  Seções detectadas: {len(sections)}")
    anchors_prompt = prompts.build_anchors_prompt(
        text,
        sections,
        max_anchors=max_anchors,
        preferred_language=pref_lang,
    )
    try:
        anchors, raw = gemini.call_gemini_json_with_retry(
            anchors_prompt,
            parsing.parse_anchors_json,
            binary=cfg["gemini"]["binary"],
            model=cfg["gemini"]["model_anchors"],
            timeout_seconds=gemini_timeout,
            label="âncoras",
        )
    except (gemini.GeminiError, ValueError) as e:
        _log(f"erro: gemini falhou ao gerar âncoras: {e}", err=True)
        return NoteResult(note=note, code=7, status="failed", message=str(e))
    _log(f"  Âncoras encontradas: {len(anchors)}")
    for i, a in enumerate(anchors, start=1):
        _log(f"  [a{i}] {_short(a['concept'])}")
        _log(f"       seção: {_section_label(a['section_path'])}")
        _log(f"       tipo: {a['visual_type']}")
        _log(f"       queries: {_format_list(a['search_queries'])}")

    inserted: list[insert.InsertedImage] = []

    _log("")
    _log("[2/3] Buscando, baixando miniaturas e ranqueando")
    cache_path = expand_path(cfg["cache"]["path"])
    with Cache(cache_path) as cache, tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for anchor_index, anchor in enumerate(anchors, start=1):
            _log(f"  [a{anchor_index}] {_short(anchor['concept'])}")
            try:
                search_report = candidate_ops.gather_candidate_report(
                    anchor,
                    sources_enabled=cfg["sources"]["enabled"],
                    top_k_per_source=cfg["sources"]["top_k_per_source"],
                    max_total=max_candidates,
                    preferred_language=pref_lang,
                )
            except candidate_ops.SourceQuotaExceeded as e:
                message = (
                    f"{e}. Interrompendo o lote para evitar novas chamadas à API."
                )
                _log(f"erro: {message}", err=True)
                return NoteResult(
                    note=note,
                    code=_EXIT_SOURCE_QUOTA,
                    status="failed",
                    message=message,
                )
            candidates = search_report.candidates
            counts = ", ".join(
                f"{source}={search_report.counts_by_source.get(source, 0)}"
                for source in cfg["sources"]["enabled"]
            )
            cap_note = " (limite atingido)" if search_report.capped else ""
            _log(f"    busca: {counts or '0'}{cap_note}")
            for source, query, error in search_report.failed_queries:
                _log(
                    f"    [warn] {source} falhou em {_short(query, limit=48)!r}: "
                    f"{_short(error, limit=90)}",
                    err=True,
                )
            if not candidates:
                _log("    sem candidatas, pulo.")
                continue
            _log(f"    candidatas únicas: {len(candidates)}")
            _log("    baixando miniaturas...")
            thumbs = candidate_ops.fetch_thumbs(
                candidates, tmp_dir=tmp_dir, user_agent=cfg["download"]["user_agent"]
            )
            valid_thumbs = [(c, t) for c, t in zip(candidates, thumbs) if t is not None]
            failed_thumbs = len(thumbs) - len(valid_thumbs)
            _log(f"    miniaturas: {len(valid_thumbs)} ok, {failed_thumbs} falharam")
            if not valid_thumbs:
                _log("    todos os thumbs falharam, pulo.")
                continue
            ranked_candidates = [c for c, _ in valid_thumbs]
            ranked_thumbs = [t for _, t in valid_thumbs]
            thumb_basenames = [t.name for t in ranked_thumbs]

            _log(
                f"    rerank: chamando {cfg['gemini']['model_rerank']} "
                f"com {len(ranked_candidates)} miniatura(s)"
            )
            rerank_prompt = prompts.build_rerank_prompt(
                anchor,
                ranked_candidates,
                thumb_basenames=thumb_basenames,
                preferred_language=pref_lang,
            )
            try:
                choice, raw = gemini.call_gemini_json_with_retry(
                    rerank_prompt,
                    parsing.parse_rerank_json,
                    binary=cfg["gemini"]["binary"],
                    model=cfg["gemini"]["model_rerank"],
                    include_dirs=[tmp_dir],
                    timeout_seconds=gemini_timeout,
                    label="rerank",
                )
            except (gemini.GeminiError, ValueError) as e:
                _log(f"    [warn] rerank inválido: {e}; pulo.", err=True)
                continue
            idx = choice.get("chosen_index")
            if idx is None:
                reason = _short(choice.get("reason", ""), limit=90)
                _log(f"    nenhuma serve ({reason})")
                continue
            if not (0 <= idx < len(ranked_candidates)):
                _log(f"    [warn] chosen_index {idx} fora do range; pulo.", err=True)
                continue
            chosen = ranked_candidates[idx]
            _log(f"    escolhida: #{idx} {_short(chosen.title)}")
            _log(f"    fonte: {chosen.source} - {_short(chosen.source_url)}")

            dl = None
            last_error = None
            for url in candidate_ops._candidate_image_urls(chosen):
                try:
                    dl = candidate_ops.download_image(
                        url,
                        vault_dir=vault,
                        max_dim=cfg["enrichment"]["max_image_dimension"],
                        webp_min_savings_pct=cfg["enrichment"]["webp_min_savings_pct"],
                        cache=cache,
                        source=chosen.source,
                        source_url=chosen.source_url,
                        user_agent=cfg["download"]["user_agent"],
                    )
                    break
                except candidate_ops.DownloadError as e:
                    last_error = e
            if dl is None:
                _log(f"    [warn] download falhou: {last_error}; pulo.", err=True)
                continue
            cached_label = "cache" if dl.get("cached") else "novo download"
            dims = "x".join(str(dl.get(k, "?")) for k in ("width", "height"))
            _log(
                f"    download: {dl['filename']} ({dims}, "
                f"{_format_bytes(dl.get('bytes'))}, {cached_label})"
            )

            inserted.append(
                insert.InsertedImage(
                    anchor_id=anchor["anchor_id"],
                    section_path=anchor["section_path"],
                    image_filename=dl["filename"],
                    concept=anchor["concept"],
                    source=chosen.source,
                    source_url=chosen.source_url,
                )
            )

    _log("")
    _log("[3/3] Atualizando nota")
    if inserted:
        try:
            new_text = insert.insert_images(text, inserted)
        except insert.SectionNotFound as e:
            _log(f"erro: {e}", err=True)
            return NoteResult(note=note, code=8, status="failed", message=str(e))
        try:
            note.write_text(new_text, encoding="utf-8")
        except OSError as e:
            message = f"não foi possível escrever a nota: {e}"
            _log(f"erro: {message}", err=True)
            return NoteResult(note=note, code=2, status="failed", message=message)
        sources_count: dict[str, int] = {}
        for item in inserted:
            sources_count[item.source] = sources_count.get(item.source, 0) + 1
        sources_summary = ", ".join(
            f"{source}={count}" for source, count in sorted(sources_count.items())
        )
        _log(f"  Inseridos: {len(inserted)} bloco(s)")
        _log(f"  Fontes: {sources_summary}")
        _log(f"  Arquivo: {note}")
        _log("")
        _log("Concluído.")
        return NoteResult(
            note=note,
            code=0,
            status="enriched",
            inserted_count=len(inserted),
            sources_count=sources_count,
        )
    else:
        _log("  Nada inserido.")
        _log("")
        _log("Concluído sem alterar a nota.")
        return NoteResult(note=note, code=0, status="no_insert")


def _print_summary(results: list[NoteResult]) -> None:
    enriched = sum(1 for r in results if r.status == "enriched")
    skipped = sum(1 for r in results if r.status == "skipped")
    no_insert = sum(1 for r in results if r.status == "no_insert")
    failures = [r for r in results if r.code != 0]

    _log("")
    _log("Resumo final")
    _log(f"  Total: {len(results)}")
    _log(f"  Enriquecidas: {enriched}")
    _log(f"  Puladas: {skipped}")
    _log(f"  Sem inserção: {no_insert}")
    _log(f"  Falhas: {len(failures)}")
    for result in failures:
        detail = f" - {result.message}" if result.message else ""
        _log(f"  Falha: {result.note} (rc={result.code}){detail}")
