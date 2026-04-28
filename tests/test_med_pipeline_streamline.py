import json
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


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

    assert "python3" not in serialized
    assert "node" in serialized
    assert ".mjs" in serialized
    assert "ensure_anki.mjs" in serialized
    assert "SessionStart" not in hooks["hooks"]
    assert "AfterAgent" not in hooks["hooks"]
    assert {entry["matcher"] for entry in before_tool} == {"^mcp_anki_.*", "run_shell_command"}
    assert "*" not in {entry["matcher"] for entry in before_tool}
    assert not list((EXTENSION / "scripts" / "hooks").glob("*.py"))
    assert not (EXTENSION / "scripts" / "hooks" / "med_context.mjs").exists()
    assert not (EXTENSION / "scripts" / "hooks" / "med_after_agent.mjs").exists()


def test_command_toml_files_parse():
    for path in (EXTENSION / "commands").rglob("*.toml"):
        tomllib.loads(path.read_text(encoding="utf-8"))


def test_flashcard_module_references_anki_mcp_prompt_and_ingestion_design():
    agent = (EXTENSION / "agents" / "med-flashcard-maker.md").read_text(encoding="utf-8")
    top_flashcards = (EXTENSION / "commands" / "flashcards.toml").read_text(encoding="utf-8")
    med_command = (EXTENSION / "commands" / "mednotes" / "flashcards.toml").read_text(encoding="utf-8")
    file_command = (EXTENSION / "commands" / "mednotes" / "twenty_rules.toml").read_text(
        encoding="utf-8"
    )
    design = (EXTENSION / "knowledge" / "flashcard-ingestion.md").read_text(encoding="utf-8")
    hook = (EXTENSION / "scripts" / "hooks" / "ensure_anki.mjs").read_text(encoding="utf-8")
    note_utils = EXTENSION / "scripts" / "mednotes" / "obsidian_note_utils.py"
    build = (ROOT / "scripts" / "build_gemini_cli_extension.py").read_text(encoding="utf-8")

    assert note_utils.exists()
    assert "@ankimcp/anki-mcp-server@0.18.5" in build
    assert "--stdio" in build
    assert '"envVar": "SERPAPI_KEY"' in build
    assert '"sensitive": True' in build
    assert not (EXTENSION / "commands" / "twenty_rules.toml").exists()
    assert "`/twenty_rules` sem namespace pertence ao prompt MCP" in file_command
    assert "twenty-rules.prompt/content.md" in agent
    assert "twenty-rules.prompt/content.md" in top_flashcards
    assert "twenty-rules.prompt/content.md" in med_command
    assert "twenty-rules.prompt/content.md" in file_command
    assert "twenty-rules.prompt/content.md" in design
    assert "nao por `read_file` nesse path" in design
    assert "Este comando aceita" in top_flashcards
    assert "filtro por tag Obsidian" in top_flashcards
    assert "mais de 10 arquivos" in top_flashcards
    assert "mcp_anki_*" in top_flashcards
    assert "twenty_rules" in agent + top_flashcards + med_command + file_command + design
    assert "flashcard-ingestion.md" in agent + top_flashcards + med_command + file_command
    assert "nao adicionar tags" in design
    assert "Obsidian`" in agent + top_flashcards + med_command + file_command + design
    assert "obsidian://open?vault=...&file=..." in top_flashcards + med_command + design
    assert "vault=...&file=..." in agent + top_flashcards + med_command + design
    assert "--absolute-path" in design
    assert "obsidian_note_utils.py" in agent + top_flashcards + med_command + file_command + design
    assert "add-tag --tag anki" in top_flashcards + med_command + file_command + design
    assert "remove-tag --tag anki" in top_flashcards + med_command + file_command + design
    assert "Wiki_Medicina::Cardiologia::Ponte_Miocardica" in design
    assert "Verso Extra" in design + agent
    assert "mcp_anki_addNotes" in agent
    assert "mcp_anki_modelFieldNames" in agent
    assert "  - addNotes" not in agent
    assert "mcp_anki_" in hook
    assert "manage_flashcards" not in agent


def test_ensure_anki_hook_ignores_unrelated_tool_calls():
    hook = EXTENSION / "scripts" / "hooks" / "ensure_anki.mjs"
    result = subprocess.run(
        ["node", str(hook)],
        input=json.dumps({"tool_name": "read_file"}),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["decision"] == "allow"
    assert payload["suppressOutput"] is True


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
