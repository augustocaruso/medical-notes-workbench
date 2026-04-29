# Medical Notes Workbench Knowledge Base

These files preserve working Gemini CLI instructions that inform the
chat-processing and flashcard pipelines. They are reference material for
commands and subagents, not activatable Gemini skills.

- `factory.md`: original `med-chat-processor` workflow, "A Fábrica".
- `knowledge-architect.md`: original Padrão Ouro, "A Mente".
- `semantic-linker.md`: original `med-auto-linker`, "O Tecelão Semântico".
- `anki-mcp-twenty-rules.md`: local operational copy of the Anki MCP
  `/twenty_rules` prompt, used by `/flashcards` because subagents cannot
  invoke MCP slash prompts themselves.
- `flashcard-ingestion.md`: local design and ingestion rules for Anki card
  creation from Obsidian notes.

When adapting the pipeline, keep the original wording as intact as practical.
Put extension-specific behavior in commands, agents, or scripts instead of
rewriting these source documents.
