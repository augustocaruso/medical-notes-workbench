import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "extension" / "scripts" / "mednotes"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wiki import graph as wiki_graph  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_graph_audit_reports_dangling_self_alias_conflict_and_missing_catalog_target(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    _write(
        wiki / "ISRS.md",
        "# ISRS\n\nTexto com [[Transtorno Depressivo Maior]].\n\n## 🔗 Notas Relacionadas\n- [[Fantasma]]\n- [[ISRS]]\n",
    )
    _write(wiki / "Transtorno Depressivo Maior.md", "# TDM\n\n## 🔗 Notas Relacionadas\n- [[ISRS]]\n")
    catalog = tmp_path / "CATALOGO_WIKI.json"
    catalog.write_text(
        json.dumps(
            {
                "entities": [
                    {"arquivo": "ISRS.md", "aliases": ["TDM"]},
                    {"arquivo": "Transtorno Depressivo Maior.md", "aliases": ["TDM"]},
                    {"arquivo": "Nota Inexistente.md", "aliases": ["NIX"]},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = wiki_graph.audit_wiki_graph(wiki, catalog_path=catalog)
    codes = {item["code"] for item in report["errors"]}

    assert report["ok"] is False
    assert {"dangling_link", "self_link", "alias_conflict", "catalog_target_missing"} <= codes


def test_graph_audit_accepts_no_strong_related_links_marker(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    _write(
        wiki / "Tema Raro.md",
        "# Tema Raro\n\n## 🔗 Notas Relacionadas\n- Sem conexões fortes no catálogo atual.\n",
    )

    report = wiki_graph.audit_wiki_graph(wiki)
    warning_codes = {item["code"] for item in report["warnings"]}

    assert "few_related_links" not in warning_codes


def test_graph_audit_ignores_index_note_and_links_to_index(tmp_path):
    wiki = tmp_path / "Wiki_Medicina"
    _write(wiki / "_indice_medicina.md", "# Índice\n\n- [[ISRS]]\n")
    _write(
        wiki / "ISRS.md",
        "# ISRS\n\nTexto com [[_indice_medicina]].\n\n## 🔗 Notas Relacionadas\n- Sem conexões fortes no catálogo atual.\n",
    )

    report = wiki_graph.audit_wiki_graph(wiki)
    warnings = {(item["code"], item.get("file"), item.get("target")) for item in report["warnings"]}
    errors = {(item["code"], item.get("file"), item.get("target")) for item in report["errors"]}

    assert ("missing_related_section", "_indice_medicina.md", None) not in warnings
    assert ("orphan_note", "_indice_medicina.md", None) not in warnings
    assert ("dangling_link", "ISRS.md", "_indice_medicina") not in errors
