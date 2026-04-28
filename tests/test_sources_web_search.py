import json
from pathlib import Path

import httpx
import pytest

from enricher.sources import ImageCandidate, web_search


FIXTURES = Path(__file__).parent / "fixtures"


def _client_with(response_json: dict, *, on_request=None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(request)
        return httpx.Response(200, json=response_json)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_sem_key_devolve_lista_vazia(monkeypatch, tmp_path):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    # Note: `client` não chega a ser usado porque a função sai antes.
    out = web_search.search("qualquer coisa", "diagram", top_k=4)
    assert out == []


def test_search_carrega_key_do_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    (tmp_path / ".env").write_text("SERPAPI_KEY=K_DOTENV\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    captured: dict = {}

    def on_request(request: httpx.Request) -> None:
        captured["params"] = dict(request.url.params)

    with _client_with({"images_results": []}, on_request=on_request) as client:
        out = web_search.search("q", "diagram", top_k=1, client=client)

    assert out == []
    assert captured["params"]["api_key"] == "K_DOTENV"


def test_search_api_key_explicita_tem_precedencia_sobre_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    (tmp_path / ".env").write_text("SERPAPI_KEY=K_DOTENV\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    captured: dict = {}

    def on_request(request: httpx.Request) -> None:
        captured["params"] = dict(request.url.params)

    with _client_with({"images_results": []}, on_request=on_request) as client:
        web_search.search("q", "diagram", top_k=1, client=client, api_key="K_EXPLICIT")

    assert captured["params"]["api_key"] == "K_EXPLICIT"


def test_search_parses_candidates_da_fixture():
    data = json.loads((FIXTURES / "serpapi_serotonin.json").read_text(encoding="utf-8"))
    with _client_with(data) as client:
        out = web_search.search(
            "serotonin reuptake", "diagram", top_k=4, client=client, api_key="fake"
        )

    assert all(isinstance(c, ImageCandidate) for c in out)
    assert all(c.source == "web_search" for c in out)
    assert out[0].title == "Serotonin reuptake at the synapse"
    assert out[0].image_url == "https://example.org/figs/serotonin_reuptake.png"
    assert out[0].source_url == "https://example.org/articles/serotonin-reuptake"
    assert out[0].thumbnail_url == "https://serpapi.com/searches/abc/images/thumbs/1.jpg"
    assert out[0].width == 1600
    assert out[0].license is None  # SerpAPI não devolve licença


def test_search_respeita_top_k():
    data = json.loads((FIXTURES / "serpapi_serotonin.json").read_text(encoding="utf-8"))
    with _client_with(data) as client:
        out = web_search.search("q", "diagram", top_k=2, client=client, api_key="fake")
    assert len(out) == 2


def test_search_cai_no_thumbnail_quando_sem_original():
    data = {
        "images_results": [
            {
                "thumbnail": "https://serpapi.com/thumb/x.jpg",
                "title": "só thumb",
                "link": "https://example/x",
            }
        ]
    }
    with _client_with(data) as client:
        out = web_search.search("q", "diagram", top_k=4, client=client, api_key="fake")
    assert len(out) == 1
    assert out[0].image_url == "https://serpapi.com/thumb/x.jpg"


def test_search_pula_entradas_sem_imagem():
    data = {
        "images_results": [
            {"title": "sem url", "link": "https://example"},
            {
                "original": "https://ok.example/y.png",
                "title": "com url",
                "link": "https://ok.example",
            },
        ]
    }
    with _client_with(data) as client:
        out = web_search.search("q", "diagram", top_k=4, client=client, api_key="fake")
    assert len(out) == 1
    assert out[0].title == "com url"


def test_search_envia_parametros_corretos_pra_api():
    captured: dict = {}

    def on_request(request: httpx.Request) -> None:
        captured["host"] = request.url.host
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)

    with _client_with({"images_results": []}, on_request=on_request) as client:
        web_search.search("ácido fólico", "diagram", top_k=3, client=client, api_key="K123")

    assert captured["host"] == "serpapi.com"
    assert captured["path"] == "/search.json"
    assert captured["params"]["engine"] == "google_images"
    assert captured["params"]["q"] == "ácido fólico"
    assert captured["params"]["api_key"] == "K123"
    assert int(captured["params"]["num"]) >= 3


def test_search_language_pt_br_envia_hl_e_gl():
    captured = {}

    def on_request(request: httpx.Request) -> None:
        captured["params"] = dict(request.url.params)

    with _client_with({"images_results": []}, on_request=on_request) as client:
        web_search.search("q", "diagram", top_k=2, client=client, api_key="K", language="pt-br")
    assert captured["params"]["hl"] == "pt-br"
    assert captured["params"]["gl"] == "br"


def test_search_language_en_envia_hl_en_e_gl_us():
    captured = {}

    def on_request(request: httpx.Request) -> None:
        captured["params"] = dict(request.url.params)

    with _client_with({"images_results": []}, on_request=on_request) as client:
        web_search.search("q", "diagram", top_k=2, client=client, api_key="K", language="en")
    assert captured["params"]["hl"] == "en"
    assert captured["params"]["gl"] == "us"


def test_search_language_any_nao_envia_hl_gl():
    captured = {}

    def on_request(request: httpx.Request) -> None:
        captured["params"] = dict(request.url.params)

    with _client_with({"images_results": []}, on_request=on_request) as client:
        web_search.search("q", "diagram", top_k=2, client=client, api_key="K", language="any")
    assert "hl" not in captured["params"]
    assert "gl" not in captured["params"]


def test_search_resposta_sem_images_results_devolve_vazio():
    with _client_with({"search_metadata": {"status": "Success"}}) as client:
        out = web_search.search("nada", "diagram", top_k=4, client=client, api_key="fake")
    assert out == []
