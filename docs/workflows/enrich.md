# /mednotes:enrich

Workflow de imagens para notas Markdown medicas.

## Objetivo

Adicionar figuras pedagogicas a notas existentes usando o toolbox `enricher` e
um orquestrador LLM externo para escolher ancoras e ranquear imagens.

## Fluxo

1. Resolver arquivos, diretorios e globs informados pelo usuario.
2. Rodar o orquestrador canonico:
   `python scripts/enrich_notes.py <nota|pasta|glob> [mais alvos] --config config.toml`
3. Usar `--force` somente quando o usuario pedir refazer notas ja marcadas com
   `images_enriched: true`.
4. Reportar notas enriquecidas, puladas, sem insercao, falhas e fontes usadas.

## Limites

- So adiciona blocos de imagem/caption e frontmatter proprio do enricher.
- Nao reescreve texto clinico da nota.
- Sem `SERPAPI_KEY`, `web_search` retorna lista vazia e Wikimedia continua.
- Cota paga esgotada interrompe o lote para evitar chamadas desnecessarias.

