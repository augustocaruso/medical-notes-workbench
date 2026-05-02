# /mednotes:fix-wiki

Workflow de saude geral da `Wiki_Medicina`.

## Objetivo

Auditar e corrigir problemas formais das notas existentes sem publicar chats e
sem mover pastas. O comando cobre estilo Markdown/Obsidian, contrato visual da
Wiki, YAML canônico de notas Wiki, reescritas LLM controladas quando a
validacao pedir, auditoria de grafo e linker seguro.

## Fluxo

1. Rodar preview primeiro:
   `python scripts/mednotes/med_ops.py fix-wiki --json`
2. Aplicar somente quando o usuario pedir explicitamente:
   `python scripts/mednotes/med_ops.py fix-wiki --apply --backup --json`
3. Se `requires_llm_rewrite` vier verdadeiro, planejar:
   `python scripts/mednotes/med_ops.py plan-subagents --phase style-rewrite --max-concurrency 3 --temp-root <tmp-rewrites>`
4. Cada reescrita vai para arquivo temporario e entra pelo gate:
   `apply-style-rewrite --dry-run --json`, depois `apply-style-rewrite --backup --json`
5. Depois de reescritas aceitas, rodar `fix-wiki --apply --backup --json` de
   novo para revalidar estilo e reparar grafo/linker.

## Limites

- Nao publica notas novas.
- Nao edita YAML/status de `Chats_Raw`.
- Pode normalizar YAML das notas Wiki para o contrato canônico: `aliases`,
  `tags` e `images_*`, ou nenhum YAML quando todos estiverem vazios.
- Nao move pastas de taxonomia.
- Se `taxonomy_action_required` for verdadeiro, use o workflow separado
  `taxonomy-migrate`.
- Para linkagem pura, use `/mednotes:link`.
