"""CLI do enricher — toolbox de subcomandos.

Cada subcomando faz **uma** coisa e devolve **JSON na stdout** (consumível por
agente). Erros vão pra stderr com exit code != 0.

Subcomandos:
- ``sections <nota.md>``: lista headings da nota com ``section_path``, ``level``,
  ``start_line``, ``end_line``.
- ``search <source> --query <q> [--visual-type T] [--top-k N]``: busca candidatas
  via adapter (``wikimedia`` ou ``web_search``).
- ``insert <nota.md> --section P --image F --concept C --source S --source-url U``:
  insere bloco no fim da seção e atualiza frontmatter aditivamente. ``--section``
  é repetível pra paths nested (ex: ``--section "🤖 Gemini" --section Mecanismo``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from enricher import frontmatter, insert
from enricher.cache import Cache
from enricher.config import expand_path, load as load_config
from enricher.download import DownloadError, download as download_image
from enricher.sources import wikimedia, web_search


_SOURCE_REGISTRY: dict[str, Any] = {
    wikimedia.NAME: wikimedia,
    web_search.NAME: web_search,
}


def _emit(obj: Any) -> None:
    """Serializa ``obj`` como JSON na stdout. ``ensure_ascii=False`` pra
    preservar acentos e emojis nas mensagens."""
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2, default=_json_default)
    sys.stdout.write("\n")


def _json_default(o: Any) -> Any:
    # Datetimes (frontmatter) e dataclasses (ImageCandidate).
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(o)
    raise TypeError(f"sem serializador pra {type(o).__name__}")


# --- subcomandos -----------------------------------------------------


def cmd_sections(args: argparse.Namespace) -> int:
    text = args.note.read_text(encoding="utf-8")
    _emit(insert.parse_sections(text))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    source = _SOURCE_REGISTRY.get(args.source)
    if source is None:
        print(
            f"erro: source desconhecida: {args.source!r}. "
            f"disponíveis: {', '.join(sorted(_SOURCE_REGISTRY))}",
            file=sys.stderr,
        )
        return 2
    candidates = source.search(args.query, args.visual_type, top_k=args.top_k)
    _emit([_candidate_to_dict(c) for c in candidates])
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    vault = _resolve_vault(args, cfg)
    if vault is None:
        print(
            "erro: vault_dir não definido. Passe --vault ou configure "
            "[vault].path / [vault].attachments_subdir em config.toml.",
            file=sys.stderr,
        )
        return 4
    cache_path = expand_path(cfg["cache"]["path"])
    try:
        with Cache(cache_path) as cache:
            out = download_image(
                args.url,
                vault_dir=vault,
                cache=cache,
                max_dim=args.max_dim or cfg["enrichment"]["max_image_dimension"],
                webp_min_savings_pct=cfg["enrichment"]["webp_min_savings_pct"],
                source=args.source,
                source_url=args.source_url,
                user_agent=cfg["download"]["user_agent"],
            )
    except DownloadError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 5
    _emit(out)
    return 0


def _resolve_vault(args: argparse.Namespace, cfg: dict) -> Path | None:
    if args.vault:
        return args.vault
    base = cfg["vault"].get("path") or ""
    if not base:
        return None
    return expand_path(base) / cfg["vault"].get("attachments_subdir", "")


def cmd_insert(args: argparse.Namespace) -> int:
    text = args.note.read_text(encoding="utf-8")
    item = insert.InsertedImage(
        anchor_id=args.anchor_id or "manual",
        section_path=args.section,
        image_filename=args.image,
        concept=args.concept,
        source=args.source,
        source_url=args.source_url,
    )
    try:
        new_text = insert.insert_images(text, [item])
    except insert.SectionNotFound as e:
        print(f"erro: {e}", file=sys.stderr)
        return 3
    args.note.write_text(new_text, encoding="utf-8")
    meta, _ = frontmatter.read(new_text)
    _emit(
        {
            "note": str(args.note),
            "inserted": 1,
            "image_count": meta.get("image_count"),
            "image_sources": meta.get("image_sources"),
            "images_enriched_at": meta.get("images_enriched_at"),
        }
    )
    return 0


def _candidate_to_dict(c) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(c)


# --- parser ---------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="enricher",
        description=(
            "Toolbox de primitivas para enriquecer notas médicas com imagens. "
            "Cada subcomando devolve JSON na stdout."
        ),
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "config.toml (default: busca na árvore acima do CWD e depois em "
            "~/.gemini/medical-notes-workbench/config.toml)"
        ),
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    s_sections = sub.add_parser("sections", help="Lista headings da nota.")
    s_sections.add_argument("note", type=Path, help="Caminho da nota .md")
    s_sections.set_defaults(func=cmd_sections)

    s_search = sub.add_parser("search", help="Busca candidatas em uma source.")
    s_search.add_argument(
        "source",
        choices=sorted(_SOURCE_REGISTRY),
        help="Nome do adapter de fonte.",
    )
    s_search.add_argument("--query", required=True, help="Termo de busca.")
    s_search.add_argument(
        "--visual-type",
        default="diagram",
        help="Tipo visual desejado (diagram, histology, radiology...). "
        "Aceito por uniformidade entre adapters.",
    )
    s_search.add_argument("--top-k", type=int, default=4, help="Máximo de candidatas.")
    s_search.set_defaults(func=cmd_search)

    s_download = sub.add_parser(
        "download",
        help="Baixa imagem, valida, redimensiona, dedupe SHA, indexa no cache.",
    )
    s_download.add_argument("url", help="URL direta da imagem.")
    s_download.add_argument(
        "--vault",
        type=Path,
        default=None,
        help="Diretório destino. Default: <[vault].path>/<[vault].attachments_subdir>.",
    )
    s_download.add_argument(
        "--max-dim",
        type=int,
        default=None,
        help="Maior lado em px. Default: [enrichment].max_image_dimension.",
    )
    s_download.add_argument(
        "--source",
        default="unknown",
        help="Identificador da fonte (vai para o cache).",
    )
    s_download.add_argument(
        "--source-url",
        default=None,
        help="URL canônica da página descritiva (rastreabilidade).",
    )
    s_download.set_defaults(func=cmd_download)

    s_insert = sub.add_parser(
        "insert",
        help="Insere bloco de imagem em uma seção da nota e atualiza frontmatter.",
    )
    s_insert.add_argument("note", type=Path, help="Caminho da nota .md (modificada in-place).")
    s_insert.add_argument(
        "--section",
        action="append",
        required=True,
        help="Heading-trail. Repetível: --section H1 --section H2 (do topo pra folha).",
    )
    s_insert.add_argument("--image", required=True, help="Filename do attachment já baixado.")
    s_insert.add_argument("--concept", required=True, help="Conceito da figura (vai no caption).")
    s_insert.add_argument("--source", required=True, help="Identificador da fonte (ex: wikimedia).")
    s_insert.add_argument("--source-url", required=True, help="URL canônica da fonte.")
    s_insert.add_argument("--anchor-id", default=None, help="Opcional, default 'manual'.")
    s_insert.set_defaults(func=cmd_insert)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)
