import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "extension" / "scripts" / "mednotes" / "flashcards" / "install_models.py"
TEMPLATES_DIR = ROOT / "extension" / "knowledge" / "anki-templates"


def _run(*args: str, input_json: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=json.dumps(input_json) if input_json is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ensure_creates_both_models_when_missing():
    result = _run("ensure", "--existing", "-", "--output", "-", input_json={"models": {}})

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    actions = plan["actions"]
    creates = [a for a in actions if a["operation"] == "createModel"]
    models = sorted(a["model"] for a in creates)
    assert models == ["Medicina", "Medicina Cloze"]
    cloze = next(a for a in creates if a["model"] == "Medicina Cloze")
    assert cloze["arguments"]["isCloze"] is True
    assert cloze["arguments"]["inOrderFields"] == ["Texto", "Verso Extra", "Obsidian"]
    qa = next(a for a in creates if a["model"] == "Medicina")
    assert qa["arguments"]["isCloze"] is False
    assert qa["arguments"]["inOrderFields"] == ["Frente", "Verso", "Verso Extra", "Obsidian"]


def test_ensure_no_op_when_present_and_fingerprint_matches():
    first = _run("ensure", "--existing", "-", "--output", "-", input_json={"models": {}})
    plan = json.loads(first.stdout)
    fingerprints = plan["fingerprints"]

    existing = {
        "models": {
            "Medicina": ["Frente", "Verso", "Verso Extra", "Obsidian"],
            "Medicina Cloze": ["Texto", "Verso Extra", "Obsidian"],
        },
        "fingerprints": fingerprints,
    }
    result = _run("ensure", "--existing", "-", "--output", "-", input_json=existing)

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["actions"] == []
    assert plan["blocked"] is False


def test_ensure_updates_when_fingerprint_changes():
    existing = {
        "models": {
            "Medicina": ["Frente", "Verso", "Verso Extra", "Obsidian"],
            "Medicina Cloze": ["Texto", "Verso Extra", "Obsidian"],
        },
        "fingerprints": {"Medicina": "stale", "Medicina Cloze": "stale"},
    }
    result = _run("ensure", "--existing", "-", "--output", "-", input_json=existing)

    plan = json.loads(result.stdout)
    operations = sorted({a["operation"] for a in plan["actions"]})
    assert operations == ["updateModelStyling", "updateModelTemplates"]


def test_ensure_blocks_when_existing_model_has_incompatible_fields():
    existing = {
        "models": {
            "Medicina": ["Front", "Back"],
            "Medicina Cloze": ["Texto", "Verso Extra", "Obsidian"],
        },
        "fingerprints": {},
    }
    result = _run("ensure", "--existing", "-", "--output", "-", input_json=existing)

    plan = json.loads(result.stdout)
    assert plan["blocked"] is True
    blocked = [a for a in plan["actions"] if a["operation"] == "blocked"]
    assert blocked and blocked[0]["model"] == "Medicina"


def test_templates_dir_contains_expected_files():
    expected = {"style.css", "qa.front.html", "qa.back.html", "cloze.front.html", "cloze.back.html"}
    actual = {p.name for p in TEMPLATES_DIR.iterdir()}
    assert expected.issubset(actual)
