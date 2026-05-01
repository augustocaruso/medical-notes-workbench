"""Testes do orquestrador `scripts/enrich_notes.py`.

Estratégia: mockar dois seams — (1) ``_invoke_gemini`` que retorna stdout do
gemini CLI, e (2) ``httpx.Client`` que serve bytes/JSON canned. Sem rede.
"""
import io
import json
import subprocess
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
from enrich_workflow import candidates as workflow_candidates  # noqa: E402
from enrich_workflow import gemini as workflow_gemini  # noqa: E402
from enrich_workflow import inputs as workflow_inputs  # noqa: E402
from enrich_workflow import parsing as workflow_parsing  # noqa: E402
from enrich_workflow import prompts as workflow_prompts  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures"


# --- helpers de mock ------------------------------------------------


def test_legacy_orchestrator_import_surface_is_preserved():
    assert run_agent.GeminiError is workflow_gemini.GeminiError
    assert run_agent._resolve_note_inputs is workflow_inputs._resolve_note_inputs
    assert run_agent.parse_anchors_json is workflow_parsing.parse_anchors_json
    assert run_agent.build_anchors_prompt is workflow_prompts.build_anchors_prompt
    assert run_agent.fetch_thumbs
    assert run_agent.main


def test_enrich_entrypoints_expose_help():
    for script in ("enrich_notes.py", "run_agent.py"):
        result = subprocess.run(
            [sys.executable, str(_SCRIPTS / script), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
        assert "enrich_notes" in result.stdout


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
        self.timeouts: list[int] = []

    def __call__(self, cmd: list[str], *, timeout_seconds: int = 120) -> str:
        self.calls.append(cmd)
        self.timeouts.append(timeout_seconds)
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


def _write_config(
    tmp_path: Path,
    *,
    vault: Path,
    cache_db: Path,
    sources: list[str] | None = None,
) -> Path:
    sources = sources or ["wikimedia"]
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[vault]\npath = "{vault}"\nattachments_subdir = ""\n'
        f'[enrichment]\nmax_anchors_per_note = 5\n'
        f'max_image_dimension = 1600\nwebp_min_savings_pct = 30\n'
        f'preferred_language = "any"\n'
        f'[sources]\nenabled = {json.dumps(sources)}\ntop_k_per_source = 4\n'
        f'[gemini]\nbinary = "gemini"\nmodel_anchors = "x"\nmodel_rerank = "y"\n'
        f'max_candidates_per_anchor = 8\ntimeout_seconds = 42\n'
        f'[cache]\npath = "{cache_db}"\ncandidates_ttl_days = 30\n',
        encoding="utf-8",
    )
    return cfg


def _anchors_json(*, concept: str = "recaptação de serotonina pelo SERT") -> str:
    return json.dumps([{
        "section_path": [
            "ISRS (inibidores seletivos da recaptação de serotonina)",
            "Mecanismo de ação",
        ],
        "concept": concept,
        "visual_type": "diagram",
        "search_queries": ["serotonin reuptake transporter"],
        "anchor_id": "a1",
    }])


def _wiki_image_response() -> dict:
    return {
        "query": {
            "pages": [{
                "pageid": 1,
                "title": "File:SERT.svg",
                "imageinfo": [{
                    "url": "https://upload.wikimedia.org/sert.png",
                    "thumburl": "https://upload.wikimedia.org/thumbs/sert_1600.png",
                    "thumbwidth": 1600,
                    "thumbheight": 1200,
                    "width": 2000,
                    "height": 1500,
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


# --- resolução de inputs -------------------------------------------


def test_resolve_note_inputs_expande_diretorio_recursivo_e_ignora_anexos(tmp_path):
    root = tmp_path / "Wiki"
    (root / "Cardiologia").mkdir(parents=True)
    (root / "Cardiologia" / "A.md").write_text("# A\n", encoding="utf-8")
    (root / "Cardiologia" / "Sub").mkdir()
    (root / "Cardiologia" / "Sub" / "B.md").write_text("# B\n", encoding="utf-8")
    (root / "attachments").mkdir()
    (root / "attachments" / "C.md").write_text("# C\n", encoding="utf-8")
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "D.md").write_text("# D\n", encoding="utf-8")

    notes, errors = workflow_inputs._resolve_note_inputs([root])

    assert errors == []
    assert [path.name for path in notes] == ["A.md", "B.md"]


def test_resolve_note_inputs_expande_glob_e_deduplica(tmp_path):
    root = tmp_path / "Wiki"
    root.mkdir()
    a = root / "A.md"
    b = root / "B.md"
    a.write_text("# A\n", encoding="utf-8")
    b.write_text("# B\n", encoding="utf-8")
    (root / "C.txt").write_text("x\n", encoding="utf-8")

    notes, errors = workflow_inputs._resolve_note_inputs([root / "*.md", a])

    assert errors == []
    assert [path.name for path in notes] == ["A.md", "B.md"]


def test_resolve_note_inputs_reporta_glob_ou_diretorio_sem_notas(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    notes, errors = workflow_inputs._resolve_note_inputs([tmp_path / "*.md", empty])

    assert notes == []
    assert len(errors) == 2
    assert errors[0].code == 2
    assert "glob sem correspondências" in errors[0].message
    assert "diretório sem notas" in errors[1].message


# --- parsing helpers (puros) ----------------------------------------


def test_parse_anchors_aceita_json_com_fences_de_codigo():
    raw = '```json\n[{"section_path":["X"],"concept":"c","visual_type":"diagram","search_queries":["q"]}]\n```'
    out = workflow_parsing.parse_anchors_json(raw)
    assert len(out) == 1
    assert out[0]["anchor_id"] == "a1"  # default gerado


def test_parse_anchors_rejeita_anchor_sem_chave_obrigatoria():
    raw = '[{"section_path":["X"],"concept":"c"}]'  # sem visual_type / search_queries
    with pytest.raises(ValueError, match="visual_type"):
        workflow_parsing.parse_anchors_json(raw)


def test_anchors_prompt_pt_br_pede_query_em_portugues():
    sections = [{"section_path": ["X"], "level": 1}]
    prompt = workflow_prompts.build_anchors_prompt(
        "nota", sections, max_anchors=3, preferred_language="pt-br"
    )
    assert "português" in prompt or "PT" in prompt


def test_anchors_prompt_en_pede_so_ingles():
    sections = [{"section_path": ["X"], "level": 1}]
    prompt = workflow_prompts.build_anchors_prompt(
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
    p_pt = workflow_prompts.build_rerank_prompt(anchor, candidates, preferred_language="pt-br")
    p_en = workflow_prompts.build_rerank_prompt(anchor, candidates, preferred_language="en")
    assert "português" in p_pt.lower()
    assert "português" not in p_en.lower()


def test_parse_rerank_aceita_chosen_index_null():
    raw = '{"chosen_index": null, "reason": "nada serve"}'
    out = workflow_parsing.parse_rerank_json(raw)
    assert out["chosen_index"] is None


def test_invoke_gemini_timeout_vira_gemini_error(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["gemini"], timeout=3)

    monkeypatch.setattr(workflow_gemini.subprocess, "run", fake_run)

    with pytest.raises(workflow_gemini.GeminiError, match="timeout de 3s"):
        workflow_gemini._invoke_gemini(["gemini"], timeout_seconds=3)


def test_call_gemini_json_retry_corrige_resposta_invalida(monkeypatch):
    valid = json.dumps([{
        "section_path": ["T"],
        "concept": "sinapse serotoninérgica",
        "visual_type": "diagram",
        "search_queries": ["serotonin synapse"],
    }])
    queue = GeminiQueue(["vou responder em JSON daqui a pouco", valid])
    monkeypatch.setattr(workflow_gemini, "_invoke_gemini", queue)

    anchors, raw = workflow_gemini.call_gemini_json_with_retry(
        "prompt original",
        workflow_parsing.parse_anchors_json,
        binary="gemini",
        model="x",
        label="âncoras",
    )

    assert len(queue.calls) == 2
    assert queue.timeouts == [120, 120]
    assert anchors[0]["concept"] == "sinapse serotoninérgica"
    assert raw == valid


def test_fetch_thumbs_tenta_thumbnail_quando_original_falha(monkeypatch, tmp_path):
    from enricher.download import DownloadError
    from enricher.sources import ImageCandidate

    calls = []

    def fake_download(url, **_kwargs):
        calls.append(url)
        if url == "https://blocked.example/original.png":
            raise DownloadError("403")
        return {"path": str(tmp_path / "thumb.webp")}

    monkeypatch.setattr(workflow_candidates, "download_image", fake_download)
    candidate = ImageCandidate(
        source="web_search",
        source_url="https://example.org/page",
        image_url="https://blocked.example/original.png",
        title="t",
        description="d",
        width=100,
        height=100,
        license=None,
        score=None,
        thumbnail_url="https://serpapi.com/thumb.jpg",
    )

    out = workflow_candidates.fetch_thumbs([candidate], tmp_dir=tmp_path)

    assert calls == [
        "https://blocked.example/original.png",
        "https://serpapi.com/thumb.jpg",
    ]
    assert out == [tmp_path / "thumb.webp"]


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
    assert queue.timeouts == [42, 42]
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
    out = capsys.readouterr().out
    assert "Resumo final" in out
    assert "Enriquecidas: 1" in out


def test_orquestrador_batch_duas_notas_enriquece_em_ordem(monkeypatch, tmp_path, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db)
    note1 = tmp_path / "n1.md"
    note2 = tmp_path / "n2.md"
    fixture = (FIXTURES / "note_didatic.md").read_text(encoding="utf-8")
    note1.write_text(fixture, encoding="utf-8")
    note2.write_text(fixture, encoding="utf-8")

    rerank_json = json.dumps({"chosen_index": 0, "reason": "diagrama claro"})
    queue = GeminiQueue([
        _anchors_json(concept="recaptação de serotonina pelo SERT"),
        rerank_json,
        _anchors_json(concept="bloqueio do SERT por ISRS"),
        rerank_json,
    ])
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)
    _mock_httpx(
        monkeypatch,
        json_responses={"commons.wikimedia.org": _wiki_image_response()},
        bytes_response=_png_bytes(),
    )

    rc = run_agent.main([str(note1), str(note2), "--config", str(cfg)])

    assert rc == 0
    assert len(queue.calls) == 4
    assert "![[" in note1.read_text(encoding="utf-8")
    assert "![[" in note2.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "[nota 1/2]" in out
    assert "[nota 2/2]" in out
    assert "Resumo final" in out
    assert "Enriquecidas: 2" in out
    assert "Falhas: 0" in out


def test_orquestrador_batch_continua_apos_falha(monkeypatch, tmp_path, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db)
    bad = tmp_path / "sem_headings.md"
    good = tmp_path / "ok.md"
    bad.write_text("texto sem heading\n", encoding="utf-8")
    good.write_text("# T\n\n## S\n\nbody.\n", encoding="utf-8")

    queue = GeminiQueue([json.dumps([])])
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)

    rc = run_agent.main([str(bad), str(good), "--config", str(cfg)])

    assert rc == 6
    assert len(queue.calls) == 1
    captured = capsys.readouterr()
    assert "nota sem headings" in captured.err
    assert "[nota 2/2]" in captured.out
    assert "Sem inserção: 1" in captured.out
    assert "Falhas: 1" in captured.out


def test_orquestrador_cota_serpapi_interrompe_lote(monkeypatch, tmp_path, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db, sources=["web_search"])
    note1 = tmp_path / "n1.md"
    note2 = tmp_path / "n2.md"
    note1.write_text("# T\n\n## S\n\nbody.\n", encoding="utf-8")
    note2.write_text("# T\n\n## S\n\nbody.\n", encoding="utf-8")

    anchors_json = json.dumps([{
        "section_path": ["T", "S"],
        "concept": "x",
        "visual_type": "diagram",
        "search_queries": ["q"],
        "anchor_id": "a1",
    }])
    queue = GeminiQueue([anchors_json])
    monkeypatch.setattr(run_agent, "_invoke_gemini", queue)
    search_calls = 0

    def quota_search(*_args, **_kwargs):
        nonlocal search_calls
        search_calls += 1
        raise run_agent.SourceQuotaExceeded(
            "web_search",
            "SerpAPI bloqueou a busca por cota/limite: quota exceeded",
        )

    monkeypatch.setattr(run_agent.web_search, "search", quota_search)

    rc = run_agent.main([str(note1), str(note2), "--config", str(cfg)])

    assert rc == 9
    assert search_calls == 1
    assert len(queue.calls) == 1
    captured = capsys.readouterr()
    assert "Interrompendo o lote" in captured.err
    assert "[nota 2/2]" not in captured.out
    assert "Falhas: 1" in captured.out


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
    assert "gemini falhou ao gerar âncoras" in capsys.readouterr().err


def test_orquestrador_timeout_de_anchors_retorna_7(monkeypatch, tmp_path, capsys):
    vault = tmp_path / "vault"
    cache_db = tmp_path / "c.db"
    cfg = _write_config(tmp_path, vault=vault, cache_db=cache_db)
    note = tmp_path / "n.md"
    note.write_text("# T\n\n## S\n\nbody.\n", encoding="utf-8")

    def timeout(*_args, **_kwargs):
        raise run_agent.GeminiError("gemini CLI excedeu timeout de 42s")

    monkeypatch.setattr(run_agent, "_invoke_gemini", timeout)

    rc = run_agent.main([str(note), "--config", str(cfg)])
    assert rc == 7
    assert "timeout de 42s" in capsys.readouterr().err
