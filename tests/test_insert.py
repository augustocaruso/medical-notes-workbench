from datetime import datetime, timezone
from pathlib import Path

import pytest

from enricher import frontmatter
from enricher.insert import InsertedImage, SectionNotFound, insert_images


FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 4, 27, 12, 34, 56, tzinfo=timezone.utc)
# Chaves arbitrárias da fixture `note_isrs.md`. Provam additive-only: qualquer
# chave preexistente sai intacta após `insert_images`. Schema da nota é livre.
PRE_EXISTING_KEYS = ("chat_id", "title", "url", "exported_at", "model", "source", "tags")


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _img(
    section_path,
    *,
    anchor_id="a1",
    image_filename="abc123.webp",
    concept="recaptação de serotonina",
    source="wikimedia",
    source_url="https://commons.wikimedia.org/wiki/File:SERT.png",
):
    return InsertedImage(
        anchor_id=anchor_id,
        section_path=list(section_path),
        image_filename=image_filename,
        concept=concept,
        source=source,
        source_url=source_url,
    )


def test_insere_em_secao_h2_imediatamente_antes_do_proximo_heading():
    text = _load("note_isrs.md")
    out = insert_images(text, [_img(["Mecanismo"])], now=NOW)
    _, body = frontmatter.read(out)

    embed = "![[abc123.webp]]"
    caption = "*Figura: recaptação de serotonina.* *Fonte: wikimedia — https://commons.wikimedia.org/wiki/File:SERT.png*"

    assert embed in body
    assert caption in body
    # bloco antes da próxima seção
    idx_embed = body.index(embed)
    idx_next = body.index("## Indicações clínicas")
    assert idx_embed < idx_next
    # ainda depois do conteúdo da própria seção
    idx_section = body.index("## Mecanismo")
    idx_paragraph = body.index("A serotonina liberada")
    assert idx_section < idx_paragraph < idx_embed


def test_insere_duas_imagens_na_mesma_secao_preservando_ordem():
    text = _load("note_isrs.md")
    items = [
        _img(["Mecanismo"], anchor_id="a1", image_filename="img1.webp", concept="c1"),
        _img(["Mecanismo"], anchor_id="a2", image_filename="img2.webp", concept="c2", source="openstax", source_url="https://openstax.org/x"),
    ]
    out = insert_images(text, items, now=NOW)
    _, body = frontmatter.read(out)

    assert "![[img1.webp]]" in body
    assert "![[img2.webp]]" in body
    assert body.index("![[img1.webp]]") < body.index("![[img2.webp]]")
    # captions separados por linha em branco
    bloco = body[body.index("![[img1.webp]]") : body.index("## Indicações clínicas")]
    assert "*Figura: c1.*" in bloco
    assert "*Figura: c2.*" in bloco
    # entre o caption 1 e o embed 2 deve haver linha em branco
    seg = bloco[bloco.index("*Figura: c1.*") : bloco.index("![[img2.webp]]")]
    assert "\n\n" in seg


def test_insere_na_ultima_secao_vai_ate_eof():
    text = _load("note_isrs.md")
    out = insert_images(text, [_img(["Indicações clínicas"], concept="ansiedade")], now=NOW)
    _, body = frontmatter.read(out)

    embed_idx = body.index("![[abc123.webp]]")
    assert body.index("## Indicações clínicas") < embed_idx
    assert body.index("Depressão maior") < embed_idx
    # nada depois do embed além de whitespace
    tail = body[body.index("![[abc123.webp]]") :]
    # remove embed e caption, sobra deve ser só whitespace
    assert tail.strip().endswith("*")  # caption termina com '*'
    assert tail.endswith("\n")


def test_path_nested_seleciona_secao_correta():
    text = _load("note_nested.md")
    out = insert_images(
        text,
        [_img(["🤖 Gemini", "Mecanismo"], image_filename="nest.webp", concept="nested")],
        now=NOW,
    )
    _, body = frontmatter.read(out)

    embed = "![[nest.webp]]"
    assert embed in body
    # primeira ocorrência de '### Mecanismo' deve preceder o embed,
    # e o embed deve preceder '### Indicações' (próxima H3 dentro do primeiro 🤖 Gemini)
    primeira_mec = body.index("### Mecanismo")
    indicacoes = body.index("### Indicações")
    embed_idx = body.index(embed)
    assert primeira_mec < embed_idx < indicacoes


def test_path_duplicado_primeira_ocorrencia_vence():
    text = _load("note_nested.md")
    out = insert_images(
        text,
        [_img(["🤖 Gemini", "Mecanismo"], image_filename="dup.webp", concept="dup")],
        now=NOW,
    )
    _, body = frontmatter.read(out)

    # Embed exatamente uma vez (não vai pra segunda ocorrência também).
    assert body.count("![[dup.webp]]") == 1
    # E está antes da segunda heading '## 🤖 Gemini'.
    second_gemini = body.index("Segunda resposta")
    assert body.index("![[dup.webp]]") < second_gemini


def test_secao_setext_h1():
    text = _load("note_nested.md")
    out = insert_images(
        text,
        [_img(["Tópico setext"], image_filename="setext.webp", concept="setext")],
        now=NOW,
    )
    _, body = frontmatter.read(out)

    embed = "![[setext.webp]]"
    assert embed in body
    # tem que estar depois do conteúdo da seção setext
    assert body.index("Conteúdo da seção H1 setext") < body.index(embed)


def test_path_inexistente_levanta_section_not_found():
    text = _load("note_isrs.md")
    with pytest.raises(SectionNotFound) as exc:
        insert_images(text, [_img(["Não existe"])], now=NOW)
    assert "Não existe" in str(exc.value)


def test_frontmatter_patch_agregado_e_ordenado():
    text = _load("note_isrs.md")
    items = [
        _img(["Mecanismo"], image_filename="a.webp", source="wikimedia", source_url="u1"),
        _img(["Mecanismo"], image_filename="b.webp", source="wikimedia", source_url="u2"),
        _img(["Indicações clínicas"], image_filename="c.webp", source="openstax", source_url="u3"),
    ]
    out = insert_images(text, items, now=NOW)
    meta, _ = frontmatter.read(out)

    assert meta["images_enriched"] is True
    assert meta["image_count"] == 3
    # ordem: count desc, depois source asc
    assert meta["image_sources"] == [
        {"source": "wikimedia", "count": 2},
        {"source": "openstax", "count": 1},
    ]
    # timestamp injetado preservado (yaml round-trip pode devolver datetime)
    assert meta["images_enriched_at"] == NOW


def test_chaves_de_export_intactas_apos_insercao():
    text = _load("note_isrs.md")
    meta_before, _ = frontmatter.read(text)
    out = insert_images(text, [_img(["Mecanismo"])], now=NOW)
    meta_after, _ = frontmatter.read(out)
    for k in PRE_EXISTING_KEYS:
        assert meta_after[k] == meta_before[k], f"chave de export {k!r} mudou"


def test_chaves_de_export_aparecem_antes_das_novas():
    text = _load("note_isrs.md")
    out = insert_images(text, [_img(["Mecanismo"])], now=NOW)
    meta_after, _ = frontmatter.read(out)
    keys = list(meta_after.keys())
    last_export_idx = max(keys.index(k) for k in PRE_EXISTING_KEYS)
    first_new_idx = min(
        keys.index(k)
        for k in ("images_enriched", "images_enriched_at", "image_count", "image_sources")
    )
    assert last_export_idx < first_new_idx


def test_funciona_em_nota_didatica_com_schema_arbitrario():
    """Schema-agnóstico: nota didática tem `title`, `topic`, `created_at`
    (não tem `chat_id`/`url`/etc.) e o enricher precisa funcionar igual."""
    text = _load("note_didatic.md")
    meta_before, _ = frontmatter.read(text)
    pre_keys = list(meta_before.keys())

    out = insert_images(
        text,
        [_img(
            ["ISRS (inibidores seletivos da recaptação de serotonina)", "Mecanismo de ação"],
            image_filename="diag.webp",
            concept="SERT",
        )],
        now=NOW,
    )
    meta_after, body_after = frontmatter.read(out)

    # chaves originais intactas e em ordem
    for k in pre_keys:
        assert meta_after[k] == meta_before[k]
    assert list(meta_after.keys())[: len(pre_keys)] == pre_keys
    # bloco inserido na seção certa
    assert "![[diag.webp]]" in body_after
    assert body_after.index("![[diag.webp]]") < body_after.index("## Indicações clínicas")


def test_funciona_em_nota_sem_frontmatter():
    """Enricher precisa rodar mesmo se a nota não tiver YAML algum."""
    text = "# Tópico\n\n## Mecanismo\n\nTexto.\n\n## Outro\n\nMais texto.\n"
    out = insert_images(
        text,
        [_img(["Tópico", "Mecanismo"], image_filename="x.webp", concept="c")],
        now=NOW,
    )
    meta, body = frontmatter.read(out)
    # frontmatter foi criado só com as nossas chaves
    assert meta["images_enriched"] is True
    assert meta["image_count"] == 1
    assert "![[x.webp]]" in body


def test_caption_normaliza_pontuacao_final_do_concept():
    """Concept que termina em '.', '!', '?' não deve gerar caption com '..'."""
    text = _load("note_isrs.md")
    out = insert_images(
        text,
        [_img(["Mecanismo"], concept="recaptação de serotonina.")],
        now=NOW,
    )
    _, body = frontmatter.read(out)
    assert "*Figura: recaptação de serotonina.*" in body
    assert "..*" not in body  # nada de ponto duplo
    assert ".*" in body


def test_items_vazio_devolve_texto_intacto():
    text = _load("note_isrs.md")
    assert insert_images(text, [], now=NOW) == text


def test_nao_quebra_em_secao_intermediaria_com_subsecoes():
    """Inserção em ['🤖 Gemini'] (H2 que contém H3s) deve ir para o fim da
    seção H2 inteira — ou seja, antes do próximo H2."""
    text = _load("note_nested.md")
    out = insert_images(
        text,
        [_img(["🤖 Gemini"], image_filename="topo.webp", concept="topo")],
        now=NOW,
    )
    _, body = frontmatter.read(out)

    embed = "![[topo.webp]]"
    assert embed in body
    # tem que estar depois das subseções H3 do primeiro ## 🤖 Gemini
    primeira_indicacoes = body.index("### Indicações")
    # e antes do próximo ## 🤖 Gemini (segunda ocorrência H2)
    segunda_h2 = body.index("Segunda resposta")
    embed_idx = body.index(embed)
    assert primeira_indicacoes < embed_idx < segunda_h2
