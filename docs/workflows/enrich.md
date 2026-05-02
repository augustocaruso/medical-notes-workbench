# /mednotes:enrich

Workflow de imagens para notas Markdown medicas.

## Objetivo

Adicionar figuras pedagogicas a notas existentes usando o toolbox `enricher` e
um orquestrador LLM externo para escolher ancoras e ranquear imagens.

## Fluxo

1. Resolver arquivos, diretorios e globs informados pelo usuario.
2. Rodar o orquestrador canonico:
   `uv run python scripts/enrich_notes.py <nota|pasta|glob> [mais alvos] --config ~/.gemini/medical-notes-workbench/config.toml`
3. Usar `--force` somente quando o usuario pedir refazer notas ja marcadas com
   `images_enriched: true`.
4. Reportar notas enriquecidas, puladas, sem insercao, falhas e fontes usadas.

## Limites

- So adiciona blocos de imagem/caption e frontmatter proprio do enricher.
- Nao reescreve texto clinico da nota.
- Estado editavel do usuario vive em `~/.gemini/medical-notes-workbench`
  (`config.toml`, `.env`, `.venv` gerenciada pelo `uv` quando aplicavel), nunca dentro do bundle
  auto-updatable `~/.gemini/extensions/medical-notes-workbench`.
- Em Windows, `[gemini].binary = "gemini"` deve funcionar quando o CLI estiver
  instalado por npm; o orquestrador resolve `gemini.cmd` via PATH ou
  `%APPDATA%\npm`. Caminho absoluto é fallback de máquina, não default do repo.
- Sem `SERPAPI_KEY`/`SERPAPI_API_KEY`, `web_search` retorna lista vazia e
  Wikimedia continua.
- Cota paga esgotada interrompe o lote para evitar chamadas desnecessarias.
