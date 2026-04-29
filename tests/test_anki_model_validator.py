import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "extension" / "scripts" / "mednotes" / "anki_model_validator.py"


def _run(payload: dict, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "validate", "--models-json", "-", *args],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def test_validator_accepts_compatible_model():
    payload = {"Medicina": ["Frente", "Verso", "Verso Extra", "Obsidian"]}

    result = _run(payload)

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["model"] == "Medicina"


def test_validator_reports_missing_fields():
    payload = {"Basic": ["Front", "Back"]}

    result = _run(payload)

    assert result.returncode == 3
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["checked_models"][0]["missing_fields"] == [
        "Frente",
        "Verso",
        "Verso Extra",
        "Obsidian",
    ]


def test_validator_falls_back_when_preferred_model_is_incomplete():
    payload = {
        "models": [
            {"name": "Basic", "fields": ["Front", "Back"]},
            {"name": "Medicina", "fields": ["Frente", "Verso", "Verso Extra", "Obsidian"]},
        ]
    }

    result = _run(payload, "--preferred-model", "Basic")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["model"] == "Medicina"
    assert "Preferred model" in data["warning"]
