import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "extension" / "scripts" / "mednotes" / "sync_anki_twenty_rules.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_sync_check_reports_equal_prompts(tmp_path: Path):
    local = tmp_path / "local.md"
    upstream = tmp_path / "upstream.md"
    local.write_text("twenty rules\n", encoding="utf-8")
    upstream.write_text("twenty rules\n", encoding="utf-8")

    result = _run("check", "--local", str(local), "--source", str(upstream), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["changed"] is False
    assert payload["diff"] == ""


def test_sync_check_reports_diff(tmp_path: Path):
    local = tmp_path / "local.md"
    upstream = tmp_path / "upstream.md"
    local.write_text("old\n", encoding="utf-8")
    upstream.write_text("new\n", encoding="utf-8")

    result = _run("check", "--local", str(local), "--source", str(upstream))

    assert result.returncode == 1
    assert "-old" in result.stdout
    assert "+new" in result.stdout


def test_sync_write_updates_local_prompt(tmp_path: Path):
    local = tmp_path / "local.md"
    upstream = tmp_path / "upstream.md"
    local.write_text("old\n", encoding="utf-8")
    upstream.write_text("new\n", encoding="utf-8")

    result = _run("write", "--local", str(local), "--source", str(upstream))

    assert result.returncode == 0, result.stderr
    assert local.read_text(encoding="utf-8") == "new\n"
    assert json.loads(result.stdout)["written"] is True
