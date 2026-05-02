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
   duplicata exata), dry-run do linker e resolução de blockers.
   Quando o catálogo tiver evidência unívoca de canonicalização, o linker também
   reescreve WikiLinks existentes, por exemplo `[[HAS]]` para
   `[[Hipertensão Arterial Sistêmica|HAS]]`, e reporta isso em
   `linker_dry_run.links_rewritten`.
   Blocker não é fim do workflow nem desculpa de encerramento: leia
   `blocker_resolution.groups`, execute a rota indicada e repita
   `fix-wiki --apply --backup --json`. O linker real só entra quando
   `blocker_resolution.linker_can_apply` for verdadeiro.
   Se algum arquivo estiver bloqueado para escrita, o comando ainda emite JSON
   com `write_error_count`/`write_errors`, pula o linker real e sai com erro de
   IO em vez de despejar traceback.
4. Repita o ciclo de reparo até estabilizar: se o JSON ainda trouxer
   `changed_count`, `graph_fix.changed_count`, `linker_applied`,
   `write_error_count`, `requires_llm_rewrite_count`,
   `taxonomy_action_required` ou `blocker_resolution.has_blockers`, execute a
   rota correspondente abaixo e rode `fix-wiki --apply --backup --json`
   novamente.
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
- Pode reescrever WikiLinks existentes apenas quando o catálogo apontar de forma
  unívoca que o alvo antigo é alias de um alvo canônico. Link válido mas
  semanticamente errado, sem evidência determinística, vira revisão/reescrita.
- Blockers restantes sempre devem aparecer em `blocker_resolution`, com rota,
  amostra e próxima ação; não deixe o agente apenas reportar `graph_blockers`.
- Se `linker_skipped_reason` vier preenchido, a resposta final não pode usar
  status de concluído; deve dizer qual rota foi executada ou qual decisão
  humana/externa ainda impede o fechamento.
- Não acumula backups indefinidamente; a limpeza aparece em `backup_cleanup`.
- Não move pastas manualmente; qualquer taxonomia é via `taxonomy-migrate` com
  plano, recibo e rollback.
- Para linkagem pura, use `/mednotes:link`.
