# CLI Reference

As CLIs operacionais priorizam stdout JSON parseavel para automacao, testes e
agentes. No Gemini CLI, os slash commands devem transformar esse JSON em resumo
humano seguindo `extension/knowledge/workflow-output-contract.md`, com status,
contagens, arquivos relevantes, warnings/blockers e proxima acao.

## Enricher toolbox

- `enricher sections <nota.md>`
- `enricher search <wikimedia|web_search> --query <q> [--visual-type T] [--top-k N]`
- `enricher download <url> [--vault PATH] [--max-dim N]`
- `enricher insert <nota.md> --section P --image F --concept C --source S --source-url U`

## Image orchestrator

- `python scripts/enrich_notes.py <nota|pasta|glob> [mais alvos] [--config config.toml] [--force]`

## Wiki operations

- `python scripts/mednotes/med_ops.py validate`
- `python scripts/mednotes/wiki_tree.py --max-depth 4 --audit`
- `python scripts/mednotes/med_ops.py list-pending`
- `python scripts/mednotes/med_ops.py list-triados`
- `python scripts/mednotes/med_ops.py plan-subagents --phase triage|architect|style-rewrite`
- `python scripts/mednotes/med_ops.py triage|discard`
- `python scripts/mednotes/med_ops.py validate-note|fix-note`
- `python scripts/mednotes/med_ops.py stage-note`
- `python scripts/mednotes/med_ops.py publish-batch --dry-run`
- `python scripts/mednotes/med_ops.py publish-batch`
- `python scripts/mednotes/med_ops.py validate-wiki|fix-wiki`
- `python scripts/mednotes/med_ops.py taxonomy-canonical|taxonomy-tree|taxonomy-audit|taxonomy-resolve|taxonomy-migrate`
- `python scripts/mednotes/med_ops.py graph-audit|run-linker`

Domain wrappers are also available for clearer script organization:

- `python scripts/mednotes/wiki/ops.py ...`
- `python scripts/mednotes/wiki/tree.py ...`
- `python scripts/mednotes/wiki/graph.py ...`
- `python scripts/mednotes/wiki/linker.py ...`

## Flashcards

Entradas historicas preservadas:

- `python scripts/mednotes/flashcard_sources.py resolve|preview`
- `python scripts/mednotes/flashcard_pipeline.py prepare|apply`
- `python scripts/mednotes/flashcard_report.py preview-cards|final`
- `python scripts/mednotes/flashcard_index.py check|record|source-status|summary`
- `python scripts/mednotes/anki_model_validator.py validate`
- `python scripts/mednotes/sync_anki_twenty_rules.py check|write`
- `python scripts/mednotes/obsidian_note_utils.py deeplink|add-tag|remove-tag`

Entradas do pacote interno:

- `python scripts/mednotes/flashcards/sources.py ...`
- `python scripts/mednotes/flashcards/pipeline.py ...`
- `python scripts/mednotes/flashcards/report.py ...`
- `python scripts/mednotes/flashcards/index.py ...`
- `python scripts/mednotes/flashcards/model.py ...`
- `python scripts/mednotes/flashcards/sync_rules.py ...`
- `python scripts/mednotes/obsidian/notes.py ...`
