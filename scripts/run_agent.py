"""Orquestrador end-to-end: chama o toolbox + gemini CLI pra enriquecer uma nota.

Fluxo:
1. Lê a nota e checa se já foi enriquecida (a menos que --force).
2. Lista as seções via `insert.parse_sections` (passa pro gemini como contexto).
3. Pede ao gemini CLI uma lista de âncoras `{section_path, concept, visual_type, search_queries}`.
4. Pra cada âncora: roda `wikimedia.search` + `web_search.search` em série (cada query),
   agrega candidatas, dedupa por `image_url`.
5. Baixa thumbs (256px) das candidatas pra um tmpdir efêmero (sem cache).
6. Pede ao gemini CLI (visual, com thumbs anexadas) qual é a melhor candidata, ou null.
7. Pra cada escolha não-nula: `download` (full size, no cache do projeto) + acumula em lista
   de `InsertedImage`.
8. Aplica `insert_images` no final, gravando a nota in-place.

Uso:
    python scripts/run_agent.py path/da/nota.md [--config config.toml] [--force]

Pré-requisitos no shell:
- ``gemini`` no PATH (ou ajuste ``[gemini].binary`` no config.toml)
- Login OAuth feito (``gemini auth`` ou equivalente)
- Opcional: ``SERPAPI_KEY`` no ambiente pra busca web
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Garante import do enricher mesmo rodando o script direto (sem `pip install -e .`).
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from enricher import frontmatter, insert  # noqa: E402
from enricher.cache import Cache  # noqa: E402
from enricher.config import expand_path, load as load_config  # noqa: E402
from enricher.download import DownloadError, download as download_image  # noqa: E402
from enricher.sources import ImageCandidate, web_search, wikimedia  # noqa: E402


__all__ = ["main", "GeminiError"]


class GeminiError(RuntimeError):
    pass


_SOURCE_REGISTRY: dict[str, Any] = {
    wikimedia.NAME: wikimedia,
    web_search.NAME: web_search,
}


# --- Gemini CLI seam ------------------------------------------------


def _invoke_gemini(cmd: list[str]) -> str:
    """Roda o gemini CLI e devolve stdout. Levanta GeminiError em rc != 0.

    Seam pra teste: monkeypatch isso pra fingir respostas.
    """
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise GeminiError(
            f"gemini CLI falhou (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def call_gemini(
    prompt: str,
    *,
    binary: str,
    model: str | None = None,
    include_dirs: list[Path] | None = None,
    skip_trust: bool = True,
) -> str:
    """Chama o gemini CLI em modo headless. Multimodal via `@arquivo` no
    próprio prompt + `--include-directories` pra dar acesso ao path."""
    cmd: list[str] = [binary]
    if skip_trust:
        cmd.append("--skip-trust")
    if include_dirs:
        for d in include_dirs:
            cmd.extend(["--include-directories", str(d)])
    if model:
        cmd.extend(["-m", model])
    cmd.extend(["-p", prompt])
    return _invoke_gemini(cmd)


def call_gemini_json_with_retry(
    prompt: str,
    parser: Callable[[str], Any],
    *,
    binary: str,
    model: str | None = None,
    include_dirs: list[Path] | None = None,
    label: str,
) -> tuple[Any, str]:
    """Chama o Gemini e dá uma chance de autocorreção quando ele responde
    prose em vez do JSON contratado."""
    raw = call_gemini(
        prompt,
        binary=binary,
        model=model,
        include_dirs=include_dirs,
    )
    try:
        return parser(raw), raw
    except (json.JSONDecodeError, ValueError) as first_error:
        retry_prompt = (
            "Sua resposta anterior para a tarefa abaixo foi inválida: "
            f"{first_error}.\n\n"
            "Responda novamente com APENAS JSON válido, sem comentários, sem Markdown, "
            "sem texto antes ou depois.\n\n"
            "TAREFA ORIGINAL:\n"
            f"{prompt}\n\n"
            "RESPOSTA ANTERIOR INVÁLIDA:\n"
            f"{raw}"
        )
        retry_raw = call_gemini(
            retry_prompt,
            binary=binary,
            model=model,
            include_dirs=include_dirs,
        )
        try:
            return parser(retry_raw), retry_raw
        except (json.JSONDecodeError, ValueError) as retry_error:
            raise ValueError(
                f"{label} inválido após retry: {retry_error}"
            ) from retry_error


# --- Prompts --------------------------------------------------------


_ANCHORS_PROMPT_TEMPLATE = """Você é um curador de imagens médicas para uma nota de estudo.

Leia a NOTA abaixo e devolva até {max_anchors} ÂNCORAS — pontos onde uma figura tornaria o aprendizado mais eficiente.

REGRAS DE SELEÇÃO (importantes):

1. **Prefira seções-folha (sem subseções)** sobre seções com filhos. Se uma seção tem subseções listadas em SECTIONS, escolha a subseção em vez do pai — a inserção vai pro fim do trilho escolhido, e seções com filhos têm o "fim" depois das subseções (posicionamento ruim).

2. **Cada visual_type bem específico**:
   - `diagram`: esquema/fluxograma de mecanismo molecular ou via metabólica
   - `anatomy`: anatomia macro (órgão, sistema, corte)
   - `histology`: lâmina histológica, tecido com coloração
   - `radiology`: imagem radiológica (RX, TC, RM, US)
   - `chart`: gráfico/curva (dose-resposta, sobrevida, ECG)
   - `photo`: foto clínica (lesão, sinal semiológico)

3. **Conceito curto e visual**: o que a figura PRECISA MOSTRAR, não o que a seção fala em geral. Ex: "binding do ISRS ao SERT bloqueando recaptação", não "mecanismo dos ISRS". Termine SEM ponto final.

4. **Queries — siga a regra de IDIOMA abaixo**:
{language_guidance}

5. **Não force âncoras fracas.** Se uma seção é puramente lista de fármacos ou texto sem imagem natural, pule. Melhor 2 âncoras boas que 5 medíocres. Mas também não seja tímido — uma nota didática quase sempre tem >=1 ponto que se beneficia.

Devolva APENAS um JSON válido (sem ```fences), no formato:
[{{"section_path": [...], "concept": "...", "visual_type": "...", "search_queries": ["...", "..."], "anchor_id": "a1"}}]

Lista vazia `[]` se realmente nenhum ponto pede figura.

SECTIONS (paths e níveis — note quais têm filhos):
{sections_json}

NOTA:
{note_text}
"""


_LANGUAGE_GUIDANCE = {
    "pt-br": (
        "   Gere 3 queries: pelo menos **1 em português** (termos médicos canônicos PT-BR, "
        "ex.: \"mecanismo de ação ISRS SERT sinapse\") e **1-2 em inglês** "
        "(ex.: \"SSRI mechanism action SERT\"). Variar as duas línguas amplia "
        "a chance de achar figura com legenda em PT (preferida) sem perder o material em EN."
    ),
    "en": (
        "   Gere 2-3 queries em **inglês**, médicas, canônicas. "
        "Ex.: [\"SSRI mechanism action SERT\", \"selective serotonin reuptake inhibitor binding\"]."
    ),
    "any": (
        "   Gere 2-3 queries em **inglês**, médicas, canônicas (cobertura máxima). "
        "Ex.: [\"SSRI mechanism action SERT\", \"selective serotonin reuptake inhibitor binding\"]."
    ),
}


_LANGUAGE_RERANK_HINT = {
    "pt-br": (
        "\n6. **PREFERÊNCIA DE IDIOMA**: quando 2+ candidatas tiverem qualidade equivalente, "
        "prefira figura com texto em **português** ou **sem texto**. Figura em inglês é "
        "aceitável se claramente superior nos outros critérios."
    ),
    "en": "",
    "any": "",
}


_RERANK_PROMPT_TEMPLATE = """Você é um curador EXIGENTE de imagens médicas. Para a ÂNCORA abaixo, escolha a melhor candidata olhando as miniaturas anexadas — OU recuse todas se nenhuma é boa.

ÂNCORA:
- Conceito (o que a figura precisa mostrar): {concept}
- Tipo visual desejado: {visual_type}
- Queries usadas: {queries}

CANDIDATAS (índice 0-based, miniatura inline via @arquivo):
{candidates_block}

REGRAS DE DECISÃO:

1. **Match temático ESTRITO.** A figura tem que mostrar exatamente o conceito. Se mostra um tópico vizinho (mesmo que mesma molécula/órgão), NÃO É MATCH. Ex: conceito "ISRS bloqueando SERT" — uma figura de "MDMA causando efflux via SERT" é vizinha mas NÃO é match. Devolva `null`.

2. **Tipo visual tem que bater.** Se pediram `diagram`, uma foto de medicamento não serve. Se pediram `radiology`, um esquema desenhado não serve.

3. **Qualidade visual mínima**: legível, sem watermark, sem texto em idioma absurdo, sem mistura de figuras desconexas no mesmo arquivo.

4. **Recusar é melhor que escolher meia-certo.** Uma figura ruim na nota é pior que nenhuma figura — quem estuda fica confuso. Em dúvida, escolha `null`.

5. **Justifique em UMA frase concreta** apontando elemento da figura (ex: "mostra exatamente SSRI ligando ao SERT bloqueando 5HT", ou "a figura é sobre MDMA causando efflux, não bloqueio por ISRS — vizinho mas off-topic").

Devolva APENAS um JSON válido (sem ```fences):
{{"chosen_index": <int ou null>, "reason": "<frase concreta>"}}
"""


def build_anchors_prompt(
    note_text: str,
    sections: list[dict],
    *,
    max_anchors: int,
    preferred_language: str = "any",
) -> str:
    # Anota `has_children`: True se a próxima seção é descendente (level maior).
    annotated = []
    for i, s in enumerate(sections):
        has_children = (
            i + 1 < len(sections) and sections[i + 1]["level"] > s["level"]
        )
        annotated.append(
            {
                "section_path": s["section_path"],
                "level": s["level"],
                "has_children": has_children,
            }
        )
    guidance = _LANGUAGE_GUIDANCE.get(preferred_language.lower(), _LANGUAGE_GUIDANCE["any"])
    return _ANCHORS_PROMPT_TEMPLATE.format(
        max_anchors=max_anchors,
        language_guidance=guidance,
        sections_json=json.dumps(annotated, ensure_ascii=False, indent=2),
        note_text=note_text,
    )


def build_rerank_prompt(
    anchor: dict,
    candidates: list[ImageCandidate],
    *,
    thumb_basenames: list[str | None] | None = None,
    preferred_language: str = "any",
) -> str:
    """``thumb_basenames[i]`` é o nome do arquivo do thumb de ``candidates[i]``,
    referenciável via ``@<basename>`` quando o caller passar a pasta dos thumbs
    em ``--include-directories``. ``None`` na posição = thumb falhou; ainda
    listamos a candidata como texto pra preservar o índice."""
    if thumb_basenames is None:
        thumb_basenames = [None] * len(candidates)
    lines = []
    for i, (c, tb) in enumerate(zip(candidates, thumb_basenames)):
        thumb_ref = f"@{tb}" if tb else "(thumb indisponível)"
        lines.append(
            f"  [{i}] {thumb_ref}\n"
            f"      title={c.title!r} | source={c.source} | "
            f"size={c.width}x{c.height} | license={c.license}\n"
            f"      description: {c.description}\n"
            f"      url: {c.image_url}"
        )
    base = _RERANK_PROMPT_TEMPLATE.format(
        concept=anchor["concept"],
        visual_type=anchor["visual_type"],
        queries=", ".join(anchor.get("search_queries", [])),
        candidates_block="\n".join(lines),
    )
    hint = _LANGUAGE_RERANK_HINT.get(preferred_language.lower(), "")
    if hint:
        # Insere a regra extra antes da instrução final de "Devolva APENAS um JSON".
        base = base.replace(
            "Devolva APENAS um JSON",
            hint + "\n\nDevolva APENAS um JSON",
        )
    return base


# --- Parse de respostas do gemini -----------------------------------


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def _strip_fences(s: str) -> str:
    m = _JSON_FENCE_RE.search(s)
    return m.group(1) if m else s.strip()


def parse_anchors_json(raw: str) -> list[dict]:
    cleaned = _strip_fences(raw)
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError(f"esperava lista de âncoras, recebi {type(data).__name__}")
    out = []
    for i, a in enumerate(data):
        for k in ("section_path", "concept", "visual_type", "search_queries"):
            if k not in a:
                raise ValueError(f"âncora #{i} sem chave obrigatória {k!r}")
        a.setdefault("anchor_id", f"a{i+1}")
        out.append(a)
    return out


def parse_rerank_json(raw: str) -> dict:
    cleaned = _strip_fences(raw)
    data = json.loads(cleaned)
    if "chosen_index" not in data:
        raise ValueError("rerank sem chave 'chosen_index'")
    return data


# --- Helpers de busca + thumb ---------------------------------------


def gather_candidates(
    anchor: dict,
    *,
    sources_enabled: list[str],
    top_k_per_source: int,
    max_total: int,
    preferred_language: str = "any",
) -> list[ImageCandidate]:
    seen_urls: set[str] = set()
    out: list[ImageCandidate] = []
    for source_name in sources_enabled:
        adapter = _SOURCE_REGISTRY.get(source_name)
        if adapter is None:
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
            except Exception as e:
                print(f"  ! source {source_name} falhou na query {query!r}: {e}", file=sys.stderr)
                continue
            for c in cs:
                if c.image_url in seen_urls:
                    continue
                seen_urls.add(c.image_url)
                out.append(c)
                if len(out) >= max_total:
                    return out
    return out


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
        try:
            res = download_image(
                c.image_url,
                vault_dir=tmp_dir,
                max_dim=256,
                webp_min_savings_pct=0,  # sempre WebP nos thumbs
                cache=None,
                source=c.source,
                source_url=c.source_url,
                user_agent=user_agent,
            )
            out.append(Path(res["path"]))
        except DownloadError as e:
            print(f"  ! thumb {i} falhou: {e}", file=sys.stderr)
            out.append(None)
    return out


# --- Main -----------------------------------------------------------


def _resolve_vault(cfg: dict) -> Path | None:
    base = cfg["vault"].get("path") or ""
    if not base:
        return None
    return expand_path(base) / cfg["vault"].get("attachments_subdir", "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_agent",
        description="Orquestrador end-to-end (gemini CLI + enricher toolbox).",
    )
    parser.add_argument("note", type=Path, help="Caminho da nota .md")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-enriquece mesmo se images_enriched já é true.",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    text = args.note.read_text(encoding="utf-8")

    meta, _ = frontmatter.read(text)
    if meta.get("images_enriched") and not args.force:
        print("nota já enriquecida — use --force pra refazer.", file=sys.stderr)
        return 0

    vault = _resolve_vault(cfg)
    if vault is None:
        print("erro: configure [vault].path no config.toml.", file=sys.stderr)
        return 4

    sections = insert.parse_sections(text)
    if not sections:
        print("erro: nota sem headings — nada a enriquecer.", file=sys.stderr)
        return 6

    pref_lang = cfg["enrichment"].get("preferred_language", "any")
    print(
        f"[1/3] gemini decide âncoras (até {cfg['enrichment']['max_anchors_per_note']}, "
        f"idioma preferido: {pref_lang})…"
    )
    anchors_prompt = build_anchors_prompt(
        text,
        sections,
        max_anchors=cfg["enrichment"]["max_anchors_per_note"],
        preferred_language=pref_lang,
    )
    try:
        anchors, raw = call_gemini_json_with_retry(
            anchors_prompt,
            parse_anchors_json,
            binary=cfg["gemini"]["binary"],
            model=cfg["gemini"]["model_anchors"],
            label="âncoras",
        )
    except ValueError as e:
        print(f"erro: gemini devolveu âncoras inválidas: {e}", file=sys.stderr)
        return 7
    print(f"  → {len(anchors)} âncora(s)")
    for a in anchors:
        print(f"    • {a['concept']} @ {' > '.join(a['section_path'])}")

    inserted: list[insert.InsertedImage] = []

    print(f"[2/3] busca + rerank por âncora…")
    cache_path = expand_path(cfg["cache"]["path"])
    with Cache(cache_path) as cache, tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for anchor in anchors:
            print(f"  ◆ {anchor['concept']}")
            candidates = gather_candidates(
                anchor,
                sources_enabled=cfg["sources"]["enabled"],
                top_k_per_source=cfg["sources"]["top_k_per_source"],
                max_total=cfg["gemini"]["max_candidates_per_anchor"],
                preferred_language=pref_lang,
            )
            if not candidates:
                print("    sem candidatas, pulo.")
                continue
            print(f"    {len(candidates)} candidata(s); baixando thumbs…")
            thumbs = fetch_thumbs(
                candidates, tmp_dir=tmp_dir, user_agent=cfg["download"]["user_agent"]
            )
            valid_thumbs = [(c, t) for c, t in zip(candidates, thumbs) if t is not None]
            if not valid_thumbs:
                print("    todos os thumbs falharam, pulo.")
                continue
            ranked_candidates = [c for c, _ in valid_thumbs]
            ranked_thumbs = [t for _, t in valid_thumbs]
            thumb_basenames = [t.name for t in ranked_thumbs]

            rerank_prompt = build_rerank_prompt(
                anchor,
                ranked_candidates,
                thumb_basenames=thumb_basenames,
                preferred_language=pref_lang,
            )
            try:
                choice, raw = call_gemini_json_with_retry(
                    rerank_prompt,
                    parse_rerank_json,
                    binary=cfg["gemini"]["binary"],
                    model=cfg["gemini"]["model_rerank"],
                    include_dirs=[tmp_dir],
                    label="rerank",
                )
            except ValueError as e:
                print(f"    ! rerank inválido: {e}; pulo.", file=sys.stderr)
                continue
            idx = choice.get("chosen_index")
            if idx is None:
                print(f"    nenhuma serve ({choice.get('reason', '')[:80]})")
                continue
            if not (0 <= idx < len(ranked_candidates)):
                print(f"    ! chosen_index {idx} fora do range; pulo.", file=sys.stderr)
                continue
            chosen = ranked_candidates[idx]
            print(f"    ✓ escolhida #{idx}: {chosen.title}")

            try:
                dl = download_image(
                    chosen.image_url,
                    vault_dir=vault,
                    max_dim=cfg["enrichment"]["max_image_dimension"],
                    webp_min_savings_pct=cfg["enrichment"]["webp_min_savings_pct"],
                    cache=cache,
                    source=chosen.source,
                    source_url=chosen.source_url,
                    user_agent=cfg["download"]["user_agent"],
                )
            except DownloadError as e:
                print(f"    ! download falhou: {e}; pulo.", file=sys.stderr)
                continue

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

    print(f"[3/3] insere {len(inserted)} bloco(s) na nota…")
    if inserted:
        try:
            new_text = insert.insert_images(text, inserted)
        except insert.SectionNotFound as e:
            print(f"erro: {e}", file=sys.stderr)
            return 8
        args.note.write_text(new_text, encoding="utf-8")
        print(f"  ✓ nota atualizada in-place: {args.note}")
    else:
        print("  (nada inserido)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
