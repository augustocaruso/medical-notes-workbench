# /flashcards

Workflow unico de criacao de flashcards no Anki.

## Objetivo

Criar cards medicos a partir de notas, pastas, globs, tags Obsidian ou texto
colado, usando o MCP global `anki-mcp`, a copia local das Twenty Rules e
checagens deterministicas antes/depois da escrita.

## Fluxo

1. Resolver escopo com `flashcard_sources.py resolve --dry-run --skip-tag anki`.
2. Ler somente as fontes selecionadas.
3. Gerar `candidate_cards` com `med-flashcard-maker`, sem chamar `addNotes`.
4. Preparar plano com `flashcard_pipeline.py prepare`.
5. Mostrar preview com `flashcard_report.py preview-cards`.
6. Gravar no Anki apenas apos confirmacao, salvo pedido explicito de modo
   direto (`--create`, `--direct`, `--yes`, `--no-preview` ou equivalente).
7. Aplicar resultados com `flashcard_pipeline.py apply`.
8. Marcar somente notas bem-sucedidas com tag Obsidian `anki`.

## Limites

- Nao cria comando local `/twenty_rules`.
- Nao adiciona tags Anki.
- O campo `Obsidian` usa deeplink portavel `obsidian://open?vault=...&file=...`.
- Lotes grandes exigem confirmacao.

