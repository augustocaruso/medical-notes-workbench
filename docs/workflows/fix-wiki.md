# /mednotes:fix-wiki

Workflow de saude geral da `Wiki_Medicina`.

## Objetivo

Auditar e corrigir problemas formais das notas existentes sem publicar chats.
O comando cobre estilo Markdown/Obsidian, contrato visual da Wiki, YAML
canônico de notas Wiki, reescritas LLM controladas quando a validacao pedir,
correções determinísticas de grafo, linker seguro e taxonomia via
`taxonomy-migrate` com plano, recibo e rollback.

## Fluxo

1. Por padrão, reparar de verdade com backup:
   `uv run python scripts/mednotes/med_ops.py fix-wiki --apply --backup --json`
2. Se o usuário passar `/mednotes:fix-wiki --dry-run`, rode:
   `uv run python scripts/mednotes/med_ops.py fix-wiki --dry-run --json`
3. No modo reparo, o `fix-wiki` aplica em série: style/YAML fix, `graph_fix`
   seguro (`dangling_link`, `self_link`, link ambíguo, marcador contraditório e
   duplicata exata), dry-run do linker e linker real quando não restarem
   blockers.
4. Repita o ciclo de reparo até estabilizar: se o JSON ainda trouxer
   `changed_count`, `graph_fix.changed_count`, `linker_applied`,
   `requires_llm_rewrite_count` ou `taxonomy_action_required`, execute o passo
   correspondente abaixo e rode `fix-wiki --apply --backup --json` novamente.
5. Se `requires_llm_rewrite` vier verdadeiro, planejar:
   `uv run python scripts/mednotes/med_ops.py plan-subagents --phase style-rewrite --max-concurrency 3 --temp-root <tmp-rewrites>`
6. Cada reescrita vai para arquivo temporario e entra pelo gate:
   `apply-style-rewrite --dry-run --json`, depois `apply-style-rewrite --backup --json`
7. Depois de reescritas aceitas, rodar `fix-wiki --apply --backup --json` de
   novo para revalidar estilo e reparar grafo/linker.
8. Se `taxonomy_action_required` vier verdadeiro, resolva no mesmo workflow via
   `taxonomy-migrate`: gere plano, aplique com recibo quando o plano não tiver
   blockers e mantenha rollback disponível.
9. Política de backup do `fix-wiki`: por padrão, manter no máximo 3 backups por
   nota e apagar backups com mais de 14 dias. Ajuste com
   `--backup-max-per-file` e `--backup-retention-days` se necessário.

## Limites

- Nao publica notas novas.
- Nao edita YAML/status de `Chats_Raw`.
- Pode normalizar YAML das notas Wiki para o contrato canônico: `aliases`,
  `tags` e `images_*`, ou nenhum YAML quando todos estiverem vazios.
- Pode remover WikiLinks inválidos convertendo-os em texto visível; duplicatas
  só são removidas automaticamente quando o conteúdo é idêntico. Duplicatas com
  conteúdo divergente viram `duplicate_merge_required`.
- Não acumula backups indefinidamente; a limpeza aparece em `backup_cleanup`.
- Não move pastas manualmente; qualquer taxonomia é via `taxonomy-migrate` com
  plano, recibo e rollback.
- Para linkagem pura, use `/mednotes:link`.
