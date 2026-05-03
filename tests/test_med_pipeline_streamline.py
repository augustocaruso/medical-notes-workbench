import json
import importlib
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
HOOK = EXTENSION / "scripts" / "hooks" / "mednotes_hook.mjs"
HOOK_MODULE_DIR = EXTENSION / "scripts" / "hooks" / "mednotes_hook"
MED_OPS = EXTENSION / "scripts" / "mednotes" / "med_ops.py"


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, block, _rest = text.split("---", 2)
    parsed: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            parsed[key.strip()] = value.strip()
    return parsed


def _hook_source_text() -> str:
    parts = [HOOK.read_text(encoding="utf-8")]
    if HOOK_MODULE_DIR.exists():
        parts.extend(path.read_text(encoding="utf-8") for path in sorted(HOOK_MODULE_DIR.glob("*.mjs")))
    return "\n".join(parts)


def test_semantic_medical_skills_are_not_activatable_skills():
    skills = {path.parent.name for path in (EXTENSION / "skills").glob("*/SKILL.md")}

    assert "create-medical-note" in skills
    assert "enrich-medical-note" in skills
    assert "med-chat-processor" not in skills
    assert "med-knowledge-architect" not in skills
    assert "med-auto-linker" not in skills


def test_streamlined_agents_and_models():
    agents = {path.stem: _frontmatter(path) for path in (EXTENSION / "agents").glob("*.md")}

    assert set(agents) == {
        "med-chat-triager",
        "med-knowledge-architect",
        "med-catalog-curator",
        "med-publish-guard",
        "med-flashcard-maker",
    }
    assert agents["med-chat-triager"]["model"] == "gemini-3-flash-preview"
    assert agents["med-publish-guard"]["model"] == "gemini-3-flash-preview"
    assert agents["med-knowledge-architect"]["model"] == "gemini-3.1-pro-preview"
    assert agents["med-catalog-curator"]["model"] == "gemini-3.1-pro-preview"
    assert agents["med-flashcard-maker"]["model"] == "gemini-3.1-pro-preview"


def test_removed_reviewer_agents_do_not_exist():
    assert not (EXTENSION / "agents" / "med-taxonomy-reviewer.md").exists()
    assert not (EXTENSION / "agents" / "med-batch-reviewer.md").exists()
    assert not (EXTENSION / "agents" / "med-note-writer.md").exists()


def test_hooks_are_node_based_for_windows_installations():
    hooks = json.loads((EXTENSION / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    serialized = json.dumps(hooks)
    before_tool = hooks["hooks"]["BeforeTool"]
    after_tool = hooks["hooks"]["AfterTool"]

    assert "python3" not in serialized
    assert "node" in serialized
    assert ".mjs" in serialized
    assert "mednotes_hook.mjs" in serialized
    assert "ensure_anki.mjs" not in serialized
    assert "med_guard.mjs" not in serialized
    assert "SessionStart" not in hooks["hooks"]
    assert "AfterAgent" not in hooks["hooks"]
    assert {entry["matcher"] for entry in before_tool} == {
        "^mcp_anki(?:-mcp)?_.*",
        "run_shell_command",
    }
    anki_entry = next(entry for entry in before_tool if entry["matcher"] == "^mcp_anki(?:-mcp)?_.*")
    assert anki_entry["hooks"][0]["timeout"] == 30000
    assert {entry["matcher"] for entry in after_tool} == {"run_shell_command"}
    assert "*" not in {entry["matcher"] for entry in before_tool}
    assert not list((EXTENSION / "scripts" / "hooks").glob("*.py"))
    assert not (EXTENSION / "scripts" / "hooks" / "ensure_anki.mjs").exists()
    assert not (EXTENSION / "scripts" / "hooks" / "med_guard.mjs").exists()
    assert not (EXTENSION / "scripts" / "hooks" / "med_context.mjs").exists()
    assert not (EXTENSION / "scripts" / "hooks" / "med_after_agent.mjs").exists()


def test_command_toml_files_parse():
    for path in (EXTENSION / "commands").rglob("*.toml"):
        tomllib.loads(path.read_text(encoding="utf-8"))


def test_public_workflows_are_preserved_and_documented():
    commands = {
        "/flashcards": EXTENSION / "commands" / "flashcards.toml",
        "/mednotes:create": EXTENSION / "commands" / "mednotes" / "create.toml",
        "/mednotes:enrich": EXTENSION / "commands" / "mednotes" / "enrich.toml",
        "/mednotes:process-chats": EXTENSION / "commands" / "mednotes" / "process-chats.toml",
        "/mednotes:fix-wiki": EXTENSION / "commands" / "mednotes" / "fix-wiki.toml",
        "/mednotes:link": EXTENSION / "commands" / "mednotes" / "link.toml",
        "/mednotes:setup": EXTENSION / "commands" / "mednotes" / "setup.toml",
        "/mednotes:status": EXTENSION / "commands" / "mednotes" / "status.toml",
    }
    for path in commands.values():
        assert path.exists()

    for doc in ("enrich", "process-chats", "fix-wiki", "link", "flashcards"):
        assert (ROOT / "docs" / "workflows" / f"{doc}.md").exists()
    for doc in ("cli", "json-contracts", "extension"):
        assert (ROOT / "docs" / "reference" / f"{doc}.md").exists()
    assert (EXTENSION / "knowledge" / "workflow-output-contract.md").exists()


def test_extension_build_excludes_generated_python_caches():
    build = (ROOT / "scripts" / "build_gemini_cli_extension.py").read_text(encoding="utf-8")
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert "shutil.ignore_patterns" in build
    assert '"__pycache__"' in build
    assert '"*.pyc"' in build
    assert 'ROOT / "scripts" / "enrich_workflow"' in build
    assert 'SOURCE / "scripts"' in build
    assert '"run_python.mjs"' in build
    assert '"full_reset_windows_python_uv.cmd"' in build
    assert "node scripts/run_python.mjs" in package["scripts"]["build:gemini-cli-extension"]
    assert "python3 scripts/" not in json.dumps(package["scripts"])


def test_user_facing_python_commands_use_uv():
    paths = [
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "docs",
        EXTENSION / "GEMINI.md",
        EXTENSION / "commands",
        EXTENSION / "skills",
        EXTENSION / "knowledge",
        EXTENSION / "agents",
        ROOT / "scripts" / "reset_windows_python_uv.ps1",
    ]
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file() and item.suffix in {".md", ".toml", ".ps1"})
        else:
            files.append(path)

    offenders: list[str] = []
    bare_python = re.compile(r"(?<!uv run )\bpython3?\s+")
    for path in files:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "where python" in line or "python.exe" in line or "requires-python" in line:
                continue
            if bare_python.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{line_no}:{line.strip()}")

    assert offenders == []


def test_launchers_are_short_and_point_to_runbooks():
    for path in (EXTENSION / "commands").rglob("*.toml"):
        text = path.read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 24
    assert "docs/workflows/enrich.md" in (EXTENSION / "commands" / "mednotes" / "enrich.toml").read_text(encoding="utf-8")
    assert "docs/workflows/fix-wiki.md" in (EXTENSION / "commands" / "mednotes" / "fix-wiki.toml").read_text(encoding="utf-8")
    assert "docs/workflows/process-chats.md" in (EXTENSION / "commands" / "mednotes" / "process-chats.toml").read_text(encoding="utf-8")
    assert "docs/workflows/flashcards.md" in (EXTENSION / "commands" / "flashcards.toml").read_text(encoding="utf-8")


def test_public_workflows_point_to_output_contract():
    contract = EXTENSION / "knowledge" / "workflow-output-contract.md"
    contract_text = contract.read_text(encoding="utf-8")

    assert "✅" in contract_text
    assert "👀" in contract_text
    assert "⚠️" in contract_text
    assert "⛔" in contract_text
    assert "🧭" in contract_text

    command_paths = (
        EXTENSION / "commands" / "flashcards.toml",
        EXTENSION / "commands" / "mednotes" / "create.toml",
        EXTENSION / "commands" / "mednotes" / "enrich.toml",
        EXTENSION / "commands" / "mednotes" / "fix-wiki.toml",
        EXTENSION / "commands" / "mednotes" / "link.toml",
        EXTENSION / "commands" / "mednotes" / "process-chats.toml",
    )
    skill_paths = (
        EXTENSION / "skills" / "create-medical-flashcards" / "SKILL.md",
        EXTENSION / "skills" / "create-medical-note" / "SKILL.md",
        EXTENSION / "skills" / "enrich-medical-note" / "SKILL.md",
        EXTENSION / "skills" / "fix-medical-wiki" / "SKILL.md",
        EXTENSION / "skills" / "link-medical-wiki" / "SKILL.md",
        EXTENSION / "skills" / "process-medical-chats" / "SKILL.md",
    )

    for path in command_paths + skill_paths:
        text = path.read_text(encoding="utf-8")
        assert "workflow-output-contract.md" in text
    assert "workflow-output-contract.md" in (EXTENSION / "GEMINI.md").read_text(encoding="utf-8")
    assert "workflow-output-contract.md" in (ROOT / "docs" / "reference" / "json-contracts.md").read_text(encoding="utf-8")


def test_root_agent_docs_are_mirrors_of_canonical_instructions():
    canonical = (ROOT / "docs" / "agent-instructions.md").read_text(encoding="utf-8")
    assert (ROOT / "AGENTS.md").read_text(encoding="utf-8") == canonical
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8") == canonical


def test_image_orchestrator_has_single_clear_entrypoint():
    canonical = ROOT / "scripts" / "enrich_notes.py"
    package = ROOT / "scripts" / "enrich_workflow"
    build = (ROOT / "scripts" / "build_gemini_cli_extension.py").read_text(encoding="utf-8")
    command = (EXTENSION / "commands" / "mednotes" / "enrich.toml").read_text(encoding="utf-8")

    assert canonical.exists()
    assert not (ROOT / "scripts" / "run_agent.py").exists()
    for module in ("models", "gemini", "prompts", "parsing", "candidates", "inputs", "runner", "cli"):
        assert (package / f"{module}.py").exists()
    assert "scripts/enrich_notes.py" in command
    assert "~/.gemini/medical-notes-workbench/config.toml" in command
    assert '"enrich_notes.py"' in build
    assert '"enrich_workflow"' in build
    assert "run_agent.py" not in build
    canonical_text = canonical.read_text(encoding="utf-8")
    assert "from enrich_workflow.cli import main" in canonical_text
    assert "_sync_compat_seams" not in canonical_text
    assert "__all__" not in canonical_text
    assert "import surface" not in canonical_text
    assert "local automation" not in canonical_text

    script_dir = str(ROOT / "scripts")
    added_path = script_dir not in sys.path
    if added_path:
        sys.path.insert(0, script_dir)
    try:
        assert hasattr(importlib.import_module("enrich_workflow.cli"), "main")
        assert hasattr(importlib.import_module("enrich_workflow.prompts"), "build_anchors_prompt")
        assert hasattr(importlib.import_module("enrich_workflow.candidates"), "fetch_thumbs")
    finally:
        if added_path:
            try:
                sys.path.remove(script_dir)
            except ValueError:
                pass


def test_enricher_docs_keep_user_state_out_of_auto_updated_extension():
    skill = (EXTENSION / "skills" / "enrich-medical-note" / "SKILL.md").read_text(encoding="utf-8")
    setup = (EXTENSION / "commands" / "mednotes" / "setup.toml").read_text(encoding="utf-8")
    status = (EXTENSION / "commands" / "mednotes" / "status.toml").read_text(encoding="utf-8")
    workflow = (ROOT / "docs" / "workflows" / "enrich.md").read_text(encoding="utf-8")

    combined = "\n".join([skill, setup, status, workflow])
    assert "~/.gemini/medical-notes-workbench" in combined
    assert "auto-updatable" in combined
    assert "SERPAPI_API_KEY" in combined
    assert "não edite scripts do enricher" in (EXTENSION / "commands" / "mednotes" / "enrich.toml").read_text(encoding="utf-8")


def test_domain_script_layout_is_declared():
    assert (EXTENSION / "scripts" / "mednotes" / "wiki" / "README.md").exists()
    assert (EXTENSION / "scripts" / "mednotes" / "flashcards" / "README.md").exists()
    assert (EXTENSION / "scripts" / "mednotes" / "obsidian" / "README.md").exists()
    assert (EXTENSION / "scripts" / "mednotes" / "wiki" / "linker.py").exists()
    assert (EXTENSION / "scripts" / "mednotes" / "flashcards" / "sources.py").exists()
    assert (EXTENSION / "scripts" / "mednotes" / "flashcards" / "pipeline.py").exists()
    assert not (EXTENSION / "scripts" / "mednotes" / "wiki" / "ops.py").exists()
    assert not (EXTENSION / "scripts" / "mednotes" / "wiki" / "tree.py").exists()
    assert not (EXTENSION / "scripts" / "mednotes" / "obsidian" / "notes.py").exists()


def test_wiki_operations_are_extracted_into_real_modules():
    script_dir = EXTENSION / "scripts" / "mednotes"
    script_dir_str = str(script_dir)
    added_path = script_dir_str not in sys.path
    if added_path:
        sys.path.insert(0, script_dir_str)
    try:
        modules = {
            "api": importlib.import_module("wiki.api"),
            "cli": importlib.import_module("wiki.cli"),
            "config": importlib.import_module("wiki.config"),
            "raw_chats": importlib.import_module("wiki.raw_chats"),
            "taxonomy": importlib.import_module("wiki.taxonomy"),
            "taxonomy_schema": importlib.import_module("wiki.taxonomy.schema"),
            "taxonomy_normalize": importlib.import_module("wiki.taxonomy.normalize"),
            "taxonomy_resolve": importlib.import_module("wiki.taxonomy.resolve"),
            "taxonomy_audit": importlib.import_module("wiki.taxonomy.audit"),
            "taxonomy_migration": importlib.import_module("wiki.taxonomy.migration"),
            "publish": importlib.import_module("wiki.publish"),
            "style": importlib.import_module("wiki.style"),
            "note_style": importlib.import_module("wiki.note_style"),
            "note_style_models": importlib.import_module("wiki.note_style.models"),
            "note_style_frontmatter": importlib.import_module("wiki.note_style.frontmatter"),
            "note_style_validate": importlib.import_module("wiki.note_style.validate"),
            "note_style_fixes": importlib.import_module("wiki.note_style.fixes"),
            "note_style_tables": importlib.import_module("wiki.note_style.tables"),
            "note_style_prompts": importlib.import_module("wiki.note_style.prompts"),
            "health": importlib.import_module("wiki.health"),
            "linking": importlib.import_module("wiki.linking"),
            "graph": importlib.import_module("wiki.graph"),
            "graph_fixes": importlib.import_module("wiki.graph_fixes"),
            "linker": importlib.import_module("wiki.linker"),
            "link_terms": importlib.import_module("wiki.link_terms"),
        }
    finally:
        if added_path:
            try:
                sys.path.remove(script_dir_str)
            except ValueError:
                pass

    assert hasattr(modules["api"], "MedConfig")
    assert hasattr(modules["cli"], "build_parser")
    assert hasattr(modules["cli"], "main")
    assert hasattr(modules["config"], "resolve_config")
    assert hasattr(modules["raw_chats"], "mutate_raw_frontmatter")
    for name in (
        "normalize_taxonomy",
        "resolve_taxonomy",
        "taxonomy_audit",
        "taxonomy_migration_plan",
        "apply_taxonomy_migration",
        "rollback_taxonomy_migration",
    ):
        assert hasattr(modules["taxonomy"], name)
    assert hasattr(modules["taxonomy_schema"], "TaxonomyResolution")
    assert hasattr(modules["taxonomy_normalize"], "safe_title")
    assert hasattr(modules["taxonomy_resolve"], "resolve_target_for_note")
    assert hasattr(modules["taxonomy_audit"], "taxonomy_tree")
    assert hasattr(modules["taxonomy_migration"], "apply_taxonomy_migration")
    assert hasattr(modules["publish"], "publish_batch")
    assert hasattr(modules["style"], "validate_wiki_style")
    assert hasattr(modules["note_style"], "validate_note_style")
    assert hasattr(modules["note_style"], "fix_note_style")
    assert hasattr(modules["note_style_models"], "StyleIssue")
    assert hasattr(modules["note_style_frontmatter"], "raw_meta_from_file")
    assert hasattr(modules["note_style_validate"], "validate_wiki_dir")
    assert hasattr(modules["note_style_fixes"], "fix_note_style")
    assert hasattr(modules["note_style_tables"], "normalize_markdown_tables")
    assert hasattr(modules["note_style_prompts"], "rewrite_prompt")
    assert hasattr(modules["health"], "fix_wiki_health")
    assert hasattr(modules["linking"], "run_linker")
    assert hasattr(modules["graph"], "audit_wiki_graph")
    assert hasattr(modules["graph_fixes"], "fix_wiki_graph")
    assert hasattr(modules["linker"], "build_vocabulary")
    assert hasattr(modules["link_terms"], "extract_aliases")
    assert "subprocess" not in (script_dir / "wiki" / "linking.py").read_text(encoding="utf-8")
    style_text = (script_dir / "wiki" / "style.py").read_text(encoding="utf-8")
    assert "import wiki_note_style" not in style_text
    assert "from wiki import note_style" in style_text
    assert not (script_dir / "wiki_note_style.py").exists()

    facade = MED_OPS.read_text(encoding="utf-8")
    assert "from wiki.cli import main" in facade
    assert "from wiki.api import *" not in facade
    assert "build_parser" not in facade
    assert "__all__" not in facade
    assert "globals().update" not in facade
    assert "Compatibility shim" not in facade
    assert "import surface" not in facade
    wiki_tree = (script_dir / "wiki_tree.py").read_text(encoding="utf-8")
    assert "import med_ops" not in wiki_tree
    assert "from wiki import api as wiki_api" in wiki_tree


def test_domain_script_wrappers_expose_help():
    for path in (
        EXTENSION / "scripts" / "mednotes" / "wiki" / "linker.py",
        EXTENSION / "scripts" / "mednotes" / "wiki" / "graph.py",
        EXTENSION / "scripts" / "mednotes" / "flashcards" / "sources.py",
        EXTENSION / "scripts" / "mednotes" / "flashcards" / "pipeline.py",
        EXTENSION / "scripts" / "mednotes" / "flashcards" / "index.py",
        EXTENSION / "scripts" / "mednotes" / "flashcards" / "report.py",
        EXTENSION / "scripts" / "mednotes" / "flashcards" / "model.py",
        EXTENSION / "scripts" / "mednotes" / "flashcards" / "sync_rules.py",
    ):
        result = subprocess.run(
            [os.sys.executable, str(path), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout


def test_wiki_graph_and_linker_keep_compat_entrypoints():
    for legacy, package_module in (
        ("med_linker.py", "linker"),
        ("wiki_graph.py", "graph"),
    ):
        path = EXTENSION / "scripts" / "mednotes" / legacy
        text = path.read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 22
        assert f"from wiki.{package_module} import main" in text
        assert "globals().update" not in text
        assert "Compatibility shim" not in text
        assert "local automation" not in text
        result = subprocess.run(
            [os.sys.executable, str(path), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout


def test_flashcard_operations_are_extracted_into_real_modules():
    script_dir = EXTENSION / "scripts" / "mednotes"
    script_dir_str = str(script_dir)
    added_path = script_dir_str not in sys.path
    if added_path:
        sys.path.insert(0, script_dir_str)
    try:
        modules = {
            "sources": importlib.import_module("flashcards.sources"),
            "pipeline": importlib.import_module("flashcards.pipeline"),
            "index": importlib.import_module("flashcards.index"),
            "report": importlib.import_module("flashcards.report"),
            "model": importlib.import_module("flashcards.model"),
            "sync_rules": importlib.import_module("flashcards.sync_rules"),
        }
    finally:
        if added_path:
            try:
                sys.path.remove(script_dir_str)
            except ValueError:
                pass

    assert hasattr(modules["sources"], "resolve_manifest")
    assert hasattr(modules["pipeline"], "prepare_write_plan")
    assert hasattr(modules["index"], "check_candidates")
    assert hasattr(modules["report"], "build_report")
    assert hasattr(modules["model"], "validate_models")
    assert hasattr(modules["sync_rules"], "compare_prompts")

    for legacy, package_module in (
        ("flashcard_sources.py", "sources"),
        ("flashcard_pipeline.py", "pipeline"),
        ("flashcard_index.py", "index"),
        ("flashcard_report.py", "report"),
        ("anki_model_validator.py", "model"),
        ("sync_anki_twenty_rules.py", "sync_rules"),
    ):
        path = EXTENSION / "scripts" / "mednotes" / legacy
        text = path.read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 22
        assert f"from flashcards.{package_module} import main" in text
        assert "globals().update" not in text
        assert "Compatibility shim" not in text
        assert "local automation" not in text
        result = subprocess.run(
            [os.sys.executable, str(path), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout


def test_fix_wiki_command_is_public_and_deterministic():
    command = (EXTENSION / "commands" / "mednotes" / "fix-wiki.toml")
    text = command.read_text(encoding="utf-8")
    workflow = (ROOT / "docs" / "workflows" / "fix-wiki.md").read_text(encoding="utf-8")

    assert command.exists()
    assert "fix-wiki --apply --backup --json" in text
    assert "fix-wiki --dry-run --json" in text
    assert "--dry-run" in text
    assert "--backup" in text
    assert "Backup tem ciclo de vida" in text
    assert "requires_llm_rewrite: true" in text
    assert "apply-style-rewrite" in workflow
    assert "taxonomy_action_required" in text
    assert "taxonomy-migrate" in text
    assert "grafo" in workflow
    assert "linkagem pura" in text


def test_subagent_parallelism_contract_is_explicit_and_sharded_by_note_owner():
    process = (EXTENSION / "commands" / "mednotes" / "process-chats.toml").read_text(encoding="utf-8")
    fix_wiki = (EXTENSION / "commands" / "mednotes" / "fix-wiki.toml").read_text(encoding="utf-8")
    gemini = (EXTENSION / "GEMINI.md").read_text(encoding="utf-8")
    triager = (EXTENSION / "agents" / "med-chat-triager.md").read_text(encoding="utf-8")
    architect = (EXTENSION / "agents" / "med-knowledge-architect.md").read_text(encoding="utf-8")
    guard = (EXTENSION / "agents" / "med-publish-guard.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    process_doc = (ROOT / "docs" / "workflows" / "process-chats.md").read_text(encoding="utf-8")
    fix_doc = (ROOT / "docs" / "workflows" / "fix-wiki.md").read_text(encoding="utf-8")

    assert "plan-subagents --phase triage --limit <N>" in process_doc
    assert "plan-subagents --phase architect --temp-root <tmp-agents> --limit <N>" in process_doc
    assert "default de concorrência é 5 subagents" in process_doc
    assert "padrão prudente é 10 itens em até 5 subagents" in process_doc
    assert "plan-subagents --limit <N>" in process
    assert "próxima ação de triagem" in process_doc
    assert "requires_llm_rewrite: true" in process_doc
    assert "plan-subagents --phase style-rewrite --max-concurrency 3" in fix_doc
    assert "um raw chat por subagent" in process
    assert "Nunca lançar dois subagents" in process_doc
    assert "preferred semantic emoji set only" in architect
    assert "exactly one raw chat per agent invocation" in triager
    assert "medical-notes-workbench.triage-note-plan.v1" in triager + process_doc
    assert "triage --note-plan" in process + process_doc
    assert "note_plan" in architect + guard
    assert "Never split one raw chat" in architect
    assert "Cada reescrita vai para arquivo temporario" in fix_doc
    assert "Runbooks canônicos" in claude
    assert "Runbooks canônicos" in agents


def test_flashcard_module_references_anki_mcp_prompt_and_ingestion_design():
    agent = (EXTENSION / "agents" / "med-flashcard-maker.md").read_text(encoding="utf-8")
    top_flashcards = (EXTENSION / "commands" / "flashcards.toml").read_text(encoding="utf-8")
    design = (EXTENSION / "knowledge" / "flashcard-ingestion.md").read_text(encoding="utf-8")
    twenty_rules = (EXTENSION / "knowledge" / "anki-mcp-twenty-rules.md").read_text(
        encoding="utf-8"
    )
    hook = _hook_source_text()
    note_utils = EXTENSION / "scripts" / "mednotes" / "obsidian_note_utils.py"
    source_resolver = EXTENSION / "scripts" / "mednotes" / "flashcard_sources.py"
    flashcard_index = EXTENSION / "scripts" / "mednotes" / "flashcard_index.py"
    model_validator = EXTENSION / "scripts" / "mednotes" / "anki_model_validator.py"
    rules_sync = EXTENSION / "scripts" / "mednotes" / "sync_anki_twenty_rules.py"
    report = EXTENSION / "scripts" / "mednotes" / "flashcard_report.py"
    pipeline = EXTENSION / "scripts" / "mednotes" / "flashcard_pipeline.py"
    build = (ROOT / "scripts" / "build_gemini_cli_extension.py").read_text(encoding="utf-8")

    assert note_utils.exists()
    assert source_resolver.exists()
    assert flashcard_index.exists()
    assert model_validator.exists()
    assert rules_sync.exists()
    assert report.exists()
    assert pipeline.exists()
    assert (ROOT / "docs" / "flashcards-roadmap.md").exists()
    assert (EXTENSION / "knowledge" / "anki-mcp-twenty-rules.md").exists()
    assert '"mcpServers"' not in build
    assert 'DIST / "docs"' in build
    combined = agent + top_flashcards + design
    assert "@ankimcp/anki-mcp-server" in combined + twenty_rules
    assert "servidor global `anki-mcp`" in top_flashcards + design
    assert '"envVar": "SERPAPI_KEY"' in build
    assert '"sensitive": True' in build
    assert not (EXTENSION / "commands" / "twenty_rules.toml").exists()
    assert not (EXTENSION / "commands" / "mednotes" / "flashcards.toml").exists()
    assert not (EXTENSION / "commands" / "mednotes" / "twenty_rules.toml").exists()
    assert "não crie `/twenty_rules` local" in top_flashcards
    assert "twenty-rules.prompt/content.md" in agent
    assert "twenty-rules.prompt/content.md" in design
    assert "twenty-rules.prompt/content.md" in twenty_rules
    assert "anki-mcp-twenty-rules.md" in combined
    assert "nem peça ao usuário para executá-lo" in top_flashcards
    assert "Execute `/twenty_rules` primeiro" not in combined
    assert "notas, pastas, tags Obsidian ou texto" in top_flashcards
    assert "preview-first" in top_flashcards
    assert "mcp_anki-mcp_*" in agent
    assert "twenty_rules" in combined
    assert "flashcard-ingestion.md" in agent + top_flashcards
    assert "nao adicionar tags" in design
    assert "Obsidian`" in agent + top_flashcards + design
    assert "obsidian://open?path=" in top_flashcards + design
    assert "path real" in top_flashcards + design
    assert "--vault-file" in design
    assert "obsidian_note_utils.py" in agent + top_flashcards + design
    assert "flashcard_sources.py" in agent + top_flashcards + design
    assert "flashcard_index.py" in agent + top_flashcards + design
    assert "anki_model_validator.py" in top_flashcards + design
    assert "sync_anki_twenty_rules.py" in design
    assert "flashcard_report.py" in top_flashcards + design
    assert "flashcard_pipeline.py" in agent + top_flashcards + design
    assert "manifest" in agent + top_flashcards + design
    assert "candidate_cards" in agent + top_flashcards + design
    assert "preferred_model" in agent + top_flashcards + design
    assert "anki_find_queries" in top_flashcards + design
    assert "preview-cards" in top_flashcards + design
    assert "--create" in top_flashcards + design
    assert "modo padrão é preview-first" in top_flashcards
    assert "FLASHCARDS_INDEX.json" in top_flashcards + design
    assert "requires_confirmation" in top_flashcards + design
    assert "preview" in top_flashcards + design
    assert "--skip-tag anki" in top_flashcards + design
    assert "skipped_notes" in agent + top_flashcards + design
    assert "add-tag --tag anki" in top_flashcards + design
    assert "remove-tag --tag anki" in top_flashcards + design
    assert "Wiki_Medicina::Cardiologia::Ponte_Miocardica" in design
    assert "Verso Extra" in design + agent
    assert "mcp_anki-mcp_addNotes" in agent
    assert "mcp_anki-mcp_modelFieldNames" in agent
    assert "  - addNotes" not in agent
    assert "mcp_anki(?:-mcp)?_" in hook
    assert "manage_flashcards" not in agent


def _run_hook(mode: str, payload: dict, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(HOOK), mode],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _hook_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MEDNOTES_HOOK_STATE_DIR"] = str(tmp_path / "hook-state")
    env["MEDNOTES_PUBLISH_DRY_RUN_TTL_MS"] = str(30 * 60 * 1000)
    return env


def test_hook_contract_avoids_blocking_io_and_beforetool_additional_context():
    hook = _hook_source_text()

    assert "readFileSync(0" not in hook
    assert "spawnSync" not in hook
    assert "additionalContext" not in hook


def test_hook_runtime_is_single_public_entrypoint_with_internal_modules(tmp_path):
    expected_modules = {
        "anki_preflight.mjs",
        "cli.mjs",
        "commands.mjs",
        "diagnostics.mjs",
        "med_ops_guard.mjs",
        "receipts.mjs",
        "runtime.mjs",
    }
    hooks = json.loads((EXTENSION / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    serialized_hooks = json.dumps(hooks)

    assert HOOK.exists()
    assert {path.name for path in HOOK_MODULE_DIR.glob("*.mjs")} == expected_modules
    assert "mednotes_hook.mjs" in serialized_hooks
    assert "mednotes_hook/" not in serialized_hooks

    shim = HOOK.read_text(encoding="utf-8")
    assert len(shim.splitlines()) <= 8
    assert 'from "./mednotes_hook/cli.mjs"' in shim

    for path in [HOOK, *sorted(HOOK_MODULE_DIR.glob("*.mjs"))]:
        result = subprocess.run(["node", "--check", str(path)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr

    diagnose = subprocess.run(
        ["node", str(HOOK), "diagnose"],
        text=True,
        capture_output=True,
        check=False,
        env=_hook_env(tmp_path),
    )
    assert diagnose.returncode == 0
    payload = json.loads(diagnose.stdout)
    assert payload["dry_run_receipt_count"] == 0
    assert payload["hook_state_dir"].endswith("hook-state")


def test_ensure_anki_hook_preserves_windows_minimize_strategy():
    hook = (HOOK_MODULE_DIR / "anki_preflight.mjs").read_text(encoding="utf-8")

    assert "Start-Process -FilePath $ankiPath -WindowStyle Minimized" in hook
    assert "public static extern bool ShowWindow" in hook
    assert "MainWindowTitle -match \"Anki\"" in hook
    assert "ShowWindow($ankiWindow.MainWindowHandle, 6)" in hook
    assert "Start-Sleep -Milliseconds 500" in hook


def test_hook_returns_json_with_open_stdin():
    process = subprocess.Popen(
        ["node", str(HOOK), "med-ops-before"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    process.stdin.write(json.dumps({"tool_name": "read_file"}))
    process.stdin.flush()

    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        raise AssertionError("hook should finish after parsing complete JSON even when stdin stays open")

    stdout = process.stdout.read() if process.stdout is not None else ""
    assert process.returncode == 0
    assert json.loads(stdout)["suppressOutput"] is True


def test_ensure_anki_hook_ignores_unrelated_tool_calls():
    result = subprocess.run(
        ["node", str(HOOK), "ensure-anki-before"],
        input=json.dumps({"tool_name": "read_file"}),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["suppressOutput"] is True


def test_med_ops_hook_blocks_legacy_commit():
    result = _run_hook(
        "med-ops-before",
        {
            "tool_name": "run_shell_command",
            "tool_input": {"command": f'uv run python "{MED_OPS}" commit'},
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "deny"
    assert "comando legado" in payload["reason"]
    assert "publish-batch --dry-run" in payload["reason"]


def test_med_ops_hook_blocks_publish_without_dry_run_receipt(tmp_path):
    manifest = tmp_path / "batch.json"
    manifest.write_text('{"raw_file": "chat.md", "notes": []}\n', encoding="utf-8")

    result = _run_hook(
        "med-ops-before",
        {
            "tool_name": "run_shell_command",
            "cwd": str(tmp_path),
            "tool_input": {"command": f'uv run python "{MED_OPS}" publish-batch --manifest batch.json'},
        },
        env=_hook_env(tmp_path),
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "deny"
    assert "rode publish-batch --dry-run" in payload["reason"]


def test_med_ops_hook_records_dry_run_and_allows_matching_publish(tmp_path):
    manifest = tmp_path / "batch.json"
    manifest.write_text('{"raw_file": "chat.md", "notes": []}\n', encoding="utf-8")
    env = _hook_env(tmp_path)
    command = f'uv run python "{MED_OPS}" publish-batch --manifest batch.json --dry-run'

    after = _run_hook(
        "med-ops-after",
        {
            "tool_name": "run_shell_command",
            "cwd": str(tmp_path),
            "tool_input": {"command": command},
            "tool_response": {"llmContent": '{"dry_run": true, "created_count": 0}'},
        },
        env=env,
    )

    after_payload = json.loads(after.stdout)
    assert "systemMessage" in after_payload
    assert "Dry-run validado" in after_payload["systemMessage"]

    before = _run_hook(
        "med-ops-before",
        {
            "tool_name": "run_shell_command",
            "cwd": str(tmp_path),
            "tool_input": {"command": f'uv run python "{MED_OPS}" publish-batch --manifest batch.json'},
        },
        env=env,
    )

    assert json.loads(before.stdout) == {"suppressOutput": True}


def test_med_ops_hook_blocks_changed_manifest_after_dry_run(tmp_path):
    manifest = tmp_path / "batch.json"
    manifest.write_text('{"raw_file": "chat.md", "notes": []}\n', encoding="utf-8")
    env = _hook_env(tmp_path)

    _run_hook(
        "med-ops-after",
        {
            "tool_name": "run_shell_command",
            "cwd": str(tmp_path),
            "tool_input": {
                "command": f'uv run python "{MED_OPS}" publish-batch --manifest batch.json --dry-run'
            },
            "tool_response": {"llmContent": '{"dry_run": true}'},
        },
        env=env,
    )

    manifest.write_text('{"raw_file": "chat.md", "notes": [{"title": "changed"}]}\n', encoding="utf-8")
    result = _run_hook(
        "med-ops-before",
        {
            "tool_name": "run_shell_command",
            "cwd": str(tmp_path),
            "tool_input": {"command": f'uv run python "{MED_OPS}" publish-batch --manifest batch.json'},
        },
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "deny"
    assert "manifest mudou" in payload["reason"]


def test_knowledge_contracts_are_current_and_factorized():
    assert not (EXTENSION / "knowledge" / "factory.md").exists()

    knowledge_readme = (EXTENSION / "knowledge" / "README.md").read_text(encoding="utf-8")
    architect = (EXTENSION / "knowledge" / "knowledge-architect.md").read_text(encoding="utf-8")
    linker = (EXTENSION / "knowledge" / "semantic-linker.md").read_text(encoding="utf-8")
    command = (EXTENSION / "commands" / "mednotes" / "process-chats.toml").read_text(encoding="utf-8")
    fix_command = (EXTENSION / "commands" / "mednotes" / "fix-wiki.toml").read_text(encoding="utf-8")
    skill = (EXTENSION / "skills" / "process-medical-chats" / "SKILL.md").read_text(encoding="utf-8")
    fix_skill = (EXTENSION / "skills" / "fix-medical-wiki" / "SKILL.md").read_text(encoding="utf-8")
    process_doc = (ROOT / "docs" / "workflows" / "process-chats.md").read_text(encoding="utf-8")
    agent = (EXTENSION / "agents" / "med-knowledge-architect.md").read_text(encoding="utf-8")
    guard = (EXTENSION / "agents" / "med-publish-guard.md").read_text(encoding="utf-8")

    assert "factory.md" not in knowledge_readme + skill + agent
    assert "Fluxo legado" not in knowledge_readme + skill
    assert "Med Knowledge Architect (A Mente)" in architect
    assert "Semantic Linker Contract" in linker
    assert "O Padrão Ouro: Estrutura de Mini-Aula" in architect
    assert "CATALOGO_WIKI.json" in architect + linker
    assert "aliases" in linker
    assert "[[_Índice_Medicina]]" in architect
    assert "taxonomy-canonical" in skill + agent
    assert "wiki_tree.py --max-depth 4 --audit" in command + skill + agent + process_doc
    assert "taxonomy-audit" in command + skill
    assert "taxonomy-migrate" in command + skill
    assert "--rollback --receipt" in skill
    assert "Modo padrão é reparar" in fix_command
    assert "--dry-run" in fix_command
    assert "Modo padrão do slash command: repare de verdade" in fix_skill
    assert "backup_cleanup.deleted_count" in fix_skill
    assert "vira o arquivo" in architect + command + skill
    assert "new leaf under an existing parent" in guard
    assert "triage-note-plan.v1" in skill + process_doc + command
    assert "coverage_path" in guard
    assert "1. Clínica Médica" in architect + command + agent + guard
    assert "run_shell_command" not in linker
    assert r"C:\Users\leona\.gemini\skills" not in linker
