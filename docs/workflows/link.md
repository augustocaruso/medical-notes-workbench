# /mednotes:link

Workflow de linkagem semantica da `Wiki_Medicina`.

## Objetivo

Atualizar WikiLinks internos com base em catalogo medico estrito e auditoria de
grafo, sem mexer em estilo, YAML, publicacao ou taxonomia.

## Fluxo

1. Rodar dry-run:
   `python scripts/mednotes/med_linker.py --dry-run --json`
2. Usar `--wiki-dir` e `--catalog` quando o destino nao for o default.
3. Se o dry-run estiver coerente e sem blockers, rodar sem `--dry-run`.
4. Reportar arquivos alterados, links inseridos, catalogo usado, blockers e
   avisos do graph audit.

## Limites

- Nao corrigir estilo.
- Nao publicar chats.
- Nao atualizar catalogo com aliases genericos.
- Nao fazer linkagem manual por regex fora do script.

