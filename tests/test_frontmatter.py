from pathlib import Path

import pytest

from enricher import frontmatter


FIXTURES = Path(__file__).parent / "fixtures"

# Chaves arbitrárias presentes na fixture `note_isrs.md` — usadas como prova
# de que o enricher NUNCA mexe em chaves preexistentes (princípio additive-only).
# Por acaso são as do gemini-md-export, mas o teste é genérico.
PRE_EXISTING_KEYS = ("chat_id", "title", "url", "exported_at", "model", "source", "tags")


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_read_sem_frontmatter_devolve_dict_vazio():
    text = "# Só conteúdo\n\nSem YAML aqui.\n"
    meta, body = frontmatter.read(text)
    assert meta == {}
    assert body == text


def test_read_extrai_meta_e_body_da_fixture():
    meta, body = frontmatter.read(_load("note_isrs.md"))
    assert meta["chat_id"] == "b8e7c075effe9457"
    assert meta["title"] == "Mecanismo de ação dos ISRS"
    assert "## 🤖 Gemini" in body
    assert not body.startswith("---")


def test_round_trip_preserva_ordem_das_chaves():
    text = _load("note_isrs.md")
    meta, body = frontmatter.read(text)
    original_order = list(meta.keys())
    rewritten = frontmatter.write(meta, body)
    meta2, _ = frontmatter.read(rewritten)
    assert list(meta2.keys()) == original_order


def test_round_trip_preserva_valores_das_chaves_de_export():
    text = _load("note_isrs.md")
    meta, _ = frontmatter.read(text)
    rewritten = frontmatter.write(meta, "")
    meta2, _ = frontmatter.read(rewritten)
    for k in PRE_EXISTING_KEYS:
        assert meta2[k] == meta[k], f"chave {k!r} mudou no round-trip"


def test_update_adiciona_chaves_novas_no_fim_sem_reordenar():
    text = _load("note_isrs.md")
    meta_before, _ = frontmatter.read(text)
    original_order = list(meta_before.keys())

    updated = frontmatter.update(text, {"images_enriched": True, "image_count": 3})
    meta_after, _ = frontmatter.read(updated)

    # ordem original preservada como prefixo
    assert list(meta_after.keys())[: len(original_order)] == original_order
    # novas chaves no fim, na ordem do patch
    assert list(meta_after.keys())[len(original_order) :] == ["images_enriched", "image_count"]
    assert meta_after["images_enriched"] is True
    assert meta_after["image_count"] == 3


def test_update_sobrescreve_chave_existente_mantendo_posicao():
    text = "---\nfoo: 1\nbar: 2\n---\nbody\n"
    out = frontmatter.update(text, {"foo": 99, "novo": "x"})
    meta, _ = frontmatter.read(out)
    assert list(meta.keys()) == ["foo", "bar", "novo"]
    assert meta["foo"] == 99
    assert meta["bar"] == 2


def test_update_em_nota_sem_frontmatter_cria_bloco_yaml():
    text = "# Sem YAML\n\nconteúdo.\n"
    out = frontmatter.update(text, {"images_enriched": True})
    meta, body = frontmatter.read(out)
    assert meta == {"images_enriched": True}
    assert body == text


def test_update_nao_altera_chaves_de_export():
    text = _load("note_isrs.md")
    meta_before, _ = frontmatter.read(text)
    out = frontmatter.update(text, {"images_enriched": True, "image_count": 1})
    meta_after, _ = frontmatter.read(out)
    for k in PRE_EXISTING_KEYS:
        assert meta_after[k] == meta_before[k]


def test_write_meta_vazio_devolve_apenas_body():
    body = "# só corpo\n"
    assert frontmatter.write({}, body) == body
