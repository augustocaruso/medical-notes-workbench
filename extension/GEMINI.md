# Medical Notes Workbench

Use this extension when the user wants to create, organize, enrich, or process
Markdown medical study notes, especially notes kept in Obsidian.

The extension bundles the `enricher` Python toolbox as its first runtime
module. That module enriches medical notes with local Obsidian image
embeds. Its core toolbox never calls an LLM; the orchestrator
`scripts/run_agent.py` uses the Gemini CLI to choose anchors and rerank images
visually.

Operational rules:

- Prefer the bundled `create-medical-note` skill when the user asks to draft or
  structure a medical study note from a topic, outline, transcript, or pasted
  source.
- Prefer the bundled `enrich-medical-note` skill when the user asks to enrich,
  illustrate, or add figures to a medical `.md` note.
- Prefer `/mednotes:process-chats` and the bundled subagents when the user asks
  to process raw Gemini/medical chat exports from `Chats_Raw` into Obsidian
  notes in `Wiki_Medicina`.
- `/twenty_rules` without a namespace is the Anki MCP prompt itself. Prefer
  `/mednotes:twenty_rules <path>` when the user asks to create Anki flashcards
  from one local note/file after that prompt has been loaded. Prefer
  `/mednotes:flashcards` for broader flashcard requests that are not exactly
  one file path.
- For Wiki_Medicina note structure, follow the preserved knowledge docs under
  `knowledge/`, especially `knowledge-architect.md`.
- For flashcard ingestion design, follow `knowledge/flashcard-ingestion.md`:
  derive the Anki deck from the Obsidian path, do not add tags for now, and
  prefix `Verso Extra` with a visual blank line.
- Prefer `/mednotes:link` or `scripts/mednotes/med_linker.py` when the user asks
  to interconnect Wiki_Medicina notes, refresh wiki links, or run the semantic
  linker.
- Work in Portuguese by default when talking to the user.
- Keep note edits additive: insert image embeds/captions and append enricher
  frontmatter fields, but do not rewrite the user's original frontmatter keys.
- Use the extension-local `.venv` under the extension directory. On Windows,
  prefer `.\.venv\Scripts\python.exe`; on macOS/Linux, prefer
  `.venv/bin/python`.
- If `config.toml` is absent, copy `config.example.toml` and ask for the
  Obsidian vault path before running the orchestrator.
- If `SERPAPI_KEY` is configured through extension settings or the environment,
  web image search can complement Wikimedia. Without it, `web_search` returns
  an empty list by design.
- For raw chat processing, never edit raw-chat YAML/status manually. Use
  `scripts/mednotes/med_ops.py`; run `publish-batch --dry-run` before any real
  `publish-batch`, and run the semantic linker once at the end.
- For chat-processing catalog work, the operational default is
  `~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json`, outside the
  auto-updated extension directory.
- For flashcards, the extension declares an `anki` MCP server using
  `@ankimcp/anki-mcp-server` in STDIO mode. It requires Anki Desktop with
  AnkiConnect reachable at `http://127.0.0.1:8765`. The MCP exposes the
  `/twenty_rules` prompt; use that prompt as the card-writing methodology.
  Gemini exposes Anki MCP tools as `mcp_anki_*`, not as bare tool names.
- The chat-processing workflow must preserve the original Gemini skill
  contract kept in `knowledge/factory.md`: triage first, use the Padrão Ouro for
  clinical note generation, stage aliases/provenance, publish safely, then run
  the semantic linker.
- If the user asks where to get SerpAPI, direct them to
  https://serpapi.com/ and tell them to create an account, open the dashboard,
  copy the API key, then run
  `gemini extensions config medical-notes-workbench SERPAPI_KEY`.

Useful extension commands:

- `/mednotes:setup` prepares the Python virtual environment.
- `/mednotes:create <topic-or-brief>` drafts a medical note.
- `/mednotes:enrich <path-to-note.md>` enriches one note with images.
- `/mednotes:process-chats [args]` processes raw chat backlog into wiki notes.
- `/mednotes:link [path-or-empty]` runs the semantic linker for one note or the
  whole Wiki_Medicina.
- `/mednotes:flashcards [source-or-brief]` creates medical Anki cards via Anki
  MCP.
- `/twenty_rules` loads the Anki MCP `twenty_rules` methodology prompt.
- `/mednotes:twenty_rules <path>` creates Anki cards from exactly one file using
  the loaded Anki MCP `/twenty_rules` prompt and local ingestion design.
- `/mednotes:status` checks local configuration and dependencies.

Bundled Gemini subagents for chat processing:

- `med-chat-triager`
- `med-knowledge-architect`
- `med-catalog-curator`
- `med-publish-guard`

Bundled Gemini subagent for Anki flashcards:

- `med-flashcard-maker`
