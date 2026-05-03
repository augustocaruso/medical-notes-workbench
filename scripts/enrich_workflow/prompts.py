"""Prompt templates and builders for image enrichment."""
from __future__ import annotations

import json

from enricher.sources import ImageCandidate


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
