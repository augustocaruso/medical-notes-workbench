import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = ROOT / "extension" / "scripts" / "mednotes" / "wiki_note_style.py"
MED_OPS_PATH = ROOT / "extension" / "scripts" / "mednotes" / "med_ops.py"
FIXTURES = ROOT / "tests" / "fixtures"


spec = importlib.util.spec_from_file_location("wiki_note_style", STYLE_PATH)
wiki_note_style = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["wiki_note_style"] = wiki_note_style
spec.loader.exec_module(wiki_note_style)


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


def test_golden_wiki_style_fixtures_pass():
    for path in sorted(FIXTURES.glob("wiki_style_*.md")):
        content = path.read_text(encoding="utf-8")
        report = wiki_note_style.validate_note_style(content, title=_title_from_fixture(path), path=str(path))

        assert report["ok"], path
        assert report["errors"] == []


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

    before = wiki_note_style.validate_note_style(bad.read_text(encoding="utf-8"), title="Escore HEART")
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

    report = wiki_note_style.validate_note_style(content, title="Nota com Avisos")

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
    isrs_report = next(item for item in payload["reports"] if item["path"].endswith("ISRS.md"))
    assert isrs_report["wrote"] is True
    assert Path(isrs_report["backup"]).exists()
    fixed = note.read_text(encoding="utf-8")
    assert "## 🔎 Diagnóstico" in fixed
    assert "## 🏁 Fechamento" in fixed
    assert "## 🔗 Notas Relacionadas" in fixed
    assert "[[Cineangiocoronariografia (Cateterismo)|CATE]]" in fixed


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
    assert payload["taxonomy_audit"]["proposed_moves"][0]["source"] == "Cardiologia"
    assert payload["taxonomy_audit"]["proposed_moves"][0]["destination"] == "1. Clínica Médica/Cardiologia"
    assert (legacy / "FA.md").exists()


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
