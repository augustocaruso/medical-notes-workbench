import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "extension" / "scripts" / "mednotes" / "flashcard_index.py"


def _run(*args: str, input_json: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=json.dumps(input_json) if input_json is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )


def _candidates() -> dict:
    return {
        "source_manifest": {
            "notes": [
                {
                    "path": "/vault/Cardiologia/Ponte.md",
                    "vault_relative_path": "Cardiologia/Ponte.md",
                    "content_sha256": "abc123",
                    "deck": "Wiki_Medicina::Cardiologia::Ponte",
                    "deeplink": "obsidian://open?vault=Wiki_Medicina&file=Cardiologia%2FPonte.md",
                }
            ]
        },
        "candidate_cards": [
            {
                "source_path": "/vault/Cardiologia/Ponte.md",
                "note_model": "Medicina",
                "fields": {
                    "Frente": "O que e ponte miocardica?",
                    "Verso": "Tunelizacao intramiocardica de uma arteria coronaria.",
                    "Verso Extra": "\n\nGeralmente envolve a DA.",
                },
            }
        ],
    }


def test_check_marks_new_card_and_enriches_from_source_manifest(tmp_path: Path):
    index = tmp_path / "FLASHCARDS_INDEX.json"

    result = _run("check", "--index", str(index), "--candidates", "-", input_json=_candidates())

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"] == {"candidate_count": 1, "duplicate_count": 0, "new_count": 1}
    card = payload["new_cards"][0]
    assert len(card["card_hash"]) == 64
    assert card["deck"] == "Wiki_Medicina::Cardiologia::Ponte"
    assert card["fields"]["Obsidian"].startswith("obsidian://open?")


def test_record_then_check_reports_duplicate(tmp_path: Path):
    index = tmp_path / "FLASHCARDS_INDEX.json"
    first = _run("check", "--index", str(index), "--candidates", "-", input_json=_candidates())
    new_cards = json.loads(first.stdout)["new_cards"]

    record = _run("record", "--index", str(index), "--accepted", "-", input_json={"accepted_cards": new_cards})
    second = _run("check", "--index", str(index), "--candidates", "-", input_json=_candidates())
    summary = _run("summary", "--index", str(index))

    assert record.returncode == 0, record.stderr
    assert json.loads(record.stdout)["summary"]["added_count"] == 1
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["summary"] == {
        "candidate_count": 1,
        "duplicate_count": 1,
        "new_count": 0,
    }
    assert summary.returncode == 0, summary.stderr
    assert json.loads(summary.stdout)["card_count"] == 1


def test_record_dry_run_does_not_write_index(tmp_path: Path):
    index = tmp_path / "FLASHCARDS_INDEX.json"

    result = _run(
        "record",
        "--index",
        str(index),
        "--accepted",
        "-",
        "--dry-run",
        input_json=_candidates(),
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["dry_run"] is True
    assert not index.exists()


def test_source_status_detects_new_unchanged_and_changed_sources(tmp_path: Path):
    index = tmp_path / "FLASHCARDS_INDEX.json"
    initial = _candidates()
    first = _run("check", "--index", str(index), "--candidates", "-", input_json=initial)
    new_cards = json.loads(first.stdout)["new_cards"]
    _run("record", "--index", str(index), "--accepted", "-", input_json={"accepted_cards": new_cards})

    manifest = {
        "notes": [
            {
                "path": "/vault/Cardiologia/Ponte.md",
                "vault_relative_path": "Cardiologia/Ponte.md",
                "content_sha256": "abc123",
            },
            {
                "path": "/vault/Cardiologia/Ponte Alterada.md",
                "vault_relative_path": "Cardiologia/Ponte Alterada.md",
                "content_sha256": "new-sha",
            },
        ]
    }
    changed_manifest = {
        "notes": [
            {
                "path": "/vault/Cardiologia/Ponte.md",
                "vault_relative_path": "Cardiologia/Ponte.md",
                "content_sha256": "changed-sha",
            }
        ]
    }

    unchanged = _run("source-status", "--index", str(index), "--manifest", "-", input_json=manifest)
    changed = _run("source-status", "--index", str(index), "--manifest", "-", input_json=changed_manifest)

    assert unchanged.returncode == 0, unchanged.stderr
    assert json.loads(unchanged.stdout)["summary"] == {
        "changed_count": 0,
        "new_count": 1,
        "unchanged_count": 1,
    }
    assert changed.returncode == 0, changed.stderr
    assert json.loads(changed.stdout)["sources"][0]["status"] == "changed"
