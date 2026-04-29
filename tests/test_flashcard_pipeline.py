import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "extension" / "scripts" / "mednotes" / "flashcard_pipeline.py"


class FakeAnkiMcp:
    def __init__(self):
        self.find_queries: list[str] = []
        self.added_notes: list[dict] = []

    def modelFieldNames(self, model: str) -> list[str]:
        assert model == "Medicina"
        return ["Frente", "Verso", "Verso Extra", "Obsidian"]

    def findNotes(self, query: str) -> list[int]:
        self.find_queries.append(query)
        return []

    def addNotes(self, notes: list[dict]) -> list[int]:
        self.added_notes.extend(notes)
        return list(range(1001, 1001 + len(notes)))


def _run(*args: str, input_json: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=json.dumps(input_json),
        text=True,
        capture_output=True,
        check=False,
    )


def _run_payload() -> dict:
    return {
        "preferred_model": "Medicina",
        "models": {"Medicina": ["Frente", "Verso", "Verso Extra", "Obsidian"]},
        "source_manifest": {
            "notes": [
                {
                    "path": "/vault/Cardio/Ponte.md",
                    "vault_relative_path": "Cardio/Ponte.md",
                    "content_sha256": "sha-v1",
                    "deck": "Wiki_Medicina::Cardio::Ponte",
                    "deeplink": "obsidian://open?vault=Wiki_Medicina&file=Cardio%2FPonte.md",
                }
            ]
        },
        "candidate_cards": [
            {
                "source_path": "/vault/Cardio/Ponte.md",
                "source_content_sha256": "sha-v1",
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
    }


def test_prepare_apply_flow_with_mocked_anki_mcp(tmp_path: Path):
    index = tmp_path / "FLASHCARDS_INDEX.json"
    fake = FakeAnkiMcp()
    payload = _run_payload()
    payload["models"] = {"Medicina": fake.modelFieldNames("Medicina")}

    prepare = _run("prepare", "--index", str(index), "--input", "-", input_json=payload)
    plan = json.loads(prepare.stdout)
    for query in plan["anki_find_queries"]:
        assert fake.findNotes(query["query"]) == []
    accepted_ids = fake.addNotes(plan["anki_notes"])
    accepted_cards = [
        {**card, "anki_note_id": note_id}
        for card, note_id in zip(plan["new_cards"], accepted_ids, strict=True)
    ]
    apply = _run(
        "apply",
        "--index",
        str(index),
        "--input",
        "-",
        input_json={
            "source_manifest": payload["source_manifest"],
            "accepted_cards": accepted_cards,
            "index_check": plan["index_check"],
            "model_validation": plan["model_validation"],
        },
    )
    second_prepare = _run("prepare", "--index", str(index), "--input", "-", input_json=payload)

    assert prepare.returncode == 0, prepare.stderr
    assert plan["summary"]["new_count"] == 1
    assert plan["summary"]["anki_note_count"] == 1
    assert len(fake.find_queries) == 1
    assert len(fake.added_notes) == 1
    assert apply.returncode == 0, apply.stderr
    assert json.loads(apply.stdout)["report"]["summary"]["created_card_count"] == 1
    assert second_prepare.returncode == 0, second_prepare.stderr
    assert json.loads(second_prepare.stdout)["summary"]["duplicate_count"] == 1


def test_prepare_blocks_when_model_is_missing_required_fields(tmp_path: Path):
    payload = _run_payload()
    payload["models"] = {"Basic": ["Front", "Back"]}

    result = _run("prepare", "--index", str(tmp_path / "index.json"), "--input", "-", input_json=payload)

    assert result.returncode == 3
    plan = json.loads(result.stdout)
    assert plan["blocked"] is True
    assert plan["anki_notes"] == []


def test_prepare_flags_changed_sources_for_reprocessing_confirmation(tmp_path: Path):
    index = tmp_path / "FLASHCARDS_INDEX.json"
    payload = _run_payload()
    first = _run("prepare", "--index", str(index), "--input", "-", input_json=payload)
    first_plan = json.loads(first.stdout)
    _run(
        "apply",
        "--index",
        str(index),
        "--input",
        "-",
        input_json={"accepted_cards": first_plan["new_cards"], "source_manifest": payload["source_manifest"]},
    )
    changed_payload = _run_payload()
    changed_payload["source_manifest"]["notes"][0]["content_sha256"] = "sha-v2"
    changed_payload["candidate_cards"][0]["source_content_sha256"] = "sha-v2"

    result = _run("prepare", "--index", str(index), "--input", "-", input_json=changed_payload)

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["requires_reprocess_confirmation"] is True
    assert plan["changed_sources"][0]["status"] == "changed"
