# /mednotes:process-chats

Workflow de ingestao de `Chats_Raw` para notas definitivas em `Wiki_Medicina`.

## Objetivo

Transformar chats medicos brutos em notas didaticas Obsidian, mantendo o agente
principal como dono das mutacoes seriais e usando subagents apenas para triagem
e escrita clinica por unidade isolada.

## Fluxo

1. Validar ambiente com `med_ops.py validate`.
2. Carregar contexto de taxonomia com
   `scripts/mednotes/wiki_tree.py --max-depth 4 --audit --format text`.
3. Planejar triagem com
   `med_ops.py plan-subagents --phase triage --max-concurrency <N> --limit <N>`
   quando o usuário pediu lote finito; para máximo paralelismo, use o mesmo
   valor nos dois argumentos.
4. Aplicar `triage` ou `discard` em serie pelo agente principal.
5. Planejar arquitetura com
   `med_ops.py plan-subagents --phase architect --max-concurrency <N> --temp-root <tmp-agents> --limit <N>`
   quando o usuário pediu lote finito; para máximo paralelismo, use o mesmo
   valor nos dois argumentos.
6. Validar/fixar notas temporarias com `validate-note` e `fix-note`, incluindo
   YAML canônico da Wiki (`aliases`, `tags`, `images_*`, ou nenhum YAML quando
   todos estiverem vazios).
7. Montar manifest somente com `stage-note`.
8. Rodar `publish-batch --dry-run`, acionar `med-publish-guard` e publicar
   apenas se aprovado.
9. Rodar `run-linker` uma unica vez ao final do lote.

## Limites

- Nunca editar YAML/status manualmente.
- Nunca sobrescrever nota existente silenciosamente.
- Nunca lançar dois subagents para o mesmo raw chat, temp note ou target final.
- Nunca trocar um plano limitado por leitura manual de vários raw chats no agente
  principal; use apenas os `work_items` retornados e respeite `batches`.
- `--limit` define o tamanho do lote, não a concorrência. Para paralelizar o
  lote inteiro, use `--max-concurrency` igual ao `--limit`.
- Quando o usuário confirmar uma próxima ação de triagem, processe somente
  triagem e pare com resumo; não avance para arquitetura, staging ou publicação.
- Se `validate-note` retornar `requires_llm_rewrite: true`, use o
  `rewrite_prompt` com `med-knowledge-architect`; `fix-note` é normalizador
  determinístico e não cria seções clínicas ausentes.
- Taxonomia e pasta de categoria; `title` vira o arquivo `.md`.
