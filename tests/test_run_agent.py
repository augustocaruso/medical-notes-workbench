"""Testes do orquestrador `scripts/run_agent.py`.

Estratégia: mockar dois seams — (1) ``_invoke_gemini`` que retorna stdout do
gemini CLI, e (2) ``httpx.Client`` que serve bytes/JSON canned. Sem rede.
"""
import io
import json
import sys
from pathlib import Path

import httpx
import pytest
from PIL import Image


# Adiciona scripts/ ao path pra importar o módulo run_agent.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import run_agent  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures"


# --- helpers de mock ------------------------------------------------


def _png_bytes(size=(400, 300), color=(50, 100, 200)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class GeminiQueue:
    """Fila de respostas canned. Cada chamada a `_invoke_gemini` consome a
    próxima. Usar via monkeypatch."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> str:
        self.calls.append(cmd)
        if not self._responses:
            raise AssertionError(f"GeminiQueue exausta. Última cmd: {cmd}")
        return self._responses.pop(0)


def _mock_httpx(monkeypatch, *, json_responses: dict[str, dict] | None = None,
                bytes_response: bytes | None = None):
    """Substitui httpx.Client. Se a URL casar com algum host em json_responses,
    devolve aquele JSON. Senão, devolve bytes_response (pra downloads).
    """
    real_client_cls = httpx.Client
    json_responses = json_responses or {}

    def factory(*_a, **_kw):
        def handler(req: httpx.Request) -> httpx.Response:
            for host_substr, payload in json_responses.items():
                if host_substr in str(req.url):
                    return httpx.Response(200, json=payload)
            if bytes_response is not None:
                return httpx.Response(200, content=bytes_response)
            return httpx.Response(404, content=b"not found")

        return real_client_cls(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", factory)


def _write_config(tmp_path: Path, *, vault: Path, cache_db: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[vault]\npath = "{vault}"\nattachments_subdir = ""\n'
        f'[enrichment]\nmax_anchors_per_note = 5\n'
        f'max_image_dimension = 1600\nwebp_min_savings_pct = 30\n'
        f'preferred_language = "any"\n'
        f'[sources]\nenabled = ["wikimedia"]\ntop_k_per_source = 4\n'
        f'[gemini]\nbinary = "gemini"\nmodel_anchors = "x"\nmodel_rerank = "y"\n'
        f'max_candidates_per_anchor = 8\n'
        f'[cache]\npath = "{cache_db}"\ncandidates_ttl_days = 30\n',
        encoding="utf-8",
    )
    return cfg


# --- parsing helpers (puros) ----------------------------------------


def test_parse_anchors_aceita_json_com_fences_de_codigo():
    raw = '```json\n[{"section_path":["X"],"concept":"c","visual_type":"diagram","search_queries":["q"]}]\n```'
    out = run_agent.parse_anchors_json(raw)
    assert len(out) == 1
    assert out[0]["anchor_id"] == "a1"  # default gerado


def test_parse_anchors_rejeita_anchor_sem_chave_obrigatoria():
    raw = '[{"section_path":["X"],"concept":"c"}]'  # sem visual_type / search_queries
    with pytest.raises(ValueError, match="visual_type"):
        run_agent.parse_anchors_json(raw)


def test_anchors_prompt_pt_br_pede_query_em_portugues():
    sections = [{"section_path": ["X"], "level": 1}]
    prompt = run_agent.build_anchors_prompt(
        "nota", sections, max_anchors=3, preferred_language="pt-br"
    )
    assert "português" in prompt or "PT" in prompt


def test_anchors_prompt_en_pede_so_ingles():
    sections = [{"section_path": ["X"], "level": 1}]
    prompt = run_agent.build_anchors_prompt(
        "nota", sections, max_anchors=3, preferred_language="en"
    )
    # Não pede PT
    assert "português" not in prompt.lower()
    assert "inglês" in prompt or "english" in prompt.lower() or "EN" in prompt


def test_rerank_prompt_pt_br_inclui_hint_de_idioma():
    from enricher.sources import ImageCandidate

    anchor = {
        "concept": "x", "visual_type": "diagram",
        "search_queries": ["q"],
    }
    candidates = [
        ImageCandidate(
            source="wikimedia", source_url="u", image_url="i",
            title="t", description="d", width=100, height=100,
            license="CC0", score=None,
        )
    ]
    p_pt = run_agent.build_rerank_prompt(anchor, candidates, preferred_language="pt-br")
    p_en = run_agent.build_rerank_prompt(anchor, candidates, preferred_language="en")
    assert "português" in p_pt.lower()
    assert "português" not in p_en.lower()


def test_parse_rerank_aceita_chosen_index_null():
    raw = '{"chosen_index": null, "reason": "nada serve"}'
    out = run_agent.parse_rerank_json(raw)
    assert out["chosen_index"] is None


def test_call_gemini_json_retry_corrige_resposta_invalida(monkeypatch):
    valid = json.dumps([{
        "section_path": ["T"],
        "concept": "sinapse serotoninérgica",
        "visual_type": "diagram",
        "search_queries": ["serotonin synapse"],
    }])
    queue = GeminiQueue(["vou responder em JSON daqui a pouco", valid])
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)

    anchors, raw = run_agent.call_gemini_json_with_retry(
        "prompt original",
        run_agent.parse_anchors_json,
        binary="gemini",
        model="x",
        label="âncoras",
    )

    assert len(queue.calls) == 2
    assert anchors[0]["concept"] == "sinapse serotoninérgica"
    assert raw == valid


# --- orquestração end-to-end (mocks) --------------------------------


def test_orquestrador_e2e_anchors_e_rerank(monkeypatch, tmp_path, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db)
    note = tmp_path / "n.md"
    note.write_text((FIXTURES / "note_didatic.md").read_text(encoding="utf-8"), encoding="utf-8")

    # Gemini retorna: 1 âncora (anchors) + 1 escolha (rerank)
    anchors_json = json.dumps([{
        "section_path": [
            "ISRS (inibidores seletivos da recaptação de serotonina)",
            "Mecanismo de ação",
        ],
        "concept": "recaptação de serotonina pelo SERT",
        "visual_type": "diagram",
        "search_queries": ["serotonin reuptake transporter"],
        "anchor_id": "a1",
    }])
    rerank_json = json.dumps({"chosen_index": 0, "reason": "diagrama claro"})
    queue = GeminiQueue([anchors_json, rerank_json])
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)

    # Wikimedia API → 1 candidata; downloads (thumb + full) → mesmo PNG
    wiki_response = {
        "query": {
            "pages": [{
                "pageid": 1,
                "title": "File:SERT.svg",
                "imageinfo": [{
                    "url": "https://upload.wikimedia.org/sert.png",
                    "thumburl": "https://upload.wikimedia.org/thumbs/sert_1600.png",
                    "thumbwidth": 1600, "thumbheight": 1200,
                    "width": 2000, "height": 1500,
                    "mime": "image/png",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:SERT.svg",
                    "extmetadata": {
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "ImageDescription": {"value": "Recaptação de serotonina."},
                    },
                }]
            }]
        }
    }
    _mock_httpx(monkeypatch, json_responses={"commons.wikimedia.org": wiki_response},
                bytes_response=_png_bytes())

    rc = run_agent.main([str(note), "--config", str(cfg)])
    assert rc == 0

    # 2 chamadas ao gemini: anchors + rerank
    assert len(queue.calls) == 2
    # Modelos diferentes nas duas chamadas (anchors=Pro, rerank=Flash)
    assert "x" in queue.calls[0]
    assert "y" in queue.calls[1]
    # Rerank teve --include-directories pra dar acesso aos thumbs
    assert "--include-directories" in queue.calls[1]

    # Nota foi modificada
    body = note.read_text(encoding="utf-8")
    assert "![[" in body
    assert "*Figura: recaptação de serotonina pelo SERT.*" in body
    # Frontmatter aditivo
    assert "images_enriched: true" in body


def test_orquestrador_idempotente_se_ja_enriquecida(monkeypatch, tmp_path, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db)
    note = tmp_path / "n.md"
    note.write_text(
        "---\ntitle: x\nimages_enriched: true\n---\n\n# T\n\n## S\n\nbody.\n",
        encoding="utf-8",
    )

    # Gemini não deve ser chamado
    queue = GeminiQueue([])
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)

    rc = run_agent.main([str(note), "--config", str(cfg)])
    assert rc == 0
    assert queue.calls == []
    err = capsys.readouterr().err
    assert "já enriquecida" in err


def test_orquestrador_force_pula_idempotencia(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db)
    note = tmp_path / "n.md"
    note.write_text(
        "---\ntitle: x\nimages_enriched: true\n---\n\n# T\n\n## S\n\nbody.\n",
        encoding="utf-8",
    )

    queue = GeminiQueue([json.dumps([])])  # gemini decide 0 âncoras
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)

    rc = run_agent.main([str(note), "--config", str(cfg), "--force"])
    assert rc == 0
    assert len(queue.calls) == 1  # gemini foi chamado pra anchors


def test_orquestrador_sem_ancoras_sai_limpo(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db)
    note = tmp_path / "n.md"
    note.write_text("# T\n\n## S\n\nbody.\n", encoding="utf-8")

    queue = GeminiQueue([json.dumps([])])
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)

    rc = run_agent.main([str(note), "--config", str(cfg)])
    assert rc == 0
    body = note.read_text(encoding="utf-8")
    assert "images_enriched" not in body  # nada foi inserido


def test_orquestrador_anchor_sem_candidatas_eh_pulada(monkeypatch, tmp_path, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db)
    note = tmp_path / "n.md"
    note.write_text("# T\n\n## S\n\nbody.\n", encoding="utf-8")

    anchors_json = json.dumps([{
        "section_path": ["T", "S"],
        "concept": "x",
        "visual_type": "diagram",
        "search_queries": ["nada"],
        "anchor_id": "a1",
    }])
    queue = GeminiQueue([anchors_json])  # só anchors; rerank não deve ser chamado
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)

    # Wikimedia retorna 0 páginas
    _mock_httpx(monkeypatch, json_responses={"commons.wikimedia.org": {"query": {"pages": []}}})

    rc = run_agent.main([str(note), "--config", str(cfg)])
    assert rc == 0
    assert len(queue.calls) == 1  # rerank não foi chamado
    assert "sem candidatas" in capsys.readouterr().out


def test_orquestrador_rerank_null_pula_ancora(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db)
    note = tmp_path / "n.md"
    note.write_text("# T\n\n## S\n\nbody.\n", encoding="utf-8")

    anchors_json = json.dumps([{
        "section_path": ["T", "S"],
        "concept": "x",
        "visual_type": "diagram",
        "search_queries": ["q"],
        "anchor_id": "a1",
    }])
    rerank_json = json.dumps({"chosen_index": None, "reason": "nada serve"})
    queue = GeminiQueue([anchors_json, rerank_json])
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)

    wiki_response = {
        "query": {
            "pages": [{
                "pageid": 1, "title": "File:x.png",
                "imageinfo": [{
                    "url": "https://upload.wikimedia.org/x.png",
                    "thumburl": "https://upload.wikimedia.org/thumb_x.png",
                    "thumbwidth": 1600, "thumbheight": 1200,
                    "mime": "image/png",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:x.png",
                    "extmetadata": {"LicenseShortName": {"value": "CC0"}},
                }]
            }]
        }
    }
    _mock_httpx(monkeypatch, json_responses={"commons.wikimedia.org": wiki_response},
                bytes_response=_png_bytes())

    rc = run_agent.main([str(note), "--config", str(cfg)])
    assert rc == 0
    body = note.read_text(encoding="utf-8")
    assert "![[" not in body  # nada foi inserido


def test_orquestrador_falha_se_gemini_devolve_lixo(monkeypatch, tmp_path, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db)
    note = tmp_path / "n.md"
    note.write_text("# T\n\n## S\n\nbody.\n", encoding="utf-8")

    queue = GeminiQueue(["isso não é JSON nenhum", "continua sem JSON"])
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)

    rc = run_agent.main([str(note), "--config", str(cfg)])
    assert rc == 7
    assert len(queue.calls) == 2
    assert "âncoras inválidas" in capsys.readouterr().err
