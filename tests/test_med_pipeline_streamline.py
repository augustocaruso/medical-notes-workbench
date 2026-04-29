import json
import os
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
HOOK = EXTENSION / "scripts" / "hooks" / "mednotes_hook.mjs"
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


def test_flashcard_module_references_anki_mcp_prompt_and_ingestion_design():
    agent = (EXTENSION / "agents" / "med-flashcard-maker.md").read_text(encoding="utf-8")
    top_flashcards = (EXTENSION / "commands" / "flashcards.toml").read_text(encoding="utf-8")
    design = (EXTENSION / "knowledge" / "flashcard-ingestion.md").read_text(encoding="utf-8")
    twenty_rules = (EXTENSION / "knowledge" / "anki-mcp-twenty-rules.md").read_text(
        encoding="utf-8"
    )
    hook = HOOK.read_text(encoding="utf-8")
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
    assert "`/twenty_rules` sem namespace e o prompt MCP" in top_flashcards
    assert "twenty-rules.prompt/content.md" in agent
    assert "twenty-rules.prompt/content.md" in top_flashcards
    assert "twenty-rules.prompt/content.md" in design
    assert "twenty-rules.prompt/content.md" in twenty_rules
    assert "anki-mcp-twenty-rules.md" in combined
    assert "Nao peça ao usuario para executar `/twenty_rules`" in top_flashcards
    assert "Execute `/twenty_rules` primeiro" not in combined
    assert "Este comando aceita" in top_flashcards
    assert "filtro por tag Obsidian" in top_flashcards
    assert "mais de 10 arquivos" in top_flashcards
    assert "mcp_anki-mcp_*" in top_flashcards
    assert "twenty_rules" in combined
    assert "flashcard-ingestion.md" in agent + top_flashcards
    assert "nao adicionar tags" in design
    assert "Obsidian`" in agent + top_flashcards + design
    assert "obsidian://open?vault=...&file=..." in top_flashcards + design
    assert "vault=...&file=..." in agent + top_flashcards + design
    assert "--absolute-path" in design
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
    assert "Por padrao, `/flashcards` NAO grava diretamente no Anki" in top_flashcards
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
    hook = HOOK.read_text(encoding="utf-8")

    assert "readFileSync(0" not in hook
    assert "spawnSync" not in hook
    assert "additionalContext" not in hook


def test_ensure_anki_hook_preserves_windows_minimize_strategy():
    hook = HOOK.read_text(encoding="utf-8")

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
            "tool_input": {"command": f'python "{MED_OPS}" commit'},
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
            "tool_input": {"command": f'python "{MED_OPS}" publish-batch --manifest batch.json'},
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
    command = f'python "{MED_OPS}" publish-batch --manifest batch.json --dry-run'

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
            "tool_input": {"command": f'python "{MED_OPS}" publish-batch --manifest batch.json'},
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
                "command": f'python "{MED_OPS}" publish-batch --manifest batch.json --dry-run'
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
            "tool_input": {"command": f'python "{MED_OPS}" publish-batch --manifest batch.json'},
        },
        env=env,
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "deny"
    assert "manifest mudou" in payload["reason"]


def test_original_knowledge_text_is_preserved_and_factorized():
    factory = (EXTENSION / "knowledge" / "factory.md").read_text(encoding="utf-8")
    architect = (EXTENSION / "knowledge" / "knowledge-architect.md").read_text(encoding="utf-8")
    linker = (EXTENSION / "knowledge" / "semantic-linker.md").read_text(encoding="utf-8")

    assert "Med Chat Processor (A Fábrica)" in factory
    assert "Med Knowledge Architect (A Mente)" in architect
    assert "Med AI Linker (O Tecelão Semântico)" in linker
    assert "O Padrão Ouro: Estrutura de Mini-Aula" in architect
    assert "CATALOGO_WIKI.json" in architect + linker
    assert "aliases" in factory + linker
    assert "[[_Índice_Medicina]]" in architect
