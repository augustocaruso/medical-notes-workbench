import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "extension" / "scripts" / "mednotes"
MED_OPS_PATH = ROOT / "extension" / "scripts" / "mednotes" / "med_ops.py"
FIXTURES = ROOT / "tests" / "fixtures"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wiki import cli as wiki_cli  # noqa: E402
from wiki import note_style, raw_chats  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _raw_chat(tmp_path: Path, fonte_id: str = "chat123") -> Path:
    return _write(
        tmp_path / "raw.md",
        f"---\nstatus: triado\ntipo: medicina\nfonte_id: {fonte_id}\n---\nChat\n",
    )


def _title_from_fixture(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:]
    raise AssertionError(f"fixture has no title: {path}")


def _valid_note(title: str, related: str = "ISRS") -> str:
    return (
        f"# {title}\n\n"
        "Definição curta para manter o contrato visual.\n\n"
        "## 🧬 Visão Geral\n"
        "Texto.\n\n"
        "## 🏁 Fechamento\n\n"
        "### Resumo\n"
        "Resumo.\n\n"
        "### Key Points\n"
        "- Ponto.\n\n"
        "### Frase de Prova\n"
        "Frase.\n\n"
        "## 🔗 Notas Relacionadas\n"
        f"- [[{related}]]\n\n"
        "---\n"
        "[Chat Original](https://gemini.google.com/app/batch)\n"
        "[[_Índice_Medicina]]\n"
    )


def _archived_sources(payload: dict[str, object]) -> set[str]:
    sources: set[str] = set()
    for key in ("hygiene_pre_cleanup", "hygiene_cleanup"):
        cleanup = payload.get(key)
        if not isinstance(cleanup, dict):
            continue
        archived = cleanup.get("archived", [])
        if not isinstance(archived, list):
            continue
        sources.update(str(item.get("source")) for item in archived if isinstance(item, dict))
    return sources


def test_golden_wiki_style_fixtures_pass():
    for path in sorted(FIXTURES.glob("wiki_style_*.md")):
        content = path.read_text(encoding="utf-8")
        report = note_style.validate_note_style(content, title=_title_from_fixture(path), path=str(path))

        assert report["ok"], path
        assert report["errors"] == []


def test_style_requires_canonical_wiki_frontmatter():
    content = (
        "---\n"
        "title: ISRS\n"
        "tags: [medicina, psiquiatria]\n"
        "alias: [ISRS, Inibidores seletivos da recaptação de serotonina, ISRS]\n"
        "---\n\n"
        + _valid_note("ISRS", related="Depressão")
    )

    report = note_style.validate_note_style(content, title="ISRS")

    assert report["ok"] is False
    assert {item["code"] for item in report["errors"]} == {"frontmatter_not_canonical"}
    assert report["requires_llm_rewrite"] is False


def test_fix_note_normalizes_wiki_frontmatter_without_llm():
    content = (
        "---\n"
        "title: ISRS\n"
        "tags: [medicina, psiquiatria]\n"
        "sinonimos:\n"
        "  - ISRS\n"
        "  - Inibidores seletivos da recaptação de serotonina\n"
        "---\n\n"
        + _valid_note("ISRS", related="Depressão")
    )

    fixed, report = note_style.fix_note_style(content, title="ISRS")

    assert report["errors"] == []
    assert {"normalize_frontmatter_aliases", "normalize_frontmatter_tags", "remove_noncanonical_frontmatter_keys"} <= set(
        report["fixes_applied"]
    )
    assert fixed.startswith(
        "---\n"
        "aliases:\n"
        '  - "Inibidores seletivos da recaptação de serotonina"\n'
        "tags:\n"
        "  - medicina\n"
        "  - psiquiatria\n"
        "---\n"
        "# ISRS\n"
    )
    assert "title:" not in fixed
    assert "sinonimos:" not in fixed


def test_fix_note_preserves_flashcard_tags_and_enricher_frontmatter_blocks():
    content = (
        "---\n"
        "aliases: [PAC]\n"
        "tags: [revisar, #anki]\n"
        "images_enriched: true\n"
        "image_count: 2\n"
        "image_sources:\n"
        "  - source: wikimedia\n"
        "    count: 2\n"
        "---\n\n"
        + _valid_note("Pneumonia Adquirida na Comunidade", related="Sepse")
    )

    fixed, report = note_style.fix_note_style(content, title="Pneumonia Adquirida na Comunidade")

    assert report["errors"] == []
    assert fixed.startswith(
        "---\n"
        "aliases:\n"
        '  - "PAC"\n'
        "tags:\n"
        "  - revisar\n"
        "  - anki\n"
        "images_enriched: true\n"
        "image_count: 2\n"
        "image_sources:\n"
        "  - source: wikimedia\n"
        "    count: 2\n"
        "---\n"
        "# Pneumonia Adquirida na Comunidade\n"
    )


def test_style_blocks_structural_errors_and_requests_llm_rewrite(tmp_path):
    raw = _raw_chat(tmp_path)
    content = (
        "# ISRS\n\n"
        "Definição curta.\n\n"
        "## Diagnóstico\n"
        "Texto.\n\n"
        "## 🔗 Notas Relacionadas\n"
        "- [[Depressão]]\n\n"
        "---\n"
        "obsidian://open?vault=Wiki_Medicina&file=ISRS.md\n"
        "[[Indice_Medicina]]\n"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "validate-note",
            "--content",
            str(_write(tmp_path / "bad.md", content)),
            "--title",
            "ISRS",
            "--raw-file",
            str(raw),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    codes = {item["code"] for item in payload["errors"]}
    assert "h2_missing_emoji" in codes
    assert "missing_required_section" in codes
    assert "invalid_footer_link" in codes
    assert "invalid_footer" in codes
    assert payload["requires_llm_rewrite"] is True
    assert "Frase de Prova" in payload["rewrite_prompt"]


def test_fix_note_corrects_form_without_inventing_missing_content(tmp_path):
    raw = _raw_chat(tmp_path, fonte_id="fix123")
    bad = _write(
        tmp_path / "bad.md",
        "# ISRS\n\n"
        "Definição curta.\n\n"
        "## Diagnóstico\n"
        "Use a clínica e evite escrever [[Cineangiocoronariografia (Cateterismo)]]CATE solto.\n\n\n"
        "## Fechamento\n\n"
        "### Resumo\n"
        "Resumo.\n\n"
        "### Key Points\n"
        "- Ponto.\n\n"
        "### Frase de Prova\n"
        "ISRS exige seguimento e orientação de efeitos adversos.\n\n\n"
        "## Notas Relacionadas\n"
        "- [[Depressão]]\n\n"
        "obsidian://open?vault=Wiki_Medicina&file=ISRS.md\n",
    )
    output = tmp_path / "fixed.md"

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "fix-note",
            "--content",
            str(bad),
            "--title",
            "ISRS",
            "--raw-file",
            str(raw),
            "--output",
            str(output),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["errors"] == []
    assert {"add_known_heading_emojis", "fix_wikilink_alias_suffixes", "normalize_footer"} <= set(
        payload["fixes_applied"]
    )
    fixed = output.read_text(encoding="utf-8")
    assert "## 🔎 Diagnóstico" in fixed
    assert "## 🏁 Fechamento" in fixed
    assert "## 🔗 Notas Relacionadas" in fixed
    assert "[[Cineangiocoronariografia (Cateterismo)|CATE]]" in fixed
    assert "obsidian://" not in fixed
    assert fixed.endswith("[Chat Original](https://gemini.google.com/app/fix123)\n[[_Índice_Medicina]]\n")


def test_fix_note_spaces_callouts_and_normalizes_tables(tmp_path):
    raw = _raw_chat(tmp_path, fonte_id="heart123")
    bad = _write(
        tmp_path / "heart.md",
        "# Escore HEART\n\n"
        "Escore usado na avaliação inicial de dor torácica para estratificar risco e orientar alta ou internação.\n\n"
        "## ⚖️ Estratificação\n\n"
        "| Pontuação | Conduta Recomendada |          |\n"
        "| :-------- | :------------------ | -------- |\n"
        "| **0 a 3** | Alta ambulatorial.  |          |\n"
        "| **7 a 10** | Internação + [[Cineangiocoronariografia (Cateterismo) | CATE]]. |\n\n"
        "## ⚠️ Qual a pegadinha de prova?\n"
        "> [!tip] CATE no baixo risco\n"
        "> Não indicar cateterismo de urgência só por HEART baixo com fatores isolados.\n\n"
        "## 🏁 Fechamento\n\n"
        "### Resumo\n"
        "HEART baixo permite alta após exclusão de IAM.\n\n"
        "### Key Points\n"
        "- Tabela precisa renderizar em Obsidian.\n\n"
        "### Frase de Prova\n"
        "HEART baixo com troponina negativa favorece alta com investigação ambulatorial.\n\n"
        "## 🔗 Notas Relacionadas\n"
        "- [[Dor Torácica]]\n\n"
        "---\n"
        "[Chat Original](https://gemini.google.com/app/heart123)\n"
        "[[_Índice_Medicina]]\n",
    )
    output = tmp_path / "fixed.md"

    before = note_style.validate_note_style(bad.read_text(encoding="utf-8"), title="Escore HEART")
    before_codes = {item["code"] for item in before["errors"]}
    before_warnings = {item["code"] for item in before["warnings"]}
    assert "unescaped_wikilink_pipe_in_table" in before_codes
    assert "malformed_markdown_table" in before_codes
    assert "missing_blank_line_before_callout" in before_warnings

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "fix-note",
            "--content",
            str(bad),
            "--title",
            "Escore HEART",
            "--raw-file",
            str(raw),
            "--output",
            str(output),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["errors"] == []
    assert {"escape_wikilink_pipes_in_tables", "normalize_markdown_tables", "normalize_blank_lines"} <= set(
        payload["fixes_applied"]
    )
    fixed = output.read_text(encoding="utf-8")
    assert "[[Cineangiocoronariografia (Cateterismo)\\|CATE]]" in fixed
    assert "Conduta Recomendada |          |" not in fixed
    assert "## ⚠️ Qual a pegadinha de prova?\n\n> [!tip]" in fixed


def test_style_warnings_are_non_blocking(tmp_path):
    long_paragraph = " ".join(["texto"] * 140)
    content = (
        "# Nota com Avisos\n\n"
        "Definição curta.\n\n"
        "## 🎯 Quando Pensar\n"
        f"{long_paragraph}\n\n"
        "> [!tip] Um\n"
        "> A\n\n"
        "> [!warning] Dois\n"
        "> B\n\n"
        "> [!danger] Três\n"
        "> C\n\n"
        "## 🏁 Fechamento\n\n"
        "### Resumo\n"
        "Resumo.\n\n"
        "### Key Points\n"
        "- Ponto.\n\n"
        "### Frase de Prova\n"
        "Frase.\n\n\n"
        "## 🔗 Notas Relacionadas\n"
        "- [[Nota]]SIGLA\n\n"
        "---\n"
        "[Chat Original](https://gemini.google.com/app/warnings)\n"
        "[[_Índice_Medicina]]\n"
    )

    report = note_style.validate_note_style(content, title="Nota com Avisos")

    assert report["ok"] is True
    codes = {item["code"] for item in report["warnings"]}
    assert "long_paragraph" in codes
    assert "excessive_callouts" in codes
    assert "extra_blank_lines_before_related" in codes
    assert "malformed_wikilink_alias" in codes


def test_validate_wiki_audits_existing_notes_without_writing(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    _write(wiki / "Boa.md", (FIXTURES / "wiki_style_disease.md").read_text(encoding="utf-8"))
    _write(wiki / "Ruim.md", "# Ruim\n\n## Diagnóstico\nTexto.\n")

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki),
            "validate-wiki",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["file_count"] == 2
    assert payload["ok_count"] == 1
    assert payload["error_count"] == 1
    bad = next(item for item in payload["reports"] if item["path"].endswith("Ruim.md"))
    assert bad["errors"]


def test_validate_wiki_skips_generated_index_note(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    _write(wiki / "Boa.md", (FIXTURES / "wiki_style_disease.md").read_text(encoding="utf-8"))
    _write(wiki / "_Índice_Medicina.md", "# Índice Medicina\n\n## 🔗 Notas Indexadas\n- [[Boa]]\n")

    audit = note_style.validate_wiki_dir(wiki)
    index = next(item for item in audit["reports"] if item["path"].endswith("_Índice_Medicina.md"))

    assert audit["error_count"] == 0
    assert index["ok"] is True
    assert index["skipped"] is True
    assert index["skip_reason"] == "wiki_index"


def test_fix_wiki_dry_run_reports_batch_changes_without_writing(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    folder = wiki / "1. Clínica Médica" / "Cardiologia"
    note = _write(
        folder / "ISRS.md",
        "# ISRS\n\n"
        "Definição curta.\n\n"
        "## Diagnóstico\n"
        "Texto com [[Cineangiocoronariografia (Cateterismo)]]CATE.\n\n"
        "## Fechamento\n\n"
        "### Resumo\n"
        "Resumo.\n\n"
        "### Key Points\n"
        "- Ponto.\n\n"
        "### Frase de Prova\n"
        "Frase.\n\n"
        "## Notas Relacionadas\n"
        "- [[Depressão]]\n\n"
        "---\n"
        "[Chat Original](https://gemini.google.com/app/batch)\n"
            "[[_Índice_Medicina]]\n",
    )
    _write(folder / "Depressão.md", _valid_note("Depressão"))
    _write(folder / "Cineangiocoronariografia (Cateterismo).md", _valid_note("CATE"))
    original = note.read_text(encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki),
            "fix-wiki",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["changed_count"] == 1
    assert payload["written_count"] == 0
    assert payload["taxonomy_action_required"] is False
    assert payload["taxonomy_audit"]["dry_run_only"] is True
    isrs_report = next(item for item in payload["reports"] if item["path"].endswith("ISRS.md"))
    assert isrs_report["would_write"] is True
    assert note.read_text(encoding="utf-8") == original


def test_fix_wiki_apply_writes_batch_changes_and_can_backup(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    folder = wiki / "1. Clínica Médica" / "Cardiologia"
    note = _write(
        folder / "ISRS.md",
        "# ISRS\n\n"
        "Definição curta.\n\n"
        "## Diagnóstico\n"
        "Texto com [[Cineangiocoronariografia (Cateterismo)]]CATE.\n\n"
        "## Fechamento\n\n"
        "### Resumo\n"
        "Resumo.\n\n"
        "### Key Points\n"
        "- Ponto.\n\n"
        "### Frase de Prova\n"
        "Frase.\n\n"
        "## Notas Relacionadas\n"
        "- [[Depressão]]\n\n"
        "---\n"
        "[Chat Original](https://gemini.google.com/app/batch)\n"
            "[[_Índice_Medicina]]\n",
    )
    _write(folder / "Depressão.md", _valid_note("Depressão"))
    _write(folder / "Cineangiocoronariografia (Cateterismo).md", _valid_note("CATE"))

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki),
            "fix-wiki",
            "--apply",
            "--backup",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is False
    assert payload["changed_count"] == 1
    assert payload["written_count"] == 1
    assert payload["taxonomy_action_required"] is False
    assert payload["backup_policy"] == {"enabled": True, "retention_days": 14, "max_per_file": 3}
    assert payload["backup_cleanup"]["deleted_count"] == 0
    isrs_report = next(item for item in payload["reports"] if item["path"].endswith("ISRS.md"))
    assert isrs_report["wrote"] is True
    assert not Path(isrs_report["backup"]).exists()
    assert "1. Clínica Médica/Cardiologia/ISRS.md.bak" in _archived_sources(payload)
    assert payload["hygiene_after"]["bak_or_rewrite"] == 0
    fixed = note.read_text(encoding="utf-8")
    assert "## 🔎 Diagnóstico" in fixed
    assert "## 🏁 Fechamento" in fixed
    assert "## 🔗 Notas Relacionadas" in fixed
    assert "[[Cineangiocoronariografia (Cateterismo)|CATE]]" in fixed


def test_fix_wiki_cleans_stale_backups_rewrites_and_empty_dirs(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    folder = wiki / "1. Clínica Médica" / "Cardiologia"
    _write(folder / "ISRS.md", _valid_note("ISRS", related="Depressão"))
    _write(folder / "Depressão.md", _valid_note("Depressão", related="ISRS"))
    _write(folder / "ISRS.md.bak", "backup antigo\n")
    _write(folder / "rascunho.rewrite.md", "# Rascunho\n")
    (folder / "Grupo Vazio").mkdir(parents=True)
    (wiki / "attachments").mkdir(parents=True)

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki),
            "fix-wiki",
            "--apply",
            "--backup",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hygiene_before"]["bak_or_rewrite"] == 2
    assert payload["hygiene_after"]["bak_or_rewrite"] == 0
    assert payload["hygiene_after"]["empty_dirs"] == 0
    assert not list(wiki.rglob("*.bak*"))
    assert not list(wiki.rglob("*.rewrite*"))
    assert not (folder / "Grupo Vazio").exists()
    assert (wiki / "attachments").exists()
    assert {"1. Clínica Médica/Cardiologia/ISRS.md.bak", "1. Clínica Médica/Cardiologia/rascunho.rewrite.md"} <= _archived_sources(payload)


def test_fix_wiki_apply_reports_write_errors_without_traceback(monkeypatch, capsys, tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    folder = wiki / "1. Clínica Médica" / "Cardiologia"
    note = _write(
        folder / "ISRS.md",
        "# ISRS\n\n"
        "Definição curta.\n\n"
        "## Diagnóstico\n"
        "Texto.\n\n"
        "## 🏁 Fechamento\n\n"
        "### Resumo\n"
        "Resumo.\n\n"
        "### Key Points\n"
        "- Ponto.\n\n"
        "### Frase de Prova\n"
        "Frase.\n\n"
        "## 🔗 Notas Relacionadas\n"
        "- [[Depressão]]\n\n"
        "---\n"
        "[Chat Original](https://gemini.google.com/app/batch)\n"
        "[[_Índice_Medicina]]\n",
    )
    _write(folder / "Depressão.md", _valid_note("Depressão"))
    original = note.read_text(encoding="utf-8")

    def locked_replace(_src: object, _dst: object) -> None:
        raise PermissionError(13, "Acesso negado")

    monkeypatch.setattr(raw_chats.os, "replace", locked_replace)

    returncode = wiki_cli.main(
        [
            "--wiki-dir",
            str(wiki),
            "fix-wiki",
            "--apply",
            "--backup",
            "--json",
        ]
    )

    assert returncode == 5
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["write_error_count"] == 1
    assert payload["linker_skipped_reason"] == "write_errors"
    write_error = payload["write_errors"][0]
    assert write_error["operation"] == "fix_wiki_style"
    assert write_error["path"].endswith("ISRS.md")
    assert "Acesso negado" in write_error["error"]
    isrs_report = next(item for item in payload["reports"] if item["path"].endswith("ISRS.md"))
    assert isrs_report["wrote"] is False
    assert not Path(isrs_report["backup"]).exists()
    assert "1. Clínica Médica/Cardiologia/ISRS.md.bak" in _archived_sources(payload)
    assert payload["hygiene_after"]["bak_or_rewrite"] == 0
    assert note.read_text(encoding="utf-8") == original


def test_fix_wiki_apply_repairs_invalid_graph_links_before_linker(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    folder = wiki / "1. Clínica Médica" / "Psiquiatria"
    note = _write(
        folder / "ISRS.md",
        "# ISRS\n\n"
        "Definição curta para manter o contrato visual.\n\n"
        "## 🧬 Visão Geral\n"
        "Texto com [[Fantasma|termo fantasma]] e [[ISRS]] no corpo.\n\n"
        "## 🏁 Fechamento\n\n"
        "### Resumo\n"
        "Resumo.\n\n"
        "### Key Points\n"
        "- Ponto.\n\n"
        "### Frase de Prova\n"
        "Frase.\n\n"
        "## 🔗 Notas Relacionadas\n"
        "- [[Depressão]]\n"
        "- [[Fantasma]]\n"
        "- [[ISRS]]\n\n"
        "---\n"
        "[Chat Original](https://gemini.google.com/app/batch)\n"
        "[[_Índice_Medicina]]\n",
    )
    _write(folder / "Depressão.md", _valid_note("Depressão", related="ISRS"))

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki),
            "fix-wiki",
            "--apply",
            "--backup",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["graph_fix"]["changed_count"] == 1
    assert payload["graph_fix"]["written_count"] == 1
    assert payload["linker_applied"] is True
    fixed = note.read_text(encoding="utf-8")
    assert "[[Fantasma" not in fixed
    assert "[[ISRS]] no corpo" not in fixed
    assert "- [[Fantasma]]" not in fixed
    assert "- [[ISRS]]" not in fixed
    assert "termo fantasma" in fixed


def test_fix_wiki_turns_remaining_graph_blockers_into_resolution_routes(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    _write(wiki / "1. Clínica Médica" / "Psiquiatria" / "ISRS.md", _valid_note("ISRS", related="Depressão"))
    _write(
        wiki / "1. Clínica Médica" / "Farmacologia" / "ISRS.md",
        _valid_note("ISRS", related="Depressão").replace("Texto.", "Texto farmacológico diferente."),
    )
    _write(wiki / "1. Clínica Médica" / "Psiquiatria" / "Depressão.md", _valid_note("Depressão", related="ISRS"))

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki),
            "fix-wiki",
            "--apply",
            "--backup",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3, result.stderr
    payload = json.loads(result.stdout)
    assert payload["linker_skipped_reason"] == "graph_blockers"
    resolution = payload["blocker_resolution"]
    assert resolution["schema"] == "medical-notes-workbench.blocker-resolution.v1"
    assert resolution["linker_can_apply"] is False
    duplicate_route = next(item for item in resolution["groups"] if item["route"] == "duplicate_merge_required")
    assert duplicate_route["automatic"] is False
    assert duplicate_route["count"] == 1
    assert duplicate_route["sample"][0]["code"] == "duplicate_stem"
    assert "fundir conteúdo" in duplicate_route["next_action"]
    assert payload["status"] == "blocked"
    assert payload["safe_for_agent"] is True
    assert payload["human_decision_required"] is True
    assert payload["next_command"] is None
    assert payload["resume_command"]
    assert payload["human_decisions"][0]["kind"] == "duplicate_merge_required"
    assert Path(payload["compact_report_path"]).exists()
    assert Path(payload["full_report_path"]).exists()


def test_fix_wiki_rewrites_existing_alias_links_via_linker_catalog(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    folder = wiki / "1. Clínica Médica" / "Cardiologia"
    _write(folder / "Hipertensão Arterial Sistêmica.md", _valid_note("Hipertensão Arterial Sistêmica", related="HAS"))
    _write(folder / "HAS.md", _valid_note("HAS", related="Hipertensão Arterial Sistêmica"))
    source = _write(
        folder / "Seguimento.md",
        _valid_note("Seguimento", related="Hipertensão Arterial Sistêmica").replace(
            "Texto.",
            "Texto com [[HAS]] no seguimento.",
        ),
    )
    catalog = tmp_path / "CATALOGO_WIKI.json"
    catalog.write_text(
        json.dumps(
            {
                "entities": [
                    {
                        "arquivo": "Cardiologia/Hipertensão Arterial Sistêmica.md",
                        "aliases": ["HAS"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki),
            "--catalog-path",
            str(catalog),
            "fix-wiki",
            "--apply",
            "--backup",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["linker_applied"] is True
    assert payload["linker_dry_run"]["links_rewritten"] == 1
    assert "[[Hipertensão Arterial Sistêmica|HAS]]" in source.read_text(encoding="utf-8")


def test_fix_wiki_reports_taxonomy_issues_without_migrating(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    legacy = wiki / "Cardiologia"
    _write(legacy / "FA.md", _valid_note("FA", related="IAM"))
    _write(legacy / "IAM.md", _valid_note("IAM", related="FA"))

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki),
            "fix-wiki",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["taxonomy_action_required"] is True
    assert payload["taxonomy_issue_count"] == 1
    assert payload["taxonomy_proposed_move_count"] == 1


def test_fix_wiki_apply_migrates_taxonomy_before_linker(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    legacy = wiki / "Cardiologia"
    source = _write(
        legacy / "Seguimento.md",
        _valid_note("Seguimento", related="Controle").replace(
            "Texto.",
            "Texto sobre Hipertensão Arterial Sistêmica no retorno.",
        ),
    )
    _write(legacy / "Controle.md", _valid_note("Controle", related="Seguimento"))
    _write(legacy / "Hipertensão Arterial Sistêmica.md", _valid_note("Hipertensão Arterial Sistêmica", related="Seguimento"))

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki),
            "fix-wiki",
            "--apply",
            "--backup",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["taxonomy_action_required"] is False
    assert payload["taxonomy_applied_move_count"] == 1
    assert payload["blocker_resolution"]["linker_can_apply"] is True
    assert payload["linker_dry_run"]["links_planned"] >= 1
    assert payload["linker_applied"] is True
    assert payload["linker_skipped_reason"] == ""
    migrated_source = wiki / "1. Clínica Médica" / "Cardiologia" / "Seguimento.md"
    assert "[[Hipertensão Arterial Sistêmica]]" in migrated_source.read_text(encoding="utf-8")
    assert payload["taxonomy_initial_audit"]["proposed_moves"][0]["source"] == "Cardiologia"
    assert payload["taxonomy_initial_audit"]["proposed_moves"][0]["destination"] == "1. Clínica Médica/Cardiologia"
    assert not source.exists()
    assert migrated_source.exists()
    assert payload["rollback_command"]


def test_apply_style_rewrite_validates_and_replaces_existing_note(tmp_path):
    target = _write(
        tmp_path / "Wiki_Medicina" / "ISRS.md",
        "# ISRS\n\n## Diagnóstico\nTexto antigo.\n",
    )
    rewritten = _write(
        tmp_path / "rewrite.md",
        "# ISRS\n\n"
        "Antidepressivos usados em transtornos depressivos e ansiosos. Em prova, o foco é latência de efeito, efeitos adversos e orientação do paciente.\n\n"
        "## 🔎 Diagnóstico\n"
        "O uso é definido pelo diagnóstico clínico e pela indicação terapêutica, não por exame laboratorial específico.\n\n"
        "## 🩺 Conduta\n"
        "Oriente latência de resposta e efeitos adversos iniciais antes de trocar a medicação.\n\n"
        "## 🏁 Fechamento\n\n"
        "### Resumo\n"
        "ISRS são fármacos frequentes no manejo de depressão e ansiedade.\n\n"
        "### Key Points\n"
        "- Latência terapêutica é esperada.\n"
        "- Orientação reduz abandono.\n\n"
        "### Frase de Prova\n"
        "ISRS não devem ser julgados como falha terapêutica nos primeiros dias de uso.\n\n"
        "## 🔗 Notas Relacionadas\n"
        "- [[Depressão]]\n\n"
        "---\n"
        "[Chat Original](https://gemini.google.com/app/rewrite)\n"
        "[[_Índice_Medicina]]\n",
    )

    dry_run = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "apply-style-rewrite",
            "--target",
            str(target),
            "--content",
            str(rewritten),
            "--dry-run",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert dry_run.returncode == 0
    dry_payload = json.loads(dry_run.stdout)
    assert dry_payload["written"] is False
    assert "Texto antigo" in target.read_text(encoding="utf-8")

    applied = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "apply-style-rewrite",
            "--target",
            str(target),
            "--content",
            str(rewritten),
            "--backup",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert applied.returncode == 0
    payload = json.loads(applied.stdout)
    assert payload["written"] is True
    assert Path(payload["backup_path"]).exists()
    assert "Latência terapêutica" in target.read_text(encoding="utf-8")


def test_apply_style_rewrite_rejects_invalid_subagent_output(tmp_path):
    target = _write(tmp_path / "Wiki_Medicina" / "ISRS.md", "# ISRS\n\n## Diagnóstico\nTexto antigo.\n")
    rewritten = _write(tmp_path / "rewrite.md", "# ISRS\n\n## Diagnóstico\nTexto novo.\n")

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "apply-style-rewrite",
            "--target",
            str(target),
            "--content",
            str(rewritten),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["written"] is False
    assert payload["validation"]["errors"]
    assert "Texto antigo" in target.read_text(encoding="utf-8")
