# Medical Notes Workbench Knowledge Base

These files preserve durable contracts and methodology for the Medical Notes
Workbench workflows. They are reference material for commands, runbook skills,
and subagents; they are not activatable Gemini skills themselves.

- `knowledge-architect.md`: Wiki_Medicina note style, taxonomy, related-note,
  footer, and writing methodology.
- `semantic-linker.md`: semantic linking and catalog rules for WikiLinks.
- `anki-mcp-twenty-rules.md`: local operational copy of the Anki MCP
  `/twenty_rules` prompt, used by `/flashcards` because subagents cannot
  invoke MCP slash prompts themselves.
- `flashcard-ingestion.md`: local design and ingestion rules for Anki card
  creation from Obsidian notes.
- `workflow-output-contract.md`: user-visible status/reporting contract for
  public workflows.

Put workflow sequence and operational branching in activatable skills,
commands, docs, agents, or scripts. Keep `GEMINI.md` as a compact routing
kernel and load these documents only when a workflow needs their contract.
