# /mednotes:fix-wiki

Workflow de saude geral da `Wiki_Medicina`.

## Objetivo

Auditar e corrigir problemas formais das notas existentes sem publicar chats.
O comando cobre estilo Markdown/Obsidian, contrato visual da Wiki, YAML
canônico de notas Wiki, reescritas LLM controladas quando a validacao pedir,
correções determinísticas de grafo, linker seguro, taxonomia determinística via
plano/recibo/rollback e limpeza final de higiene do vault.

## Fluxo

1. Por padrão, reparar de verdade com backup:
   `uv run python scripts/mednotes/med_ops.py fix-wiki --apply --backup --json`
2. Se o usuário passar `/mednotes:fix-wiki --dry-run`, rode:
   `uv run python scripts/mednotes/med_ops.py fix-wiki --dry-run --json`
3. No modo reparo, o `fix-wiki` aplica em série: migrações determinísticas de
   taxonomia com recibo, limpeza de `.bak`/`.rewrite` antigos, style/YAML fix,
   `graph_fix` seguro (`dangling_link`, `self_link`, link ambíguo, marcador
   contraditório e duplicata exata), dry-run do linker, linker real quando
   desbloqueado e limpeza final.
   Quando o catálogo tiver evidência unívoca de canonicalização, o linker também
   reescreve WikiLinks existentes, por exemplo `[[HAS]]` para
   `[[Hipertensão Arterial Sistêmica|HAS]]`, e reporta isso em
   `linker_dry_run.links_rewritten`.
   Blocker não é fim do workflow nem desculpa de encerramento: o comando já
   executa as rotas determinísticas. Leia `status`, `next_command`,
   `human_decision_required`, `human_decisions` e `rollback_command`. O linker
   real só entra quando `blocker_resolution.linker_can_apply` for verdadeiro.
   Se algum arquivo estiver bloqueado para escrita, o comando ainda emite JSON
   com `write_error_count`/`write_errors`, pula o linker real e sai com erro de
   IO em vez de despejar traceback.
4. Repita o ciclo de reparo apenas quando o JSON trouxer `next_command`.
   Se `human_decision_required=true`, pare e mostre as decisões listadas; não
   improvise merge, renome semântico ou apagamento de nota.
5. Se `requires_llm_rewrite` vier verdadeiro, planejar:
   `uv run python scripts/mednotes/med_ops.py plan-subagents --phase style-rewrite --max-concurrency 3 --temp-root <tmp-rewrites>`
6. Cada reescrita vai para arquivo temporario e entra pelo gate:
   `apply-style-rewrite --dry-run --json`, depois `apply-style-rewrite --backup --json`
7. Depois de reescritas aceitas, rodar `fix-wiki --apply --backup --json` de
   novo para revalidar estilo e reparar grafo/linker.
8. Se `taxonomy_action_required` ainda vier verdadeiro depois do `--apply`, a
   pendência restante não tinha destino único seguro. Use `human_decisions` ou
   `blocker_resolution.groups` para revisar; movimentos seguros já foram
   aplicados.
9. Política de backup do `fix-wiki`: backups locais criados durante o reparo
   são arquivados fora do vault em
   `~/.gemini/backup_archive/fix-wiki/<data>/<run_id>/...`. O estado e os
   relatórios ficam em `~/.gemini/medical-notes-workbench/runs/<run_id>/`.

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
  status de concluído; deve dizer qual decisão humana/externa ainda impede o
  fechamento ou qual `next_command` foi retornado.
- Não deixa `.bak` ou `.rewrite` dentro do vault; a limpeza aparece em
  `hygiene_cleanup`, `hygiene_after` e `backup_cleanup`.
- Não move pastas manualmente; qualquer taxonomia é via `taxonomy-migrate` com
  plano, recibo e rollback, agora orquestrado pelo próprio `fix-wiki` quando
  o movimento é determinístico.
- Para linkagem pura, use `/mednotes:link`.
