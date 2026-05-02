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
3. Conferir backlog com `med_ops.py list-pending --summary` e
   `med_ops.py list-triados --summary`; use listas completas só quando precisar
   depurar um item específico.
4. Planejar triagem com
   `med_ops.py plan-subagents --phase triage --limit <N>` quando o usuário
   pediu lote finito. O default de concorrência é 5 subagents; use
   `--max-concurrency 2` ou `--max-concurrency 3` em modo econômico e só passe
   valor maior que 5 quando o usuário pedir explicitamente.
5. Aplicar `triage` ou `discard` em serie pelo agente principal.
6. Planejar arquitetura com
   `med_ops.py plan-subagents --phase architect --temp-root <tmp-agents> --limit <N>`
   quando o usuário pediu lote finito. O mesmo teto default de 5 subagents vale
   aqui; omita `--max-concurrency` para usar esse default.
7. Validar/fixar notas temporarias com `validate-note` e `fix-note`, incluindo
   YAML canônico da Wiki (`aliases`, `tags`, `images_*`, ou nenhum YAML quando
   todos estiverem vazios).
8. Montar um único manifest de lote somente com `stage-note`; ele aceita vários
   raw chats e cria `batches` internamente.
9. Rodar `publish-batch --dry-run` uma vez para esse manifest, acionar
   `med-publish-guard` e publicar uma vez apenas se aprovado.
10. Rodar `run-linker` uma unica vez depois do publish do lote inteiro. Se o
    linker bloquear por grafo, a próxima ação padrão é
    `/mednotes:fix-wiki --dry-run`; deixe fusão/deleção manual apenas para
    duplicatas não-idênticas que o fix-wiki não consegue resolver.

## Limites

- Nunca editar YAML/status manualmente.
- Nunca sobrescrever nota existente silenciosamente.
- Nunca lançar dois subagents para o mesmo raw chat, temp note ou target final.
- Nunca trocar um plano limitado por leitura manual de vários raw chats no agente
  principal; use apenas os `work_items` retornados e respeite `batches`.
- `--limit` define o tamanho do lote, não a concorrência. Para lote de 10, o
  padrão prudente é 10 itens em até 5 subagents por batch, não 10 subagents em
  paralelo.
- Quando o usuário confirmar uma próxima ação de triagem, processe somente
  triagem e pare com resumo; não avance para arquitetura, staging ou publicação.
- Se `validate-note` retornar `requires_llm_rewrite: true`, use o
  `rewrite_prompt` com `med-knowledge-architect`; `fix-note` é normalizador
  determinístico e não cria seções clínicas ausentes.
- Taxonomia e pasta de categoria; `title` vira o arquivo `.md`.
