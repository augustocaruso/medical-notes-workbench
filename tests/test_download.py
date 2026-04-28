import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from enricher.cache import Cache
from enricher.download import DownloadError, download


def _png_bytes(*, size=(800, 600), color=(255, 0, 0)) -> bytes:
    """Gera bytes PNG válidos via Pillow (para alimentar MockTransport)."""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _png_with_pattern(*, size=(800, 600)) -> bytes:
    """PNG mais 'compressível' que o cor-única (testa savings WebP)."""
    img = Image.new("RGB", size, (255, 0, 0))
    # adiciona ruído pra que PNG não comprima trivialmente
    pixels = img.load()
    for y in range(0, size[1], 2):
        for x in range(0, size[0], 2):
            pixels[x, y] = ((x * 13) % 256, (y * 7) % 256, ((x + y) * 5) % 256)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _client_returning(payload: bytes, *, status: int = 200, on_request=None) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(req)
        return httpx.Response(status, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


# --- happy path -----------------------------------------------------


def test_download_baixa_grava_e_indexa_no_cache(tmp_path):
    vault = tmp_path / "vault"
    db = tmp_path / "c.db"
    payload = _png_bytes()
    with Cache(db) as cache, _client_returning(payload) as client:
        out = download(
            "https://x.test/img.png",
            vault_dir=vault,
            cache=cache,
            client=client,
            source="wikimedia",
            source_url="https://x.test/page",
        )

    assert out["cached"] is False
    assert out["source"] == "wikimedia"
    assert out["source_url"] == "https://x.test/page"
    assert out["width"] == 800
    assert out["height"] == 600
    assert out["bytes"] > 0
    # arquivo gravado
    assert Path(out["path"]).exists()
    assert Path(out["path"]).read_bytes() == _file_bytes(out["path"])
    # cache populado (sha + url_index)
    with Cache(db) as cache:
        assert cache.get_image(out["sha"])["filename"] == out["filename"]
        assert cache.get_sha_for_url("https://x.test/img.png") == out["sha"]


def _file_bytes(p: str) -> bytes:
    return Path(p).read_bytes()


def test_download_filename_eh_sha_truncado(tmp_path):
    vault = tmp_path / "vault"
    payload = _png_bytes()
    with Cache(tmp_path / "c.db") as cache, _client_returning(payload) as client:
        out = download("https://x/img.png", vault_dir=vault, cache=cache, client=client)
    assert out["filename"].startswith(out["sha"][:12])
    assert out["filename"].split(".")[0] == out["sha"][:12]


# --- resize ---------------------------------------------------------


def test_download_redimensiona_para_max_dim(tmp_path):
    vault = tmp_path / "vault"
    payload = _png_bytes(size=(3000, 2000))
    with Cache(tmp_path / "c.db") as cache, _client_returning(payload) as client:
        out = download("https://x/big.png", vault_dir=vault, cache=cache, client=client, max_dim=1600)
    assert max(out["width"], out["height"]) == 1600
    # aspect ratio preservado (PIL pode arredondar ±1)
    assert out["width"] == 1600
    assert abs(out["height"] - round(1600 * 2000 / 3000)) <= 1


def test_download_nao_redimensiona_quando_dentro_do_limite(tmp_path):
    vault = tmp_path / "vault"
    payload = _png_bytes(size=(800, 600))
    with Cache(tmp_path / "c.db") as cache, _client_returning(payload) as client:
        out = download("https://x/sm.png", vault_dir=vault, cache=cache, client=client, max_dim=1600)
    assert (out["width"], out["height"]) == (800, 600)


# --- WebP encoding decision -----------------------------------------


def test_download_recodifica_para_webp_quando_economiza_bastante(tmp_path):
    """PNG com cor única → WebP economiza muito → vira .webp."""
    vault = tmp_path / "vault"
    payload = _png_bytes(size=(1000, 1000), color=(123, 222, 33))
    with Cache(tmp_path / "c.db") as cache, _client_returning(payload) as client:
        out = download(
            "https://x/solid.png",
            vault_dir=vault,
            cache=cache,
            client=client,
            webp_min_savings_pct=10,
        )
    assert out["filename"].endswith(".webp")


def test_download_preserva_formato_quando_webp_nao_economiza_o_suficiente(tmp_path):
    """Forçando threshold absurdo, PNG fica PNG."""
    vault = tmp_path / "vault"
    payload = _png_with_pattern(size=(400, 400))
    with Cache(tmp_path / "c.db") as cache, _client_returning(payload) as client:
        out = download(
            "https://x/noise.png",
            vault_dir=vault,
            cache=cache,
            client=client,
            webp_min_savings_pct=99,  # impossível atingir
        )
    assert out["filename"].endswith(".png")


# --- validação ------------------------------------------------------


def test_download_rejeita_html_servido_no_lugar_de_imagem(tmp_path):
    vault = tmp_path / "vault"
    html = b"<html><body>404 Not Found</body></html>"
    with Cache(tmp_path / "c.db") as cache, _client_returning(html) as client:
        with pytest.raises(DownloadError, match="não é imagem válida"):
            download("https://x/missing.png", vault_dir=vault, cache=cache, client=client)


def test_download_falha_em_status_4xx(tmp_path):
    vault = tmp_path / "vault"
    with Cache(tmp_path / "c.db") as cache, _client_returning(b"", status=404) as client:
        with pytest.raises(DownloadError, match="falha HTTP"):
            download("https://x/missing.png", vault_dir=vault, cache=cache, client=client)


# --- dedupe / cache --------------------------------------------------


def test_segunda_chamada_mesma_url_volta_via_cache_sem_http(tmp_path):
    vault = tmp_path / "vault"
    db = tmp_path / "c.db"
    payload = _png_bytes()
    hit_count = {"n": 0}

    def on_req(_):
        hit_count["n"] += 1

    with Cache(db) as cache, _client_returning(payload, on_request=on_req) as client:
        out1 = download("https://x/img.png", vault_dir=vault, cache=cache, client=client)
        out2 = download("https://x/img.png", vault_dir=vault, cache=cache, client=client)

    assert hit_count["n"] == 1  # segunda chamada não tocou na rede
    assert out1["sha"] == out2["sha"]
    assert out2["cached"] is True


def test_dedupe_por_sha_quando_duas_urls_servem_o_mesmo_conteudo(tmp_path):
    """URLs diferentes, conteúdo idêntico → mesmo sha → 1 arquivo."""
    vault = tmp_path / "vault"
    db = tmp_path / "c.db"
    payload = _png_bytes()
    with Cache(db) as cache, _client_returning(payload) as client:
        a = download("https://a/img.png", vault_dir=vault, cache=cache, client=client)
        b = download("https://b/img.png", vault_dir=vault, cache=cache, client=client)

    assert a["sha"] == b["sha"]
    assert a["filename"] == b["filename"]
    assert b["cached"] is True
    # só um arquivo no vault
    assert sum(1 for p in vault.iterdir() if p.is_file()) == 1


def test_user_agent_default_quando_nao_passado(tmp_path):
    """Quando user_agent=None, usa o _DEFAULT_USER_AGENT do módulo."""
    captured = {}
    real_client_cls = httpx.Client

    def factory(*a, **kw):
        def handler(req):
            captured["ua"] = req.headers.get("user-agent", "")
            return httpx.Response(200, content=_png_bytes())

        return real_client_cls(transport=httpx.MockTransport(handler), **kw)

    import enricher.download as dl_mod

    original = dl_mod.httpx.Client
    dl_mod.httpx.Client = factory
    try:
        with Cache(tmp_path / "c.db") as cache:
            download("https://x/img.png", vault_dir=tmp_path / "v", cache=cache)
    finally:
        dl_mod.httpx.Client = original

    # Default vem do módulo (não importa se é "browser" ou "identified" —
    # o que importa é que algo é enviado, e que não é o python-httpx que
    # Wikimedia rejeita).
    assert captured["ua"]
    assert "python-httpx" not in captured["ua"].lower()


def test_user_agent_custom_eh_propagado(tmp_path):
    captured = {}
    real_client_cls = httpx.Client

    def factory(*a, **kw):
        def handler(req):
            captured["ua"] = req.headers.get("user-agent", "")
            return httpx.Response(200, content=_png_bytes())

        return real_client_cls(transport=httpx.MockTransport(handler), **kw)

    import enricher.download as dl_mod
    original = dl_mod.httpx.Client
    dl_mod.httpx.Client = factory
    try:
        with Cache(tmp_path / "c.db") as cache:
            download(
                "https://x/img.png",
                vault_dir=tmp_path / "v",
                cache=cache,
                user_agent="MyCustomBot/9000",
            )
    finally:
        dl_mod.httpx.Client = original

    assert captured["ua"] == "MyCustomBot/9000"


def test_funciona_sem_cache(tmp_path):
    vault = tmp_path / "vault"
    payload = _png_bytes()
    with _client_returning(payload) as client:
        out = download("https://x/img.png", vault_dir=vault, cache=None, client=client)
    assert out["cached"] is False
    assert Path(out["path"]).exists()
