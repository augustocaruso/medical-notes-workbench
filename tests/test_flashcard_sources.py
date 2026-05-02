import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "extension" / "scripts" / "mednotes" / "flashcards" / "sources.py"


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.pop("MED_WIKI_DIR", None)
    merged_env.pop("MEDNOTES_HOME", None)
    merged_env.pop("MEDNOTES_CONFIG", None)
    merged_env.pop("MEDICAL_NOTES_CONFIG", None)
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
        env=merged_env,
    )


def _note(path: Path, text: str = "# Nota\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_resolve_explicit_file_manifest_has_deck_deeplink_and_tags(tmp_path: Path):
    vault = tmp_path / "Wiki_Medicina"
    (vault / ".obsidian").mkdir(parents=True)
    note = _note(
        vault / "Cardiologia" / "Ponte Miocardica.md",
        "---\ntags: [cardio, #revisar]\n---\n# Ponte\ntexto #prova\n```\n#ignorar\n```\n",
    )

    result = _run("resolve", str(note), "--dry-run")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    record = payload["notes"][0]
    assert payload["schema"] == "medical-notes-workbench.flashcard-sources.v1"
    assert payload["dry_run"] is True
    assert record["deck"] == "Wiki_Medicina::Cardiologia::Ponte Miocardica"
    assert record["vault_relative_path"] == "Cardiologia/Ponte Miocardica.md"
    assert record["deeplink"] == f"obsidian://open?path={quote(str(note.resolve()), safe='')}"
    assert record["frontmatter_tags"] == ["cardio", "revisar"]
    assert record["inline_tags"] == ["prova"]
    assert record["tags"] == ["cardio", "revisar", "prova"]
    assert record["already_marked_anki"] is False
    assert record["link_mode"] == "absolute_path"
    assert len(record["content_sha256"]) == 64


def test_resolve_explicit_file_outside_vault_uses_absolute_path_deeplink(tmp_path: Path):
    note = _note(tmp_path / "Notas Soltas" / "Ponte Miocardica.md")

    result = _run("resolve", str(note), "--dry-run")

    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)["notes"][0]
    assert record["vault_root"] is None
    assert record["vault_name"] is None
    assert record["vault_relative_path"] == "Ponte Miocardica.md"
    assert record["link_mode"] == "absolute_path"
    assert record["deck"] == "Medicina::Notas Soltas::Ponte Miocardica"
    assert record["deeplink"] == f"obsidian://open?path={quote(str(note.resolve()), safe='')}"


def test_resolve_explicit_file_keeps_nearest_vault_metadata_but_links_real_path(tmp_path: Path):
    configured = tmp_path / "Wiki_Medicina"
    (configured / ".obsidian").mkdir(parents=True)
    other_vault = tmp_path / "Residencia"
    (other_vault / ".obsidian").mkdir(parents=True)
    note = _note(other_vault / "Cardiologia" / "Ponte.md")

    result = _run("resolve", str(note), env={"MED_WIKI_DIR": str(configured)})

    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)["notes"][0]
    assert record["vault_root"] == str(other_vault)
    assert record["vault_name"] == "Residencia"
    assert record["vault_relative_path"] == "Cardiologia/Ponte.md"
    assert record["link_mode"] == "absolute_path"
    assert record["deeplink"] == f"obsidian://open?path={quote(str(note.resolve()), safe='')}"


def test_resolve_directory_and_glob_ignore_generated_or_attachment_dirs(tmp_path: Path):
    vault = tmp_path / "Wiki_Medicina"
    (vault / ".obsidian").mkdir(parents=True)
    _note(vault / "Cardiologia" / "A.md")
    _note(vault / "Cardiologia" / "B.md")
    _note(vault / "Cardiologia" / "dist" / "Skip.md")
    _note(vault / "Cardiologia" / "attachments" / "Skip.md")
    (vault / "Cardiologia" / "image.png").write_bytes(b"png")

    result = _run("resolve", str(vault / "Cardiologia"))
    globbed = _run("resolve", str(vault / "Cardiologia" / "*.md"))

    assert result.returncode == 0, result.stderr
    assert globbed.returncode == 0, globbed.stderr
    paths = [Path(note["path"]).name for note in json.loads(result.stdout)["notes"]]
    glob_paths = [Path(note["path"]).name for note in json.loads(globbed.stdout)["notes"]]
    assert paths == ["A.md", "B.md"]
    assert glob_paths == ["A.md", "B.md"]


def test_resolve_scope_filters_by_tag_and_folder_name(tmp_path: Path):
    vault = tmp_path / "Wiki_Medicina"
    (vault / ".obsidian").mkdir(parents=True)
    _note(vault / "Cardiologia" / "A.md", "---\ntags:\n  - revisar\n---\n# A\n")
    _note(vault / "Cardiologia" / "B.md", "---\ntags:\n  - outro\n---\n# B\n")
    _note(vault / "Neuro" / "C.md", "---\ntags:\n  - revisar\n---\n# C\n")

    result = _run(
        "resolve",
        "--scope",
        "notas com tag #revisar na pasta Cardiologia",
        "--vault-root",
        str(vault),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [Path(note["path"]).name for note in payload["notes"]] == ["A.md"]
    assert payload["scope"]["tags"] == ["revisar"]
    assert payload["scope"]["folders"] == ["Cardiologia"]


def test_resolve_tag_scope_requires_search_root(tmp_path: Path):
    _note(tmp_path / "A.md", "---\ntags: [revisar]\n---\n# A\n")

    result = _run(
        "resolve",
        "--scope",
        "notas com tag #revisar",
        "--config",
        str(tmp_path / "missing-config.toml"),
    )

    assert result.returncode == 2
    assert "Tag filters need" in result.stderr


def test_resolve_tag_scope_uses_persistent_config(tmp_path: Path):
    vault = tmp_path / "Wiki_Medicina"
    (vault / ".obsidian").mkdir(parents=True)
    note = _note(vault / "Cardiologia" / "A.md", "---\ntags: [revisar]\n---\n# A\n")
    state = tmp_path / "state"
    state.mkdir()
    (state / "config.toml").write_text(
        "[chat_processor]\n"
        f'wiki_dir = "{vault}"\n',
        encoding="utf-8",
    )

    result = _run(
        "resolve",
        "--scope",
        "notas com tag #revisar",
        env={"MEDNOTES_HOME": str(state)},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [record["path"] for record in payload["notes"]] == [str(note)]


def test_resolve_free_text_scope_returns_empty_manifest_with_warning():
    result = _run("resolve", "--scope", "resuma esta explicacao em flashcards")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["file_count"] == 0
    assert payload["notes"] == []
    assert "pasted text" in payload["warnings"][0]


def test_resolve_scope_warns_about_unmatched_pathish_input(tmp_path: Path):
    missing = tmp_path / "missing.md"

    result = _run("resolve", "--scope", str(missing))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["notes"] == []
    assert f"No Markdown files matched input: {missing}" in payload["warnings"]


def test_resolve_can_skip_notes_with_reserved_anki_tag(tmp_path: Path):
    vault = tmp_path / "Wiki_Medicina"
    (vault / ".obsidian").mkdir(parents=True)
    _note(vault / "Cardiologia" / "Novo.md", "---\ntags: [revisar]\n---\n# Novo\n")
    _note(vault / "Cardiologia" / "Feito.md", "---\ntags: [revisar, anki]\n---\n# Feito\n")

    result = _run("resolve", str(vault / "Cardiologia"), "--skip-tag", "anki")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [Path(note["path"]).name for note in payload["notes"]] == ["Novo.md"]
    assert [Path(note["path"]).name for note in payload["skipped_notes"]] == ["Feito.md"]
    assert payload["skipped_notes"][0]["skip_reason"] == "skip_tag"
    assert payload["skipped_notes"][0]["skip_tags"] == ["anki"]
    assert payload["summary"]["candidate_file_count"] == 2
    assert payload["summary"]["file_count"] == 1
    assert payload["summary"]["skipped_count"] == 1


def test_resolve_includes_anki_tagged_notes_when_skip_tag_is_omitted(tmp_path: Path):
    vault = tmp_path / "Wiki_Medicina"
    (vault / ".obsidian").mkdir(parents=True)
    _note(vault / "Cardiologia" / "Feito.md", "---\ntags: [anki]\n---\n# Feito\n")

    result = _run("resolve", str(vault / "Cardiologia"))

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [Path(note["path"]).name for note in payload["notes"]] == ["Feito.md"]
    assert payload["notes"][0]["already_marked_anki"] is True
    assert payload["skipped_notes"] == []


def test_preview_emits_human_readable_summary(tmp_path: Path):
    vault = tmp_path / "Wiki_Medicina"
    (vault / ".obsidian").mkdir(parents=True)
    _note(vault / "Cardiologia" / "Novo.md", "---\ntags: [revisar]\n---\n# Novo\n")
    _note(vault / "Cardiologia" / "Feito.md", "---\ntags: [revisar, anki]\n---\n# Feito\n")

    result = _run(
        "preview",
        str(vault / "Cardiologia"),
        "--tag",
        "revisar",
        "--skip-tag",
        "anki",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Flashcard source preview\n")
    assert "- Processar: 1 nota(s)" in result.stdout
    assert "- Puladas: 1 nota(s)" in result.stdout
    assert "- Tags exigidas: revisar" in result.stdout
    assert "- Tags puladas: anki" in result.stdout
    assert "Notas que serao processadas:" in result.stdout
    assert "- Cardiologia/Novo.md -> Wiki_Medicina::Cardiologia::Novo" in result.stdout
    assert "Notas puladas:" in result.stdout
    assert "- Cardiologia/Feito.md (skip_tag: anki)" in result.stdout


def test_resolve_large_batch_sets_confirmation_flag(tmp_path: Path):
    vault = tmp_path / "Wiki_Medicina"
    (vault / ".obsidian").mkdir(parents=True)
    for idx in range(11):
        _note(vault / "Lote" / f"N{idx:02d}.md")

    result = _run("resolve", str(vault / "Lote"))

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)["summary"]
    assert summary["file_count"] == 11
    assert summary["requires_confirmation"] is True
    assert summary["confirmation_reasons"] == ["more_than_10_files"]
