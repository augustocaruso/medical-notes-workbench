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
- `/twenty_rules` without a namespace is the Anki MCP prompt itself. The
  extension keeps that name reserved for the MCP, but `/flashcards` must not
  require the user to run it first. Use `/flashcards` for all flashcard
  requests: one file, multiple files, folders, globs, Obsidian tag filters, or
  natural-language source instructions.
- For Wiki_Medicina note structure, follow the preserved knowledge docs under
  `knowledge/`, especially `knowledge-architect.md`.
- For flashcard ingestion design, follow `knowledge/flashcard-ingestion.md`:
  derive the Anki deck from the Obsidian path, fill the Anki `Obsidian` field
  with a source deeplink, do not add Anki tags for now, mark successful source
  notes with the Obsidian frontmatter tag `anki`, and prefix `Verso Extra` with
  a visual blank line. For the card-writing methodology, follow
  `knowledge/anki-mcp-twenty-rules.md`, the local operational copy of the Anki
  MCP `/twenty_rules` prompt. For file/folder/tag scopes, resolve sources first
  with `scripts/mednotes/flashcard_sources.py resolve --scope "<args>" --dry-run --skip-tag anki`
  and use that manifest for decks, deeplinks, tags and confirmation flags. Use
  the sibling `preview` subcommand when you need a human-readable confirmation
  summary. The candidate-card payload must include `preferred_model` and
  `models` captured through Anki MCP `modelNames`/`modelFieldNames`. Before
  writing to Anki, validate model fields with
  `scripts/mednotes/anki_model_validator.py`, filter duplicate candidate cards
  with `scripts/mednotes/flashcard_index.py check`, run generated `findNotes`
  queries for Anki-side duplicates, and record only Anki-accepted cards with
  `flashcard_index.py record`. Use
  `scripts/mednotes/flashcard_pipeline.py prepare`/`apply` for the consolidated
  preferred flow around Anki MCP writes. By default, show the prepared cards in
  the terminal with `scripts/mednotes/flashcard_report.py preview-cards` and ask
  for confirmation before any Anki write; skip that prompt only when the user
  explicitly requests direct creation (`--create`, `--direct`, `--yes`, or
  equivalent natural language). Use
  `scripts/mednotes/flashcard_report.py final` to format a consistent final
  report when structured run data is available.
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
  `publish-batch`, run `scripts/mednotes/wiki_tree.py --max-depth 4 --audit`
  before note-writing agents choose paths, and run the semantic linker once at
  the end. The equivalent split subcommands are `taxonomy-canonical`,
  `taxonomy-tree --max-depth 4`, and `taxonomy-audit` in `med_ops.py`.
- For Wiki_Medicina note creation, taxonomy means existing category folders
  only and title means the `.md` filename. Targets must live under the 5
  canonical big areas (`1. Clínica Médica`, `2. Cirurgia`,
  `3. Ginecologia e Obstetrícia`, `4. Pediatria`, `5. Medicina Preventiva`).
  Specialty-first inputs such as `Cardiologia/Arritmias` are canonicalized by
  `med_ops.py`, but agents should prefer full canonical paths. Do not repeat
  the title as the final taxonomy folder. New taxonomy folders are blocked by default; use
  `--allow-new-taxonomy-leaf` only after explicit approval for a single new
  leaf under an existing parent.
- To correct pre-existing vault folder drift, use `med_ops.py taxonomy-migrate`
  conservatively: generate a dry-run plan first, apply only that plan with a
  receipt, and use rollback from the receipt if needed. Never merge into an
  existing destination automatically; report blocked items for human review.
- For chat-processing catalog work, the operational default is
  `~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json`, outside the
  auto-updated extension directory.
- For flashcards, the extension uses the user's existing global `anki-mcp` MCP
  server from `~/.gemini/settings.json`. It deliberately does not declare
  another Anki MCP server in the extension manifest, to avoid duplicates. The
  MCP requires Anki Desktop with AnkiConnect reachable at
  `http://127.0.0.1:8765`. It exposes the `/twenty_rules` prompt, whose content
  is bundled locally for autonomous command/subagent use.
  Its package source path is
  `@ankimcp/anki-mcp-server/dist/mcp/primitives/essential/prompts/twenty-rules.prompt/content.md`;
  treat that package path as upstream provenance. Read
  `knowledge/anki-mcp-twenty-rules.md` at runtime instead.
  Gemini exposes the existing `anki-mcp` tools as `mcp_anki-mcp_*`, not as bare
  tool names.
  `/flashcards` resolves folders/globs/tag filters through
  `scripts/mednotes/flashcard_sources.py`, but selected source content remains
  the only factual base and Obsidian tags must not become Anki tags. The
  manifest provides portable `obsidian://open?vault=...&file=...` links and
  `skipped_notes` for notes already tagged `anki`; use
  `scripts/mednotes/obsidian_note_utils.py add-tag --tag anki` only after at
  least one card from that note is accepted by Anki. The same script supports
  `remove-tag --tag anki` for cleanup. Use
  `scripts/mednotes/sync_anki_twenty_rules.py check` when auditing the vendored
  Twenty Rules copy against the upstream Anki MCP package.
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
- `/flashcards [paths-or-scope]` creates medical Anki cards from files,
  folders, globs, Obsidian tags, or source instructions.
- `/mednotes:status` checks local configuration and dependencies.

Bundled Gemini subagents for chat processing:

- `med-chat-triager`
- `med-knowledge-architect`
- `med-catalog-curator`
- `med-publish-guard`

Bundled Gemini subagent for Anki flashcards:

- `med-flashcard-maker`
