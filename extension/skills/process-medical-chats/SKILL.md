---
name: process-medical-chats
description: Processa Chats_Raw médicos em notas Wiki_Medicina usando med_ops.py, subagents, validação formal, publish dry-run e linker semântico. Use com /mednotes:process-chats.
---

# Skill: process-medical-chats

Resumo canônico do workflow: `docs/workflows/process-chats.md`.
Resposta ao usuário: `knowledge/workflow-output-contract.md`.

## Quando usar

Use quando o usuário pedir para processar backlog de chats médicos brutos,
converter `Chats_Raw` em notas do `Wiki_Medicina`, publicar lote de notas
triadas ou continuar o pipeline `/mednotes:process-chats`.

## Fontes de verdade

- Operação mecânica: `${extensionPath}/scripts/mednotes/med_ops.py`.
- Árvore/taxonomia/auditoria: `${extensionPath}/scripts/mednotes/wiki_tree.py`.
- Estilo e taxonomia clínica: `${extensionPath}/knowledge/knowledge-architect.md`.
- Grafo/linker: `${extensionPath}/knowledge/semantic-linker.md`,
  `${extensionPath}/scripts/mednotes/wiki_graph.py` e
  `${extensionPath}/scripts/mednotes/med_linker.py`.
- Saída visível: `${extensionPath}/knowledge/workflow-output-contract.md`.

## Invariantes

- Nunca edite YAML/status de raw chats manualmente.
- Nunca sobrescreva nota existente silenciosamente.
- Sempre rode `publish-batch --dry-run` antes de `publish-batch` real.
- Rode o workflow de grafo/linker uma única vez ao final do lote.
- O agente principal consolida estado compartilhado em série: `triage`,
  `discard`, `stage-note`, catálogo, dry-run, publish e linker.
- Paralelize apenas work items planejados por `plan-subagents`.

## Fluxo

1. Localize `${extensionPath}`; se indisponível, use
   `~/.gemini/extensions/medical-notes-workbench`.
2. Rode:

   ```bash
   python "${extensionPath}/scripts/mednotes/med_ops.py" validate
   ```

   Resuma pendências de configuração antes de continuar.
3. Rode:

   ```bash
   python "${extensionPath}/scripts/mednotes/wiki_tree.py" --max-depth 4 --audit --format text
   ```

   Passe ao `med-knowledge-architect` a taxonomia canônica, a árvore real e a
   auditoria dry-run, preferindo a saída em árvore textual quando o contexto for
   para leitura humana. Os equivalentes separados são `taxonomy-canonical`,
   `taxonomy-tree --max-depth 4` e `taxonomy-audit`.
4. Se o usuário pedir organização prévia do vault, use `taxonomy-migrate`:
   primeiro `--dry-run --plan-output <plano.json>`, depois aplique somente com
   confirmação explícita via `--apply --plan <plano.json> --receipt <recibo.json>`.
   Use `--rollback --receipt <recibo.json>` se precisar desfazer.
5. Rode `list-pending` e `list-triados`.
6. Para chats pendentes, rode:

   ```bash
   python "<med_ops.py>" plan-subagents --phase triage --max-concurrency 4
   ```

   Para cada `work_item.raw_file`, lance no máximo um `med-chat-triager`.
   Depois aplique `triage` ou `discard` em série via `med_ops.py`.
7. Atualize `list-triados`. Para chats triados, rode:

   ```bash
   python "<med_ops.py>" plan-subagents --phase architect --max-concurrency 3 --temp-root <tmp-agents>
   ```

   Para cada `work_item.raw_file`, lance no máximo um `med-knowledge-architect`.
   Passe `work_id`, `raw_file`, `temp_dir`, taxonomia canônica, árvore real e
   snapshot do catálogo. Cada architect escreve somente no próprio `temp_dir`.
8. Antes de staging, valide cada nota temporária:

   ```bash
   python "<med_ops.py>" validate-note --content <temp.md> --title <title> --raw-file <raw.md> --json
   ```

   Se houver erro formal corrigível, rode `fix-note`, valide de novo e só então
   prossiga. Se `requires_llm_rewrite` aparecer, retorne ao mesmo architect ou
   faça uma tentativa substituta após a anterior terminar; limite a 2 tentativas
   por nota.
9. Monte o manifest apenas com `stage-note`. Se taxonomia/estilo bloquear,
   corrija a nota ou a escolha de taxonomia; não edite o manifest manualmente.
10. Rode `med-catalog-curator` em série para atualizar/validar
    `CATALOGO_WIKI.json`, usando o caminho configurado ou
    `~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json`.
11. Rode:

    ```bash
    python "<med_ops.py>" publish-batch --manifest <manifest.json> --dry-run
    ```

    Revise colisões, destinos e `taxonomy_new_dirs`.
12. Acione `med-publish-guard` com o manifest e o dry-run. Publique apenas se
    ele retornar `approve`.
13. Rode `publish-batch` real e, ao final, rode:

    ```bash
    python "<med_ops.py>" run-linker
    ```

    O `run-linker` faz preflight de grafo, aplica apenas se não houver blockers
    e retorna auditoria final.
14. Responda usando o contrato de saída, com status emoji, triados,
    descartados, notas criadas, raw chats processados, canonizações de
    taxonomia, colisões, resultado do linker, warnings de estilo e próxima ação.

## Paralelização

- A unidade indivisível é o raw chat; nunca divida um raw chat, nota temporária
  ou nota final entre dois subagents.
- Se um raw chat gerar várias notas, o mesmo `med-knowledge-architect` decide
  todas.
- Se houver 0 ou 1 item, use zero ou um subagent; não crie paralelismo artificial.
- Para `/mednotes:fix-wiki`, a unidade indivisível muda para uma nota Wiki
  existente e o planejamento usa `--phase style-rewrite`.
