# /mednotes:link

Workflow de linkagem semantica da `Wiki_Medicina`.

## Objetivo

Atualizar WikiLinks internos com base em catalogo medico estrito e auditoria de
grafo, sem mexer em estilo, YAML, publicacao ou taxonomia. O mesmo workflow
mantem a nota operacional `[[_Índice_Medicina]]` como indice hierarquico de
todas as notas Markdown publicadas.

## Fluxo

1. Rodar dry-run:
   `uv run python scripts/mednotes/med_linker.py --dry-run --json`
2. Usar `--wiki-dir` e `--catalog` quando o destino nao for o default.
3. Se o dry-run estiver coerente e sem blockers, rodar sem `--dry-run`.
4. Conferir no JSON `index_files_changed` e `index_entries_planned` para saber
   se o indice seria criado/atualizado e quantas notas entrariam nele.
5. Reportar arquivos alterados, links inseridos, links reescritos, indice,
   catalogo usado, blockers e avisos do graph audit.

## Limites

- Nao corrigir estilo.
- Nao publicar chats.
- Nao atualizar catalogo com aliases genericos.
- Reescrever WikiLinks existentes somente quando o catálogo apontar de forma
  unívoca que o alvo antigo é alias de um alvo canônico.
- Nao fazer linkagem manual por regex fora do script.
