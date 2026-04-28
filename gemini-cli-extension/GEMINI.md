# Medical Notes Enricher

Use this extension when the user wants to enrich a Markdown medical study note
with images embedded for Obsidian.

The extension bundles the `medical-notes-enricher` Python toolbox. The core
toolbox never calls an LLM; the orchestrator `scripts/run_agent.py` uses the
Gemini CLI to choose anchors and rerank images visually.

Operational rules:

- Prefer the bundled `enrich-medical-note` skill when the user asks to enrich,
  illustrate, or add figures to a medical `.md` note.
- Work in Portuguese by default when talking to the user.
- Keep note edits additive: insert image embeds/captions and append enricher
  frontmatter fields, but do not rewrite the user's original frontmatter keys.
- Use `python3` and the extension-local `.venv` under the extension directory.
- If `config.toml` is absent, copy `config.example.toml` and ask for the
  Obsidian vault path before running the orchestrator.
- If `SERPAPI_KEY` is present in `.env`, web image search can complement
  Wikimedia. Without it, `web_search` returns an empty list by design.
- If the user asks where to get SerpAPI, direct them to
  https://serpapi.com/ and tell them to create an account, open the dashboard,
  copy the API key, then run
  `gemini extensions config medical-notes-enricher SERPAPI_KEY`.

Useful extension commands:

- `/enricher:setup` prepares the Python virtual environment.
- `/enricher:enrich <path-to-note.md>` enriches one note.
- `/enricher:status` checks local configuration and dependencies.
