import json
from pathlib import Path

import httpx
import pytest

from enricher.sources import ImageCandidate, wikimedia


FIXTURES = Path(__file__).parent / "fixtures"


def _client_with(response_json: dict, *, on_request=None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(request)
        return httpx.Response(200, json=response_json)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_parses_candidates_da_fixture():
    data = json.loads((FIXTURES / "wikimedia_serotonin.json").read_text(encoding="utf-8"))
    with _client_with(data) as client:
        out = wikimedia.search("serotonin reuptake", "diagram", top_k=4, client=client)

    assert all(isinstance(c, ImageCandidate) for c in out)
    assert all(c.source == "wikimedia" for c in out)
    assert all(c.image_url.startswith("https://upload.wikimedia.org/") for c in out)
    # primeiro candidato vem da primeira página com imageinfo válido
    assert out[0].title == "File:Serotonin_reuptake.svg"
    assert out[0].license == "CC BY-SA 4.0"
    assert "recaptação" in out[0].description.lower()


def test_search_respeita_top_k():
    data = json.loads((FIXTURES / "wikimedia_serotonin.json").read_text(encoding="utf-8"))
    with _client_with(data) as client:
        out = wikimedia.search("q", "diagram", top_k=2, client=client)
    assert len(out) == 2


def test_search_pula_paginas_sem_imageinfo_e_mimes_nao_imagem():
    data = json.loads((FIXTURES / "wikimedia_serotonin.json").read_text(encoding="utf-8"))
    with _client_with(data) as client:
        out = wikimedia.search("q", "diagram", top_k=10, client=client)
    titles = [c.title for c in out]
    # PDF e a página sem imageinfo são puladas
    assert "File:Random_unrelated.pdf" not in titles
    assert "File:Without_imageinfo.png" not in titles
    # 4 candidatas válidas restam (1001, 1002, 1003, 1006)
    assert len(out) == 4


def test_search_prefere_thumb_sobre_url_original():
    data = {
        "query": {
            "pages": [
                {
                    "pageid": 1,
                    "title": "File:ok.png",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/x/y/ok.png",
                            "thumburl": "https://upload.wikimedia.org/.../1600px-ok.png",
                            "thumbwidth": 1600,
                            "thumbheight": 1200,
                            "width": 4000,
                            "height": 3000,
                            "mime": "image/png",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:ok.png",
                            "extmetadata": {"LicenseShortName": {"value": "CC0"}},
                        }
                    ],
                }
            ]
        }
    }
    with _client_with(data) as client:
        out = wikimedia.search("q", "diagram", top_k=4, client=client)
    assert len(out) == 1
    assert out[0].image_url.endswith("1600px-ok.png")
    assert out[0].width == 1600  # thumbwidth ganha
    assert out[0].license == "CC0"


def test_search_envia_parametros_corretos_pra_api():
    captured: dict = {}

    def on_request(request: httpx.Request) -> None:
        captured["host"] = request.url.host
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["ua"] = request.headers.get("user-agent", "")

    with _client_with({"query": {"pages": []}}, on_request=on_request) as client:
        wikimedia.search("ácido fólico", "histology", top_k=3, client=client)

    assert captured["host"] == "commons.wikimedia.org"
    assert captured["path"] == "/w/api.php"
    assert captured["params"]["action"] == "query"
    assert captured["params"]["generator"] == "search"
    assert captured["params"]["gsrsearch"] == "ácido fólico"
    assert captured["params"]["gsrnamespace"] == "6"
    assert captured["params"]["prop"] == "imageinfo"
    assert "medical-notes-enricher" in captured["ua"]


def test_search_resposta_vazia_devolve_lista_vazia():
    with _client_with({"batchcomplete": True, "query": {"pages": []}}) as client:
        out = wikimedia.search("nada disso existe", "diagram", top_k=4, client=client)
    assert out == []


def test_search_resposta_sem_query_devolve_lista_vazia():
    with _client_with({"batchcomplete": True}) as client:
        out = wikimedia.search("q", "diagram", top_k=4, client=client)
    assert out == []
