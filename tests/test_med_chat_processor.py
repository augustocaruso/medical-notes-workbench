import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MED_OPS_PATH = ROOT / "extension" / "scripts" / "mednotes" / "med_ops.py"
WIKI_TREE_PATH = ROOT / "extension" / "scripts" / "mednotes" / "wiki_tree.py"


spec = importlib.util.spec_from_file_location("med_ops", MED_OPS_PATH)
med_ops = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["med_ops"] = med_ops
spec.loader.exec_module(med_ops)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _config(raw_dir: Path, wiki_dir: Path, linker_path: Path | None = None):
    return med_ops.MedConfig(
        raw_dir=raw_dir,
        wiki_dir=wiki_dir,
        linker_path=linker_path or (raw_dir.parent / "missing_linker.py"),
        catalog_path=raw_dir.parent / "missing_catalog.json",
    )


def _mkdir_canonical(wiki_dir: Path, taxonomy: str) -> Path:
    path = wiki_dir.joinpath(*taxonomy.split("/"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_update_frontmatter_creates_and_updates_keys():
    created = med_ops.update_frontmatter("Corpo\n", {"status": "triado", "titulo_triagem": "Acatisia"})
    assert created.startswith("---\n")
    assert "status: triado\n" in created
    assert "titulo_triagem: Acatisia\n" in created
    assert created.endswith("Corpo\n")

    updated = med_ops.update_frontmatter(created, {"status": "processado"})
    assert "status: processado\n" in updated
    assert "status: triado\n" not in updated
    assert "titulo_triagem: Acatisia\n" in updated


def test_default_catalog_path_uses_gemini_persistent_data_dir():
    assert med_ops.DEFAULT_CATALOG_PATH == "~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json"


def test_path_expands_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDNOTES_TMP", str(tmp_path))

    assert med_ops._path("$MEDNOTES_TMP/CATALOGO_WIKI.json") == tmp_path / "CATALOGO_WIKI.json"


def test_triage_mutates_raw_without_backup_by_default(tmp_path):
    raw = _write(tmp_path / "raw" / "chat.md", "Conteudo\n")

    result = med_ops.mutate_raw_frontmatter(
        raw,
        {
            "tipo": "medicina",
            "status": "triado",
            "data_importacao": "2026-04-28",
            "fonte_id": "abc",
            "titulo_triagem": "Acatisia por lurasidona",
        },
    )

    assert result["updated"] is True
    assert result["backup"] is None
    assert not (raw.parent / "chat.md.bak").exists()
    body = raw.read_text(encoding="utf-8")
    assert "status: triado" in body
    assert "tipo: medicina" in body
    assert "Conteudo" in body


def test_triage_can_create_backup_when_requested(tmp_path):
    raw = _write(tmp_path / "raw" / "chat.md", "Conteudo\n")

    result = med_ops.mutate_raw_frontmatter(raw, {"status": "triado"}, backup=True)

    assert result["updated"] is True
    assert Path(result["backup"]).exists()


def test_list_pending_and_triados(tmp_path):
    raw_dir = tmp_path / "raw"
    _write(raw_dir / "a.md", "Sem yaml\n")
    _write(raw_dir / "b.md", "---\nstatus: pendente\n---\nB\n")
    _write(raw_dir / "c.md", "---\nstatus: triado\ntipo: medicina\ntitulo_triagem: ISRS\n---\nC\n")
    _write(raw_dir / "d.md", "---\nstatus: triado\ntipo: outra\n---\nD\n")

    pending = med_ops.list_by_status(raw_dir, "pending")
    triados = med_ops.list_by_status(raw_dir, "triados")

    assert {Path(item["path"]).name for item in pending} == {"a.md", "b.md"}
    assert [Path(item["path"]).name for item in triados] == ["c.md"]
    assert triados[0]["titulo_triagem"] == "ISRS"


def test_taxonomy_validation_rejects_unsafe_paths():
    assert med_ops.normalize_taxonomy("Cardiologia/Arritmias") == ("Cardiologia", "Arritmias")
    assert med_ops.normalize_taxonomy(r"Cardiologia\Arritmias") == ("Cardiologia", "Arritmias")

    for value in ("../Segredo", "/abs/path", r"C:\Users\leona", "Cardio/A*:B", "Cardio/Cardio", "_"):
        try:
            med_ops.normalize_taxonomy(value)
        except med_ops.ValidationError:
            pass
        else:
            raise AssertionError(f"taxonomy should fail: {value}")


def test_taxonomy_tree_and_resolve_use_existing_folder_canonical_names(tmp_path):
    wiki_dir = tmp_path / "wiki"
    _write(wiki_dir / "1. Clínica Médica" / "Cardiologia" / "Arritmias" / "existente.md", "# Existente\n")
    _write(wiki_dir / "2. Cirurgia" / "Trauma" / "choque.md", "# Choque\n")

    tree = med_ops.taxonomy_tree(wiki_dir)
    assert {item["path"] for item in tree["directories"]} >= {
        "1. Clínica Médica",
        "1. Clínica Médica/Cardiologia",
        "1. Clínica Médica/Cardiologia/Arritmias",
        "2. Cirurgia",
        "2. Cirurgia/Trauma",
    }

    resolved = med_ops.resolve_taxonomy(wiki_dir, "cardiologia/arrítmias", title="Fibrilação Atrial")
    assert resolved.taxonomy == "1. Clínica Médica/Cardiologia/Arritmias"
    assert resolved.canonicalized == (
        {"from": "cardiologia", "to": "1. Clínica Médica/Cardiologia", "under": ""},
        {"from": "arrítmias", "to": "Arritmias", "under": "1. Clínica Médica/Cardiologia"},
    )


def test_resolve_taxonomy_rejects_new_intermediate_or_title_as_folder(tmp_path):
    wiki_dir = tmp_path / "wiki"
    _write(wiki_dir / "1. Clínica Médica" / "Cardiologia" / "Arritmias" / "existente.md", "# Existente\n")

    for taxonomy, title in (
        ("Cardiologia/Ritmo/Supraventriculares", "Taquicardia Supraventricular"),
        ("Cardiologia/Arritmias/Fibrilação Atrial", "Fibrilação Atrial"),
    ):
        try:
            med_ops.resolve_taxonomy(wiki_dir, taxonomy, title=title)
        except med_ops.ValidationError:
            pass
        else:
            raise AssertionError(f"taxonomy should fail: {taxonomy}")


def test_resolve_taxonomy_can_allow_one_explicit_new_leaf(tmp_path):
    wiki_dir = tmp_path / "wiki"
    _write(wiki_dir / "1. Clínica Médica" / "Cardiologia" / "Arritmias" / "existente.md", "# Existente\n")

    resolved = med_ops.resolve_taxonomy(
        wiki_dir,
        "Cardiologia/Eletrofisiologia",
        title="Estudo Eletrofisiológico",
        allow_new_leaf=True,
    )

    assert resolved.taxonomy == "1. Clínica Médica/Cardiologia/Eletrofisiologia"
    assert resolved.new_dirs == ("1. Clínica Médica/Cardiologia/Eletrofisiologia",)


def test_taxonomy_audit_maps_legacy_top_level_folders_to_canonical_plan(tmp_path):
    wiki_dir = tmp_path / "wiki"
    _write(wiki_dir / "Cardiologia" / "Arritmias" / "existente.md", "# Existente\n")
    _write(wiki_dir / "Clinica Medica" / "HAS.md", "# HAS\n")
    _write(wiki_dir / "Ginecologia_Obstetricia" / "Prenatal.md", "# Pré-natal\n")
    _write(wiki_dir / "Geral" / "misc.md", "# Misc\n")

    audit = med_ops.taxonomy_audit(wiki_dir)

    moves = {(item["source"], item["destination"]) for item in audit["proposed_moves"]}
    assert ("Cardiologia", "1. Clínica Médica/Cardiologia") in moves
    assert ("Clinica Medica", "1. Clínica Médica/Clínica Médica") in moves
    assert ("Ginecologia_Obstetricia", "3. Ginecologia e Obstetrícia/Ginecologia e Obstetrícia") in moves
    assert audit["unmapped_top_level_dirs"] == ["Geral"]
    assert audit["dry_run_only"] is True


def test_publish_batch_dry_run_writes_nothing(tmp_path):
    raw_dir = tmp_path / "raw"
    wiki_dir = tmp_path / "wiki"
    _mkdir_canonical(wiki_dir, "1. Clínica Médica/Psiquiatria")
    raw = _write(raw_dir / "chat.md", "---\nstatus: triado\ntipo: medicina\n---\nChat\n")
    content = _write(tmp_path / "tmp" / "nota.md", "---\naliases: [ISRS]\n---\n# Nota\n")
    manifest = _write(
        tmp_path / "manifest.json",
        json.dumps({"raw_file": str(raw), "notes": [{"taxonomy": "Psiquiatria", "title": "ISRS", "content_path": str(content)}]}),
    )

    result = med_ops.publish_batch(manifest, _config(raw_dir, wiki_dir), dry_run=True)

    assert result["dry_run"] is True
    assert result["created"] == []
    assert result["planned_batches"][0]["notes"][0]["target_path"].endswith("1. Clínica Médica/Psiquiatria/ISRS.md")
    assert not (wiki_dir / "1. Clínica Médica" / "Psiquiatria" / "ISRS.md").exists()
    assert "status: triado" in raw.read_text(encoding="utf-8")


def test_publish_batch_creates_notes_then_marks_raw_processed_without_backup(tmp_path):
    raw_dir = tmp_path / "raw"
    wiki_dir = tmp_path / "wiki"
    _mkdir_canonical(wiki_dir, "1. Clínica Médica/Psiquiatria")
    raw = _write(raw_dir / "chat.md", "---\nstatus: triado\ntipo: medicina\n---\nChat\n")
    content = _write(tmp_path / "tmp" / "nota.md", "---\naliases: [ISRS]\n---\n# Nota\n")
    manifest = _write(
        tmp_path / "manifest.json",
        json.dumps({"raw_file": str(raw), "notes": [{"taxonomy": "Psiquiatria", "title": "ISRS", "content_path": str(content)}]}),
    )

    result = med_ops.publish_batch(manifest, _config(raw_dir, wiki_dir))

    target = wiki_dir / "1. Clínica Médica" / "Psiquiatria" / "ISRS.md"
    assert target.exists()
    assert "# Nota" in target.read_text(encoding="utf-8")
    assert result["created_count"] == 1
    raw_text = raw.read_text(encoding="utf-8")
    assert "status: processado" in raw_text
    assert "processed_at:" in raw_text
    assert not (raw_dir / "chat.md.bak").exists()


def test_publish_batch_can_create_backup_when_requested(tmp_path):
    raw_dir = tmp_path / "raw"
    wiki_dir = tmp_path / "wiki"
    _mkdir_canonical(wiki_dir, "1. Clínica Médica/Psiquiatria")
    raw = _write(raw_dir / "chat.md", "---\nstatus: triado\ntipo: medicina\n---\nChat\n")
    content = _write(tmp_path / "tmp" / "nota.md", "# Nota\n")
    manifest = _write(
        tmp_path / "manifest.json",
        json.dumps({"raw_file": str(raw), "notes": [{"taxonomy": "Psiquiatria", "title": "ISRS", "content_path": str(content)}]}),
    )

    result = med_ops.publish_batch(manifest, _config(raw_dir, wiki_dir), backup=True)

    assert result["backup"] is True
    assert (raw_dir / "chat.md.bak").exists()


def test_publish_batch_collision_abort_and_suffix(tmp_path):
    raw_dir = tmp_path / "raw"
    wiki_dir = tmp_path / "wiki"
    raw = _write(raw_dir / "chat.md", "---\nstatus: triado\ntipo: medicina\n---\nChat\n")
    content = _write(tmp_path / "tmp" / "nota.md", "# Nota\n")
    _write(wiki_dir / "1. Clínica Médica" / "Psiquiatria" / "ISRS.md", "existente\n")
    manifest = _write(
        tmp_path / "manifest.json",
        json.dumps({"raw_file": str(raw), "notes": [{"taxonomy": "Psiquiatria", "title": "ISRS", "content_path": str(content)}]}),
    )

    try:
        med_ops.publish_batch(manifest, _config(raw_dir, wiki_dir), collision="abort")
    except med_ops.CollisionError:
        pass
    else:
        raise AssertionError("collision abort should raise")

    result = med_ops.publish_batch(manifest, _config(raw_dir, wiki_dir), collision="suffix")
    assert result["created"][0].endswith("ISRS (2).md")
    assert (wiki_dir / "1. Clínica Médica" / "Psiquiatria" / "ISRS (2).md").exists()


def test_publish_batch_blocks_taxonomy_that_repeats_title_folder(tmp_path):
    raw_dir = tmp_path / "raw"
    wiki_dir = tmp_path / "wiki"
    _mkdir_canonical(wiki_dir, "1. Clínica Médica/Psiquiatria")
    raw = _write(raw_dir / "chat.md", "---\nstatus: triado\ntipo: medicina\n---\nChat\n")
    content = _write(tmp_path / "tmp" / "nota.md", "# Nota\n")
    manifest = _write(
        tmp_path / "manifest.json",
        json.dumps({"raw_file": str(raw), "notes": [{"taxonomy": "Psiquiatria/ISRS", "title": "ISRS", "content_path": str(content)}]}),
    )

    try:
        med_ops.publish_batch(manifest, _config(raw_dir, wiki_dir), allow_new_taxonomy_leaf=True)
    except med_ops.ValidationError as exc:
        assert "do not repeat the note title" in str(exc)
    else:
        raise AssertionError("title folder duplication should fail")


def test_commit_batch_cli_alias_still_works(tmp_path):
    raw_dir = tmp_path / "raw"
    wiki_dir = tmp_path / "wiki"
    _mkdir_canonical(wiki_dir, "1. Clínica Médica/Psiquiatria")
    raw = _write(raw_dir / "chat.md", "---\nstatus: triado\ntipo: medicina\n---\nChat\n")
    content = _write(tmp_path / "tmp" / "nota.md", "# Nota\n")
    manifest = _write(
        tmp_path / "manifest.json",
        json.dumps({"raw_file": str(raw), "notes": [{"taxonomy": "Psiquiatria", "title": "ISRS", "content_path": str(content)}]}),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--raw-dir",
            str(raw_dir),
            "--wiki-dir",
            str(wiki_dir),
            "commit-batch",
            "--manifest",
            str(manifest),
            "--dry-run",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["dry_run"] is True


def test_taxonomy_cli_commands_return_json(tmp_path):
    wiki_dir = tmp_path / "wiki"
    _write(wiki_dir / "1. Clínica Médica" / "Cardiologia" / "Arritmias" / "existente.md", "# Existente\n")

    canonical = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "taxonomy-canonical",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert canonical.returncode == 0
    assert json.loads(canonical.stdout)["areas"][0]["area"] == "1. Clínica Médica"

    tree = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki_dir),
            "taxonomy-tree",
            "--max-depth",
            "3",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert tree.returncode == 0
    assert "1. Clínica Médica/Cardiologia/Arritmias" in {item["path"] for item in json.loads(tree.stdout)["directories"]}

    resolved = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki_dir),
            "taxonomy-resolve",
            "--taxonomy",
            "cardiologia/arrítmias",
            "--title",
            "Fibrilação Atrial",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert resolved.returncode == 0
    assert json.loads(resolved.stdout)["taxonomy"] == "1. Clínica Médica/Cardiologia/Arritmias"

    audit = subprocess.run(
        [
            sys.executable,
            str(MED_OPS_PATH),
            "--wiki-dir",
            str(wiki_dir),
            "taxonomy-audit",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert audit.returncode == 0
    assert json.loads(audit.stdout)["dry_run_only"] is True


def test_wiki_tree_script_returns_canonical_and_current_tree(tmp_path):
    wiki_dir = tmp_path / "wiki"
    _write(wiki_dir / "1. Clínica Médica" / "Cardiologia" / "Arritmias" / "existente.md", "# Existente\n")

    result = subprocess.run(
        [
            sys.executable,
            str(WIKI_TREE_PATH),
            "--wiki-dir",
            str(wiki_dir),
            "--max-depth",
            "3",
            "--audit",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["canonical_taxonomy"]["areas"][0]["area"] == "1. Clínica Médica"
    assert "1. Clínica Médica/Cardiologia/Arritmias" in {
        item["path"] for item in payload["current_tree"]["directories"]
    }
    assert payload["audit"]["dry_run_only"] is True


def test_run_linker_missing_path_raises(tmp_path):
    cfg = _config(tmp_path / "raw", tmp_path / "wiki", linker_path=tmp_path / "nope.py")
    try:
        med_ops.run_linker(cfg)
    except med_ops.MissingPathError:
        pass
    else:
        raise AssertionError("missing linker should raise")


def test_resolve_config_prefers_bundled_linker_when_no_override(monkeypatch, tmp_path):
    monkeypatch.delenv("MED_LINKER_PATH", raising=False)
    monkeypatch.delenv("MED_WIKI_DIR", raising=False)
    monkeypatch.delenv("MED_CATALOG_PATH", raising=False)
    args = type(
        "Args",
        (),
        {
            "config": str(tmp_path / "missing-config.toml"),
            "raw_dir": None,
            "wiki_dir": None,
            "linker_path": None,
            "catalog_path": None,
        },
    )()

    cfg = med_ops.resolve_config(args)

    assert cfg.linker_path.name == "med_linker.py"
    assert cfg.linker_path.parts[-2:] == ("mednotes", "med_linker.py")
    assert cfg.catalog_path.parts[-3:] == (".gemini", "medical-notes-workbench", "CATALOGO_WIKI.json")


def test_med_ops_help_subprocess():
    result = subprocess.run([sys.executable, str(MED_OPS_PATH), "--help"], text=True, capture_output=True, check=False)
    assert result.returncode == 0
    assert "publish-batch" in result.stdout
    assert "commit-batch" in result.stdout
