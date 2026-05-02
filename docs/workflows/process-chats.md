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
   `med_ops.py plan-subagents --phase triage --max-concurrency 4`.
4. Aplicar `triage` ou `discard` em serie pelo agente principal.
5. Planejar arquitetura com
   `med_ops.py plan-subagents --phase architect --max-concurrency 3 --temp-root <tmp-agents>`.
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
- Taxonomia e pasta de categoria; `title` vira o arquivo `.md`.
