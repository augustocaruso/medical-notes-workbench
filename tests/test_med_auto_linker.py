import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINKER_PATH = ROOT / "extension" / "scripts" / "mednotes" / "med_linker.py"


spec = importlib.util.spec_from_file_location("med_linker", LINKER_PATH)
med_linker = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["med_linker"] = med_linker
spec.loader.exec_module(med_linker)


def test_extract_aliases_inline_and_multiline():
    inline = "---\naliases: [IAM, Infarto Agudo do Miocárdio]\n---\n# Nota\n"
    multiline = "---\naliases:\n  - SDR\n  - Síndrome do Desconforto Respiratório\n---\n# Nota\n"

    assert med_linker.extract_aliases(inline) == ["IAM", "Infarto Agudo do Miocárdio"]
    assert med_linker.extract_aliases(multiline) == ["SDR", "Síndrome do Desconforto Respiratório"]


def test_default_catalog_path_uses_gemini_persistent_data_dir():
    assert med_linker.DEFAULT_CATALOG_PATH == "~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json"


def test_expand_path_expands_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDNOTES_TMP", str(tmp_path))

    assert med_linker.expand_path("$MEDNOTES_TMP/CATALOGO_WIKI.json") == tmp_path / "CATALOGO_WIKI.json"


def test_linker_uses_aliases_longest_match_and_skips_headings(tmp_path):
    wiki = tmp_path / "wiki"
    target = wiki / "Cardiologia" / "Infarto Agudo do Miocardio.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\naliases: [IAM]\n---\n# Infarto\n", encoding="utf-8")
    source = wiki / "Emergencia" / "Dor toracica.md"
    source.parent.mkdir(parents=True)
    source.write_text("# IAM\n\nIAM deve ser avaliado rapidamente.\n", encoding="utf-8")

    vocab = med_linker.build_vocabulary(wiki)
    plan = med_linker.link_file(source, vocab)

    assert plan.changed is True
    text = source.read_text(encoding="utf-8")
    assert "# IAM" in text
    assert "[[Infarto Agudo do Miocardio|IAM]] deve" in text


def test_linker_uses_catalog_as_primary_vocabulary(tmp_path):
    wiki = tmp_path / "wiki"
    target = wiki / "Psiquiatria" / "Acatisia por Lurasidona.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Acatisia\n", encoding="utf-8")
    source = wiki / "Psiquiatria" / "Antipsicoticos.md"
    source.write_text("A inquietação motora pode ocorrer com antipsicóticos.\n", encoding="utf-8")
    catalog = tmp_path / "CATALOGO_WIKI.json"
    catalog.write_text(
        json.dumps(
            {
                "entities": [
                    {
                        "arquivo": "Psiquiatria/Acatisia por Lurasidona.md",
                        "aliases": ["inquietação motora"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    vocab = med_linker.build_vocabulary(wiki, catalog_path=catalog)
    plan = med_linker.link_file(source, vocab)

    assert any(item.source == "catalog" for item in plan.insertions)
    assert "[[Acatisia por Lurasidona|inquietação motora]]" in source.read_text(encoding="utf-8")


def test_linker_dry_run_json_does_not_write(tmp_path, capsys):
    wiki = tmp_path / "wiki"
    target = wiki / "Cardiologia" / "Infarto.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\naliases: [IAM]\n---\n# Infarto\n", encoding="utf-8")
    source = wiki / "Emergencia" / "Dor.md"
    source.parent.mkdir(parents=True)
    source.write_text("IAM deve ser lembrado.\n", encoding="utf-8")

    rc = med_linker.run(wiki, dry_run=True, json_output=True, verify=False)

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["links_planned"] == 1
    assert "[[" not in source.read_text(encoding="utf-8")


def test_linker_skips_existing_links_and_code_blocks(tmp_path):
    wiki = tmp_path / "wiki"
    target = wiki / "Cardiologia" / "Infarto.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\naliases: [IAM]\n---\n# Infarto\n", encoding="utf-8")
    source = wiki / "Emergencia" / "Dor.md"
    source.parent.mkdir(parents=True)
    source.write_text("[[Infarto|IAM]]\n\n```text\nIAM\n```\n\nIAM fora do bloco.\n", encoding="utf-8")

    vocab = med_linker.build_vocabulary(wiki)
    plan = med_linker.link_file(source, vocab)

    text = source.read_text(encoding="utf-8")
    assert text.count("[[Infarto|IAM]]") == 2
    assert "```text\nIAM\n```" in text
    assert len(plan.insertions) == 1


def test_linker_skips_related_section_and_escapes_table_alias_pipe(tmp_path):
    wiki = tmp_path / "wiki"
    target = wiki / "Cardiologia" / "Infarto.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\naliases: [IAM]\n---\n# Infarto\n", encoding="utf-8")
    source = wiki / "Emergencia" / "Dor.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "| Tema | Conduta |\n| --- | --- |\n| IAM | ECG |\n\n## 🔗 Notas Relacionadas\n- IAM\n",
        encoding="utf-8",
    )

    vocab = med_linker.build_vocabulary(wiki)
    plan = med_linker.link_file(source, vocab)

    text = source.read_text(encoding="utf-8")
    assert "[[Infarto\\|IAM]]" in text
    assert "## 🔗 Notas Relacionadas\n- IAM\n" in text
    assert len(plan.insertions) == 1


def test_linker_blocks_apply_when_graph_has_existing_dangling_link(tmp_path, capsys):
    wiki = tmp_path / "wiki"
    target = wiki / "Cardiologia" / "Infarto.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\naliases: [IAM]\n---\n# Infarto\n", encoding="utf-8")
    source = wiki / "Emergencia" / "Dor.md"
    source.parent.mkdir(parents=True)
    source.write_text("IAM deve ser lembrado. Link quebrado: [[Fantasma]].\n", encoding="utf-8")

    rc = med_linker.run(wiki, dry_run=False, json_output=True, verify=False)
    out = json.loads(capsys.readouterr().out)

    assert rc == 3
    assert out["blocked"] is True
    assert out["blocker_count"] == 1
    assert "[[Infarto|IAM]]" not in source.read_text(encoding="utf-8")


def test_linker_run_missing_wiki_returns_4(tmp_path):
    assert med_linker.run(tmp_path / "missing", verify=False) == 4
