# Medical Notes Workbench

Gemini CLI extension for creating, organizing, enriching, linking, processing,
and studying medical Markdown notes in Obsidian. Work in Brazilian Portuguese
by default.

This extension bundles the `enricher` Python toolbox and deterministic
`scripts/mednotes/*.py` utilities. The toolbox itself does not call an LLM;
Gemini/subagents provide judgment, reranking, writing, and review.

Long workflow detail lives in activatable skills and `docs/workflows/`.
Durable contracts live in `knowledge/`. Do not duplicate those runbooks here.
User-visible workflow summaries follow `knowledge/workflow-output-contract.md`;
operational JSON is for agents, hooks, and tests unless the user asks for it.

## Routing

| User intent | Use |
| --- | --- |
| Draft or structure a medical study note | `/mednotes:create` + `create-medical-note` |
| Add figures/images to one or more Markdown notes | `/mednotes:enrich` + `enrich-medical-note` |
| Process `Chats_Raw` into `Wiki_Medicina` | `/mednotes:process-chats` + `process-medical-chats` |
| Audit/fix Wiki_Medicina health | `/mednotes:fix-wiki` + `fix-medical-wiki` |
| Refresh semantic Wiki links | `/mednotes:link` + `link-medical-wiki` |
| Create Anki flashcards | `/flashcards` + `create-medical-flashcards` |
| Configure or inspect the local install | `/mednotes:setup` or `/mednotes:status` |

## Global Rules

- Keep public workflow names, JSON contracts, hooks, and settings stable.
- For workflow results, summarize in Brazilian Portuguese with the status emoji,
  key counts, relevant files, warnings/blockers, and next action from
  `knowledge/workflow-output-contract.md`; do not dump raw JSON by default.
- Prefer `${extensionPath}`; fallback root is
  `~/.gemini/extensions/medical-notes-workbench`.
- Treat `${extensionPath}` as read-only bundle content during normal workflows.
  Mutable user state belongs in `~/.gemini/medical-notes-workbench`
  (`config.toml`, `.env`, cache/catalog files, and the workflow `.venv`).
- Use the persistent workflow venv when present:
  Windows `$HOME\.gemini\medical-notes-workbench\.venv\Scripts\python.exe`,
  macOS/Linux `~/.gemini/medical-notes-workbench/.venv/bin/python`.
- The enricher is additive-only for note content/frontmatter: insert image
  embeds/captions and append its own keys; never rewrite existing frontmatter.
- Raw-chat processing must go through `scripts/mednotes/med_ops.py`; never edit
  raw-chat YAML/status manually and always run `publish-batch --dry-run` before
  a real publish.
- Wiki_Medicina taxonomy is category folders only; `title` becomes the `.md`
  filename. Use the fixed 5 big areas from `knowledge/knowledge-architect.md`
  and the current tree from `scripts/mednotes/wiki_tree.py --max-depth 4 --audit --format text`.
- `/mednotes:fix-wiki` reports taxonomy health, but folder migrations stay in
  `taxonomy-migrate` with plan, receipt, and rollback.
- Wiki_Medicina note style, taxonomy, related-note, and footer requirements live
  in `knowledge/knowledge-architect.md`; do not duplicate them from memory.
- Flashcards use `/flashcards`, the global existing `anki-mcp` server, and
  local methodology in `knowledge/anki-mcp-twenty-rules.md` plus
  `knowledge/flashcard-ingestion.md`. Do not create a local `/twenty_rules`
  command or ask the user to run it first.
- Link and graph repair use `scripts/mednotes/wiki_graph.py` and
  `scripts/mednotes/med_linker.py`; do not hand-roll regex linking.
- If `SERPAPI_KEY`/`SERPAPI_API_KEY` is absent, `web_search` returns `[]`;
  Wikimedia still works.

## Commands

- `/mednotes:setup`
- `/mednotes:create <topic-or-brief>`
- `/mednotes:enrich <note.md|folder|glob> [more targets ...]`
- `/mednotes:process-chats [args]`
- `/mednotes:fix-wiki [--apply] [--backup]`
- `/mednotes:link [path-or-empty]`
- `/flashcards [paths-or-scope]`
- `/mednotes:status`

## Subagents

- `med-chat-triager`
- `med-knowledge-architect`
- `med-catalog-curator`
- `med-publish-guard`
- `med-flashcard-maker`

## References

- `docs/workflows/fix-wiki.md`
- `docs/workflows/process-chats.md`
- `docs/workflows/enrich.md`
- `docs/workflows/flashcards.md`
- `docs/workflows/link.md`
- `docs/reference/cli.md`
- `docs/reference/json-contracts.md`
- `docs/reference/extension.md`
