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
5. Aplicar `triage --note-plan <note-plan.json>` ou `discard` em serie pelo
   agente principal. O `note-plan` é a lista exaustiva de notas que devem nascer
   daquele chat.
6. Planejar arquitetura com
   `med_ops.py plan-subagents --phase architect --temp-root <tmp-agents> --limit <N>`
   quando o usuário pediu lote finito. O mesmo teto default de 5 subagents vale
   aqui; omita `--max-concurrency` para usar esse default. Se houver manifests
   `gemini-md-export.artifact-html-manifest.v1` para o `fonte_id` do raw chat,
   o plano inclui `artifact_manifests` e esses artefatos viram insumo
   obrigatório. Se o plano retornar `blocked_items` com
   `duplicate_create_note_targets`, não lance architects: revise a triagem para
   consolidar fontes ou converter itens duplicados em `covered_by_existing`.
7. Cada `med-knowledge-architect` deve seguir exatamente o `note_plan` da
   triagem e criar um inventário de cobertura
   (`medical-notes-workbench.raw-coverage.v1`) derivado dele. Se achar que o
   plano está incompleto, bloqueie e refaça a triagem; não crie subconjunto nem
   notas extras silenciosamente.
8. Validar/fixar notas temporarias com `validate-note` e `fix-note`, incluindo
   YAML canônico da Wiki (`aliases`, `tags`, `images_*`, ou nenhum YAML quando
   todos estiverem vazios). Se uma nota carregar artefato HTML, ela deve ter
   iframe, link e comentário `gemini-artifact`; a cobertura completa dos
   artefatos é validada no grupo do raw chat durante o publish dry-run.
9. Montar um único manifest de lote somente com `stage-note --coverage
   <coverage.json>`; ele aceita vários raw chats e cria `batches` internamente.
10. Rodar `publish-batch --dry-run` uma vez para esse manifest, acionar
   `med-publish-guard` e publicar uma vez apenas se aprovado. O CLI grava um
   recibo do dry-run e bloqueia o publish real se manifest, cwd, caminhos ou
   opcoes mudarem.
11. Rodar `run-linker` uma unica vez depois do publish do lote inteiro. O
    resultado precisa ser conferido por `index_files_changed` e
    `index_entries_planned`, porque esse passo atualiza o `_Índice_Medicina`.
    Se o linker bloquear links semânticos por grafo, o índice ainda deve ser
   atualizado; a próxima ação padrão é `/mednotes:fix-wiki --dry-run`. Deixe
   fusão/deleção manual apenas para duplicatas não-idênticas que o fix-wiki não
   consegue resolver.
12. Em JSON, trate `phase`, `status`, `blocked_reason`, `next_action`,
   `required_inputs` e `human_decision_required` como contrato operacional do
   workflow. A fase seguinte só é autorizada quando a fase atual terminar sem
   blocker pendente.

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
- `publish-batch` bloqueia manifest sem `coverage_path`, raw chat sem
  `note_plan`, cobertura que não bate com o `note_plan`, notas staged fora da
  cobertura, ou alvo Obsidian que duplica nome existente por normalização de
  acento/caixa.
- Mudanças observáveis no workflow devem ser entregues em 3 camadas:
  contrato, implementação e docs/testes. Em revisão, declare fase alterada,
  pre-condição nova, JSON afetado e teste adversarial correspondente.
- `plan-subagents --phase architect` bloqueia antes de gastar tokens de escrita
  quando um `create_note` duplica nota existente ou outro raw chat planejado por
  normalização de acento/caixa.
- Um raw chat com manifesto `gemini-md-export.artifact-html-manifest.v1` e
  `savedCount > 0` bloqueia `publish-batch` se qualquer HTML exigido faltar do
  grupo de notas staged daquele raw chat. `validate-note` e `stage-note` podem
  mostrar cobertura parcial por nota, mas só bloqueiam HTML inlineado ou
  inclusão parcial/inválida. O HTML permanece em `.html` isolado; não cole HTML
  capturado no Markdown.
- Taxonomia e pasta de categoria; `title` vira o arquivo `.md`.
