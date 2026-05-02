# CLI Reference

As CLIs operacionais priorizam stdout JSON parseavel para automacao, testes e
agentes. No Gemini CLI, os slash commands devem transformar esse JSON em resumo
humano seguindo `extension/knowledge/workflow-output-contract.md`, com status,
contagens, arquivos relevantes, warnings/blockers e proxima acao.

Todos os exemplos assumem `uv run python`. Em instalações da extensão, configure
`UV_PROJECT_ENVIRONMENT` para a venv persistente em
`~/.gemini/medical-notes-workbench/.venv` antes de rodar comandos manuais.

## Enricher toolbox

- `enricher sections <nota.md>`
- `enricher search <wikimedia|web_search> --query <q> [--visual-type T] [--top-k N]`
- `enricher download <url> [--vault PATH] [--max-dim N]`
- `enricher insert <nota.md> --section P --image F --concept C --source S --source-url U`

## Image orchestrator

- `uv run python scripts/enrich_notes.py <nota|pasta|glob> [mais alvos] [--config config.toml] [--force]`
- Em instalações Gemini CLI, use config persistente:
  `--config ~/.gemini/medical-notes-workbench/config.toml`.
  O fallback sem `--config` também procura esse caminho, mas o argumento
  explícito evita confusão com arquivos temporários dentro do bundle.

## Wiki operations

- `uv run python scripts/mednotes/med_ops.py validate`
- `uv run python scripts/mednotes/wiki_tree.py --max-depth 4 --audit` (JSON)
- `uv run python scripts/mednotes/wiki_tree.py --max-depth 4 --audit --format text` (árvore legível)
- `uv run python scripts/mednotes/med_ops.py list-pending`
- `uv run python scripts/mednotes/med_ops.py list-triados`
- `uv run python scripts/mednotes/med_ops.py plan-subagents --phase triage|architect|style-rewrite [--limit N]`
- `uv run python scripts/mednotes/med_ops.py triage|discard`
- `uv run python scripts/mednotes/med_ops.py validate-note|fix-note`
- `uv run python scripts/mednotes/med_ops.py stage-note`
- `uv run python scripts/mednotes/med_ops.py publish-batch --dry-run`
- `uv run python scripts/mednotes/med_ops.py publish-batch`
- `uv run python scripts/mednotes/med_ops.py validate-wiki`
- `uv run python scripts/mednotes/med_ops.py fix-wiki --dry-run --json`
- `uv run python scripts/mednotes/med_ops.py fix-wiki --apply --backup --json`
- `uv run python scripts/mednotes/med_ops.py taxonomy-canonical|taxonomy-tree|taxonomy-audit|taxonomy-resolve|taxonomy-migrate`
- `uv run python scripts/mednotes/med_ops.py graph-audit|run-linker`

Entradas do pacote Wiki para uso direto quando útil:

- `uv run python scripts/mednotes/wiki/graph.py ...`
- `uv run python scripts/mednotes/wiki/linker.py ...`

## Flashcards

Aliases publicos preservados:

- `uv run python scripts/mednotes/flashcard_sources.py resolve|preview`
- `uv run python scripts/mednotes/flashcard_pipeline.py prepare|apply`
- `uv run python scripts/mednotes/flashcard_report.py preview-cards|final`
- `uv run python scripts/mednotes/flashcard_index.py check|record|source-status|summary`
- `uv run python scripts/mednotes/anki_model_validator.py validate`
- `uv run python scripts/mednotes/sync_anki_twenty_rules.py check|write`
- `uv run python scripts/mednotes/obsidian_note_utils.py deeplink|add-tag|remove-tag`

Entradas do pacote interno:

- `uv run python scripts/mednotes/flashcards/sources.py ...`
- `uv run python scripts/mednotes/flashcards/pipeline.py ...`
- `uv run python scripts/mednotes/flashcards/report.py ...`
- `uv run python scripts/mednotes/flashcards/index.py ...`
- `uv run python scripts/mednotes/flashcards/model.py ...`
- `uv run python scripts/mednotes/flashcards/sync_rules.py ...`
