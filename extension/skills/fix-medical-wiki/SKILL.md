---
name: fix-medical-wiki
description: Audita e corrige a saude da Wiki_Medicina com fix-wiki, taxonomia, reescritas controladas, graph-audit e linker. Use com /mednotes:fix-wiki.
---

# Skill: fix-medical-wiki

Resumo canônico do workflow: `docs/workflows/fix-wiki.md`.
Resposta ao usuário: `knowledge/workflow-output-contract.md`.

## Quando usar

Use quando o usuário pedir auditoria, preview ou correção em lote da
`Wiki_Medicina`. Este workflow cobre hierarquia/taxonomia, estilo, YAML
canônico de notas Wiki, reescritas necessárias e grafo.

## Fontes de verdade

- Estilo Wiki: `${extensionPath}/knowledge/knowledge-architect.md`.
- CLI formal: `${extensionPath}/scripts/mednotes/med_ops.py`.
- Hierarquia/taxonomia: `${extensionPath}/scripts/mednotes/wiki_tree.py` e os
  subcomandos `taxonomy-audit`/`taxonomy-migrate` do `med_ops.py`.
- Grafo/linker: `${extensionPath}/scripts/mednotes/wiki_graph.py` e
  `${extensionPath}/scripts/mednotes/med_linker.py`.
- Reescrita LLM: subagent `med-knowledge-architect`, apenas quando a CLI
  reportar `requires_llm_rewrite: true`.
- Saída visível: `${extensionPath}/knowledge/workflow-output-contract.md`.

## Fluxo

1. Localize `${extensionPath}` e o script
   `${extensionPath}/scripts/mednotes/med_ops.py`.
2. Modo padrão do slash command: repare de verdade, com backup:

   ```bash
   uv run python "<med_ops.py>" fix-wiki --apply --backup --json
   ```

   Se o usuário passar `/mednotes:fix-wiki --dry-run` ou pedir explicitamente
   auditoria/preview sem escrita, rode:

   ```bash
   uv run python "<med_ops.py>" fix-wiki --dry-run --json
   ```

   Se o usuário passar `--wiki-dir`, `MED_WIKI_DIR` ou um caminho de Wiki, use
   esse destino.
3. Resuma `status`, `summary`, `total_changed_count`, `file_count`,
   `changed_count`, `written_count`, `error_count`,
   `taxonomy_action_required`, `taxonomy_issue_count`,
   `taxonomy_applied_move_count`, `graph_error_count`, `write_error_count`,
   `requires_llm_rewrite_count`, `hygiene_after.bak_or_rewrite`,
   `hygiene_after.empty_dirs`, `next_command`, `rollback_command`,
   `linker_dry_run.links_planned`, `linker_dry_run.links_rewritten`,
   `blocker_resolution`, `backup_policy` e `backup_cleanup`. Quando uma mudança
   vier só de YAML,
   trate como fix determinístico: `aliases`, `tags` e `images_*`, ou nenhum
   YAML quando todos estiverem vazios. Quando vier de grafo, destaque
   `graph_fix`: links quebrados/self/ambíguos são convertidos para texto
   visível, marcador contraditório é removido e duplicatas exatas podem ser
   removidas com backup. Quando o linker reescrever link existente, explique que
   isso só ocorre com evidência unívoca do catálogo, preservando o texto visível
   do link.
   Se `write_error_count` for maior que zero, trate como bloqueio de IO:
   mostre poucos exemplos de `write_errors`, explique que o linker real foi
   pulado com `linker_skipped_reason: write_errors` e peça liberar iCloud,
   Obsidian, antivírus ou outro processo antes de retentar.
4. Depois do fix determinístico aplicado, leia `taxonomy_initial_plan`,
   `taxonomy_apply`, `taxonomy_audit`, `style_audit`, `graph_fix`,
   `graph_audit`, `linker_dry_run`, `linker_apply`, `graph_audit_final` e
   `final_validation` no JSON retornado. O `fix-wiki` já aplica movimentos
   determinísticos de taxonomia antes do linker; não rode `taxonomy-migrate`
   manualmente para casos já cobertos por `taxonomy_apply`.
5. Repita o ciclo apenas se `next_command` vier preenchido. Se
   `human_decision_required=true`, pare e mostre `human_decisions`. Se
   `graph_fix.duplicates` ou `blocker_resolution` trouxer
   `duplicate_merge_required`, trate como decisão clínica/humana; não peça a
   outro agente para apagar uma das notas sem revisar conteúdo.
6. Se qualquer relatório exigir reescrita LLM, planeje automaticamente:

   ```bash
   uv run python "<med_ops.py>" plan-subagents --phase style-rewrite --max-concurrency 3 --temp-root <tmp-rewrites>
   ```

   Para cada `work_item.target_path`, lance no máximo um
   `med-knowledge-architect`. Passe caminho absoluto, conteúdo atual,
   `rewrite_prompt`, `work_id`, `temp_dir`, `temp_output` e a instrução de
   preservar fatos, aliases, WikiLinks fortes, `[Chat Original]` e
   `[[_Índice_Medicina]]`.
7. O subagent deve escrever somente em `temp_output`. Aplique cada resultado
   primeiro em dry-run:

   ```bash
   uv run python "<med_ops.py>" apply-style-rewrite --target <nota.md> --content <temp.md> --dry-run --json
   ```

   Só aplique se `validation.errors` estiver vazio. No modo padrão do
   `/mednotes:fix-wiki`, a escrita já foi autorizada pelo `--apply`; em
   `--dry-run`, não aplique.
8. A aplicação real usa:

   ```bash
   uv run python "<med_ops.py>" apply-style-rewrite --target <nota.md> --content <temp.md> --backup --json
   ```

   Use `--backup` por padrão.
9. Limite reescritas LLM a 2 tentativas por nota. Nunca rode duas reescritas
   simultâneas para a mesma nota.
10. Depois de aplicar reescritas LLM aceitas, rode novamente:

    ```bash
    uv run python "<med_ops.py>" fix-wiki --apply --backup --json
    ```

    Isso revalida estilo e roda o workflow de grafo/linker em cima do conteúdo
    reescrito.
11. Se `taxonomy_action_required` ainda for true depois de `fix-wiki --apply`,
    os movimentos seguros já foram aplicados e a pendência restante exige
    revisão humana/semântica. Use `human_decisions`, `blocker_resolution.groups`
    e `rollback_command` se a migração aplicada precisar ser revertida.
12. Política de backup: o `fix-wiki` arquiva `.bak` e `.rewrite` fora do vault
    em `~/.gemini/backup_archive/fix-wiki/<data>/<run_id>/...`. Sempre resuma
    `hygiene_after.bak_or_rewrite`, `hygiene_after.empty_dirs` e
    `backup_cleanup.archived_count`. O campo
    `backup_cleanup.deleted_count` continua existindo por compatibilidade, mas
    backups não devem permanecer no vault.
13. Responda usando o contrato de saída: status emoji, contagens, arquivos
    alterados, notas reescritas, links inseridos, backups criados, blockers de
    grafo, problemas de hierarquia e próximas ações.

## Limites

- Não edite YAML/status de raw chats.
- Não publique notas.
- Não rode regex manual para links; use o grafo/linker do `fix-wiki` ou
  `/mednotes:link`.
- Não escreva manualmente sobre a Wiki; use `fix-wiki` ou
  `apply-style-rewrite`.
- Não mova pastas manualmente; migração de hierarquia é sempre
  `taxonomy-migrate` com plano, recibo e rollback, orquestrada pelo
  `fix-wiki` quando o destino for determinístico.
