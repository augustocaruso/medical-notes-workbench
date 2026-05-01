---
name: fix-medical-wiki
description: Audita e corrige a saude da Wiki_Medicina com fix-wiki, taxonomia, reescritas controladas, graph-audit e linker. Use com /mednotes:fix-wiki.
---

# Skill: fix-medical-wiki

Resumo canônico do workflow: `docs/workflows/fix-wiki.md`.

## Quando usar

Use quando o usuário pedir auditoria, preview ou correção em lote da
`Wiki_Medicina`. Este workflow cobre hierarquia/taxonomia, estilo, reescritas
necessárias e grafo.

## Fontes de verdade

- Estilo Wiki: `${extensionPath}/knowledge/knowledge-architect.md`.
- CLI formal: `${extensionPath}/scripts/mednotes/med_ops.py`.
- Hierarquia/taxonomia: `${extensionPath}/scripts/mednotes/wiki_tree.py` e os
  subcomandos `taxonomy-audit`/`taxonomy-migrate` do `med_ops.py`.
- Grafo/linker: `${extensionPath}/scripts/mednotes/wiki_graph.py` e
  `${extensionPath}/scripts/mednotes/med_linker.py`.
- Reescrita LLM: subagent `med-knowledge-architect`, apenas quando a CLI
  reportar `requires_llm_rewrite: true`.

## Fluxo

1. Localize `${extensionPath}` e o script
   `${extensionPath}/scripts/mednotes/med_ops.py`.
2. Rode preview primeiro, sem aplicar:

   ```bash
   python "<med_ops.py>" fix-wiki --json
   ```

   Se o usuário passar `--wiki-dir`, `MED_WIKI_DIR` ou um caminho de Wiki, use
   esse destino.
3. Resuma `file_count`, `changed_count`, `error_count`,
   `taxonomy_action_required`, `taxonomy_issue_count`, `graph_error_count`,
   `requires_llm_rewrite_count`, `linker_dry_run.links_planned` e alguns
   exemplos de arquivos que mudariam.
4. Só aplique quando o usuário pedir explicitamente `--apply`, `--yes`,
   "aplicar", "corrigir de verdade" ou equivalente. Ao aplicar, inclua
   `--backup` por padrão, salvo pedido explícito de não criar backup.
5. Depois do fix determinístico aplicado, leia `taxonomy_audit`,
   `style_audit`, `graph_audit`, `linker_dry_run`, `linker_apply` e
   `graph_audit_final` no JSON retornado.
6. Se qualquer relatório exigir reescrita LLM, planeje:

   ```bash
   python "<med_ops.py>" plan-subagents --phase style-rewrite --max-concurrency 3 --temp-root <tmp-rewrites>
   ```

   Para cada `work_item.target_path`, lance no máximo um
   `med-knowledge-architect`. Passe caminho absoluto, conteúdo atual,
   `rewrite_prompt`, `work_id`, `temp_dir`, `temp_output` e a instrução de
   preservar fatos, aliases, WikiLinks fortes, `[Chat Original]` e
   `[[_Índice_Medicina]]`.
7. O subagent deve escrever somente em `temp_output`. Aplique cada resultado
   primeiro em dry-run:

   ```bash
   python "<med_ops.py>" apply-style-rewrite --target <nota.md> --content <temp.md> --dry-run --json
   ```

   Só aplique se `validation.errors` estiver vazio e o usuário autorizou escrita.
8. A aplicação real usa:

   ```bash
   python "<med_ops.py>" apply-style-rewrite --target <nota.md> --content <temp.md> --backup --json
   ```

   Use `--backup` por padrão.
9. Limite reescritas LLM a 2 tentativas por nota. Nunca rode duas reescritas
   simultâneas para a mesma nota.
10. Depois de aplicar reescritas LLM aceitas, rode novamente:

    ```bash
    python "<med_ops.py>" fix-wiki --apply --backup --json
    ```

    Isso revalida estilo e roda o workflow de grafo/linker em cima do conteúdo
    reescrito.
11. Se `taxonomy_action_required` for true, não mova pastas dentro do
    `fix-wiki`. Oriente o fluxo separado:

    ```bash
    python "<med_ops.py>" taxonomy-migrate --dry-run --plan-output <plano.json>
    ```

    Depois, se o usuário autorizar, aplique com `taxonomy-migrate --apply
    --plan <plano.json> --receipt <recibo.json>`. Rollback deve usar o recibo.
12. Responda com arquivos alterados, notas reescritas, links inseridos, backups
    criados, blockers de grafo, problemas de hierarquia e próximas ações.

## Limites

- Não edite YAML/status de raw chats.
- Não publique notas.
- Não rode regex manual para links; use o grafo/linker do `fix-wiki` ou
  `/mednotes:link`.
- Não escreva manualmente sobre a Wiki; use `fix-wiki` ou
  `apply-style-rewrite`.
- Não migre pastas automaticamente dentro do `fix-wiki`; migração de hierarquia
  é sempre `taxonomy-migrate` com plano, recibo e rollback.
