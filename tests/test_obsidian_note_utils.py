import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "extension" / "scripts" / "mednotes" / "obsidian_note_utils.py"

spec = importlib.util.spec_from_file_location("obsidian_note_utils", SCRIPT)
assert spec is not None
obsidian_note_utils = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(obsidian_note_utils)


def test_deeplink_can_emit_portable_vault_and_file_uri(tmp_path: Path):
    vault = tmp_path / "Wiki Medicina"
    (vault / ".obsidian").mkdir(parents=True)
    note = vault / "Cardiologia" / "Ponte Miocardica.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Ponte\n", encoding="utf-8")

    deeplink = obsidian_note_utils.obsidian_deeplink(note, absolute_path=False)

    assert deeplink == (
        "obsidian://open?"
        f"vault={quote('Wiki Medicina', safe='')}&"
        f"file={quote('Cardiologia/Ponte Miocardica.md', safe='')}"
    )
    assert "%20" in deeplink
    assert "%2F" in deeplink


def test_deeplink_uses_absolute_real_path_by_default(tmp_path: Path):
    note = tmp_path / "nota.md"
    note.write_text("# Nota\n", encoding="utf-8")

    deeplink = obsidian_note_utils.obsidian_deeplink(note)

    assert deeplink == f"obsidian://open?path={quote(str(note.resolve()), safe='')}"


def test_deeplink_falls_back_to_absolute_path_without_vault(tmp_path: Path):
    note = tmp_path / "solta.md"
    note.write_text("# Nota\n", encoding="utf-8")

    deeplink = obsidian_note_utils.obsidian_deeplink(note)

    assert deeplink == f"obsidian://open?path={quote(str(note.resolve()), safe='')}"


def test_add_tag_creates_frontmatter_when_missing(tmp_path: Path):
    note = tmp_path / "nota.md"
    note.write_text("# Nota\n", encoding="utf-8")

    result = obsidian_note_utils.mutate_note_tag(note, "anki", "add-tag")

    assert result["changed"] is True
    assert result["tags"] == ["anki"]
    assert note.read_text(encoding="utf-8") == "---\ntags:\n  - anki\n---\n# Nota\n"


def test_add_tag_preserves_existing_tags_and_dedupes(tmp_path: Path):
    note = tmp_path / "nota.md"
    note.write_text("---\ntitle: Ponte\ntags: [cardio, #anki]\n---\n# Nota\n", encoding="utf-8")

    result = obsidian_note_utils.mutate_note_tag(note, "#anki", "add-tag")

    assert result["tags"] == ["cardio", "anki"]
    assert note.read_text(encoding="utf-8") == (
        "---\ntitle: Ponte\ntags:\n  - cardio\n  - anki\n---\n# Nota\n"
    )


def test_remove_tag_is_idempotent_and_removes_empty_field(tmp_path: Path):
    note = tmp_path / "nota.md"
    note.write_text("---\ntags:\n  - anki\n---\n# Nota\n", encoding="utf-8")

    first = obsidian_note_utils.mutate_note_tag(note, "anki", "remove-tag")
    second = obsidian_note_utils.mutate_note_tag(note, "anki", "remove-tag")

    assert first["changed"] is True
    assert first["tags"] == []
    assert second["changed"] is False
    assert note.read_text(encoding="utf-8") == "# Nota\n"


def test_cli_emits_json_for_deeplink_and_tag_mutation(tmp_path: Path):
    (tmp_path / ".obsidian").mkdir()
    note = tmp_path / "nota.md"
    note.write_text("# Nota\n", encoding="utf-8")

    link = subprocess.run(
        [sys.executable, str(SCRIPT), "deeplink", str(note)],
        text=True,
        capture_output=True,
        check=True,
    )
    link_vault_file = subprocess.run(
        [sys.executable, str(SCRIPT), "deeplink", "--vault-file", str(note)],
        text=True,
        capture_output=True,
        check=True,
    )
    add = subprocess.run(
        [sys.executable, str(SCRIPT), "add-tag", "--tag", "anki", str(note)],
        text=True,
        capture_output=True,
        check=True,
    )
    remove = subprocess.run(
        [sys.executable, str(SCRIPT), "remove-tag", "--tag", "anki", str(note)],
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(link.stdout)[0]["deeplink"].startswith("obsidian://open?path=")
    assert json.loads(link_vault_file.stdout)[0]["deeplink"].startswith("obsidian://open?vault=")
    assert json.loads(add.stdout)[0]["changed"] is True
    assert json.loads(remove.stdout)[0]["tags"] == []
