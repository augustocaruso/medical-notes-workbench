import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "extension" / "scripts" / "mednotes" / "flashcards" / "report.py"


def _run(payload: dict, *args: str, command: str = "final") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), command, "--input", "-", *args],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def test_final_report_summarizes_created_duplicates_skips_and_model_errors():
    payload = {
        "source_manifest": {
            "skipped_notes": [{"vault_relative_path": "Cardio/Feito.md", "skip_reason": "skip_tag"}]
        },
        "accepted_cards": [
            {"source_path": "/vault/Cardio/Novo.md", "fields": {"Frente": "Q1"}},
            {"source_path": "/vault/Cardio/Novo.md", "fields": {"Frente": "Q2"}},
        ],
        "index_check": {"duplicate_cards": [{"card_hash": "abc"}]},
        "model_validation": {"ok": False, "required_fields": ["Frente", "Verso", "Obsidian"]},
        "anki_errors": ["addNotes failed"],
    }

    result = _run(payload)

    assert result.returncode == 0, result.stderr
    assert "- Notas processadas: 1" in result.stdout
    assert "- Cards criados: 2" in result.stdout
    assert "- Cards pulados por duplicidade: 1" in result.stdout
    assert "- Notas puladas: 1" in result.stdout
    assert "- Erros de modelo/campos: 1" in result.stdout
    assert "- Erros do Anki MCP: 1" in result.stdout
    assert "- /vault/Cardio/Novo.md" in result.stdout
    assert "- Cardio/Feito.md (skip_tag)" in result.stdout


def test_final_report_can_emit_json():
    result = _run({"accepted_cards": [{"source_path": "/vault/A.md"}]}, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == "medical-notes-workbench.flashcard-report.v1"
    assert payload["summary"]["processed_note_count"] == 1
    assert payload["summary"]["created_card_count"] == 1


def test_preview_cards_formats_new_cards_before_writing():
    payload = {
        "new_cards": [
            {
                "source_path": "/vault/Cardio/Ponte.md",
                "deck": "Wiki_Medicina::Cardio::Ponte",
                "note_model": "Medicina",
                "fields": {
                    "Frente": "O que e ponte miocardica?",
                    "Verso": "Tunelizacao intramiocardica de uma coronaria.",
                    "Verso Extra": "\n\nGeralmente envolve a DA.",
                    "Obsidian": "obsidian://open?vault=Wiki_Medicina&file=Cardio%2FPonte.md",
                },
            }
        ],
        "duplicate_cards": [{"card_hash": "abc"}],
    }

    result = _run(payload, command="preview-cards")

    assert result.returncode == 0, result.stderr
    assert "Flashcards preview" in result.stdout
    assert "- Cards candidatos para criar: 1" in result.stdout
    assert "- Cards pulados por duplicidade local: 1" in result.stdout
    assert "Deck: Wiki_Medicina::Cardio::Ponte" in result.stdout
    assert "Frente: O que e ponte miocardica?" in result.stdout
    assert "Verso: Tunelizacao intramiocardica de uma coronaria." in result.stdout
    assert "Obsidian: obsidian://open?vault=Wiki_Medicina&file=Cardio%2FPonte.md" in result.stdout


def test_preview_cards_can_emit_json_from_index_check():
    result = _run(
        {"index_check": {"new_cards": [{"fields": {"Frente": "Q"}}], "duplicate_cards": []}},
        "--json",
        command="preview-cards",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == "medical-notes-workbench.flashcard-card-preview.v1"
    assert payload["summary"]["card_count"] == 1
