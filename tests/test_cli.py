"""Testes do dispatcher de subcomandos do CLI.

Chamamos ``cli.main([...])`` direto (mais rápido e capturável que subprocess) e
inspecionamos stdout/stderr via capsys. Pra ``search`` que faz HTTP, fazemos
monkeypatch de ``httpx.Client`` pra usar ``MockTransport`` carregando uma
fixture JSON.
"""
import io
import json
import shutil
from pathlib import Path

import httpx
import pytest
from PIL import Image

from enricher import cli


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- sections -------------------------------------------------------


def test_sections_devolve_lista_de_headings(tmp_path, capsys):
    note = tmp_path / "n.md"
    note.write_text(_fixture_text("note_didatic.md"), encoding="utf-8")

    rc = cli.main(["sections", str(note)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, list)
    assert {s["text"] for s in out} >= {
        "ISRS (inibidores seletivos da recaptação de serotonina)",
        "Mecanismo de ação",
        "Cinética sináptica",
        "Indicações clínicas",
        "Efeitos adversos",
    }
    cinetica = next(s for s in out if s["text"] == "Cinética sináptica")
    assert cinetica["level"] == 3
    assert cinetica["section_path"] == ["ISRS (inibidores seletivos da recaptação de serotonina)", "Mecanismo de ação", "Cinética sináptica"]


# --- search ---------------------------------------------------------


def _mock_httpx_client(monkeypatch, response_json: dict):
    """Substitui ``httpx.Client(...)`` por uma instância com MockTransport.

    Captura a classe original antes do patch pra evitar recursão infinita
    (o factory precisa instanciar Client de verdade, não o próprio factory).
    """
    real_client_cls = httpx.Client

    def factory(*_a, **_kw):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_json)

        return real_client_cls(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", factory)


def test_search_wikimedia_devolve_candidates_em_json(monkeypatch, capsys):
    data = json.loads((FIXTURES / "wikimedia_serotonin.json").read_text(encoding="utf-8"))
    _mock_httpx_client(monkeypatch, data)

    rc = cli.main(["search", "wikimedia", "--query", "serotonin", "--top-k", "2"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, list)
    assert len(out) == 2
    assert all(c["source"] == "wikimedia" for c in out)


def test_search_web_search_sem_key_devolve_lista_vazia(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setenv("MEDNOTES_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)

    rc = cli.main(["search", "web_search", "--query", "synapse"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == []


def test_search_web_search_com_key_usa_serpapi(monkeypatch, capsys):
    data = json.loads((FIXTURES / "serpapi_serotonin.json").read_text(encoding="utf-8"))
    _mock_httpx_client(monkeypatch, data)
    monkeypatch.setenv("SERPAPI_KEY", "fake")
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    rc = cli.main(["search", "web_search", "--query", "synapse", "--top-k", "3"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 3
    assert all(c["source"] == "web_search" for c in out)


def test_search_source_invalida_falha_com_exit_2(capsys):
    # `argparse choices` rejeita antes do dispatcher: SystemExit(2)
    with pytest.raises(SystemExit) as exc:
        cli.main(["search", "fonte_que_nao_existe", "--query", "x"])
    assert exc.value.code == 2


# --- download -------------------------------------------------------


def _png_bytes(size=(400, 300), color=(50, 100, 200)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _mock_httpx_returning(monkeypatch, payload: bytes, status: int = 200):
    real_client_cls = httpx.Client

    def factory(*_a, **_kw):
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(status, content=payload)

        return real_client_cls(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", factory)


def test_download_grava_arquivo_e_emite_resumo(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    monkeypatch.setenv("ENRICHER_DUMMY", "x")  # apenas pra silenciar lints
    _mock_httpx_returning(monkeypatch, _png_bytes())

    # CLI lê config; injeto cache path via config.toml temporário
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[vault]\npath = "{vault}"\nattachments_subdir = ""\n'
        f'[cache]\npath = "{cache_db}"\n',
        encoding="utf-8",
    )

    rc = cli.main(["--config", str(cfg), "download", "https://x/img.png", "--source", "wikimedia"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cached"] is False
    assert out["source"] == "wikimedia"
    assert Path(out["path"]).exists()
    # cache populado
    assert cache_db.exists()


def test_download_idempotente_segunda_chamada_marca_cached(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    _mock_httpx_returning(monkeypatch, _png_bytes())
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[vault]\npath = "{vault}"\nattachments_subdir = ""\n'
        f'[cache]\npath = "{cache_db}"\n',
        encoding="utf-8",
    )

    cli.main(["--config", str(cfg), "download", "https://x/img.png"])
    capsys.readouterr()  # descarta primeiro JSON
    cli.main(["--config", str(cfg), "download", "https://x/img.png"])
    out2 = json.loads(capsys.readouterr().out)
    assert out2["cached"] is True


def test_download_sem_vault_em_config_falha_com_exit_4(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[vault]\npath = ""\n', encoding="utf-8")

    rc = cli.main(["--config", str(cfg), "download", "https://x/img.png"])
    assert rc == 4
    assert "vault_dir" in capsys.readouterr().err


def test_download_html_no_lugar_da_imagem_falha_com_exit_5(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    _mock_httpx_returning(monkeypatch, b"<html>404</html>")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[vault]\npath = "{vault}"\nattachments_subdir = ""\n'
        f'[cache]\npath = "{cache_db}"\n',
        encoding="utf-8",
    )

    rc = cli.main(["--config", str(cfg), "download", "https://x/missing.png"])
    assert rc == 5
    assert "imagem" in capsys.readouterr().err


# --- insert ---------------------------------------------------------


def test_insert_modifica_nota_in_place_e_emite_resumo(tmp_path, capsys):
    note = tmp_path / "n.md"
    note.write_text(_fixture_text("note_didatic.md"), encoding="utf-8")

    rc = cli.main(
        [
            "insert",
            str(note),
            "--section", "ISRS (inibidores seletivos da recaptação de serotonina)",
            "--section", "Mecanismo de ação",
            "--image", "abc.webp",
            "--concept", "recaptação",
            "--source", "wikimedia",
            "--source-url", "https://commons.wikimedia.org/wiki/File:X",
        ]
    )
    assert rc == 0

    # nota foi modificada
    body = note.read_text(encoding="utf-8")
    assert "![[abc.webp]]" in body
    assert "*Figura: recaptação.*" in body

    # stdout tem resumo JSON
    summary = json.loads(capsys.readouterr().out)
    assert summary["inserted"] == 1
    assert summary["image_count"] == 1
    assert summary["image_sources"] == [{"source": "wikimedia", "count": 1}]


def test_insert_secao_inexistente_falha_com_exit_3(tmp_path, capsys):
    note = tmp_path / "n.md"
    note.write_text(_fixture_text("note_didatic.md"), encoding="utf-8")

    rc = cli.main(
        [
            "insert",
            str(note),
            "--section", "Seção",
            "--section", "Que não existe",
            "--image", "x.webp",
            "--concept", "c",
            "--source", "wikimedia",
            "--source-url", "u",
        ]
    )
    assert rc == 3
    err = capsys.readouterr().err
    assert "não encontrado" in err
    # nota intacta
    assert "![[x.webp]]" not in note.read_text(encoding="utf-8")


def test_insert_aceita_section_repetivel_pra_path_nested(tmp_path, capsys):
    note = tmp_path / "n.md"
    note.write_text(_fixture_text("note_nested.md"), encoding="utf-8")

    rc = cli.main(
        [
            "insert",
            str(note),
            "--section", "🤖 Gemini",
            "--section", "Mecanismo",
            "--image", "nest.webp",
            "--concept", "nested",
            "--source", "wikimedia",
            "--source-url", "https://x",
        ]
    )
    assert rc == 0
    body = note.read_text(encoding="utf-8")
    # Vai pra primeira ocorrência de ### Mecanismo, antes de ### Indicações
    primeira_mec = body.index("### Mecanismo")
    indicacoes = body.index("### Indicações")
    embed = body.index("![[nest.webp]]")
    assert primeira_mec < embed < indicacoes
