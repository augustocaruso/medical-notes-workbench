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
- Todo raw chat triado como medicina precisa de `note_plan` exaustivo
  `medical-notes-workbench.triage-note-plan.v1`; o architect deve derivar a
  cobertura `medical-notes-workbench.raw-coverage.v1` desse plano. O
  `publish-batch` bloqueia manifest sem `coverage_path`, raw sem `note_plan`,
  cobertura divergente ou notas staged fora do plano.
- Rode o workflow de grafo/linker uma única vez ao final do lote.
- O agente principal consolida estado compartilhado em série: `triage`,
  `discard`, `stage-note`, catálogo, dry-run, publish e linker.
- Paralelize apenas work items planejados por `plan-subagents`.
- Se o usuário confirmou uma próxima ação específica, execute só essa fase. Uma
  confirmação para "triagem de mais 10 chats" não autoriza arquitetura, staging,
  publish ou linker no mesmo turno.
- Para lotes explícitos, use `plan-subagents --limit <N>` e processe somente os
  `work_items` retornados, em `batches`. `--limit` é tamanho do lote, não teto
  de paralelismo. O default prudente é 5 subagents em paralelo; use
  `--max-concurrency 2` ou `--max-concurrency 3` em modo econômico e só passe
  valor maior que 5 quando o usuário pedir explicitamente.

## Fluxo

1. Localize `${extensionPath}`; se indisponível, use
   `~/.gemini/extensions/medical-notes-workbench`.
2. Rode:

   ```bash
   uv run python "${extensionPath}/scripts/mednotes/med_ops.py" validate
   ```

   Resuma pendências de configuração antes de continuar.
3. Rode:

   ```bash
   uv run python "${extensionPath}/scripts/mednotes/wiki_tree.py" --max-depth 4 --audit --format text
   ```

   Passe ao `med-knowledge-architect` a taxonomia canônica, a árvore real e a
   auditoria dry-run, preferindo a saída em árvore textual quando o contexto for
   para leitura humana. Os equivalentes separados são `taxonomy-canonical`,
   `taxonomy-tree --max-depth 4` e `taxonomy-audit`.
4. Se o usuário pedir organização prévia do vault, use `taxonomy-migrate`:
   primeiro `--dry-run --plan-output <plano.json>`, depois aplique somente com
   confirmação explícita via `--apply --plan <plano.json> --receipt <recibo.json>`.
   Use `--rollback --receipt <recibo.json>` se precisar desfazer.
5. Rode `list-pending --summary` e `list-triados --summary` para orientar o
   tamanho do backlog sem despejar listas grandes no terminal.
6. Para chats pendentes, rode:

   ```bash
   uv run python "<med_ops.py>" plan-subagents --phase triage --limit <N>
   ```

   Use `--limit` quando o usuário pediu um lote finito (por exemplo, 10). Omita
   `--max-concurrency` para usar o default conservador de 5; em plano humilde,
   prefira `--max-concurrency 2` ou `--max-concurrency 3`. Para cada
   `work_item.raw_file` retornado, lance no máximo um `med-chat-triager`,
   seguindo `batches`. Não leia vários raw chats no agente principal para
   substituir o triager. O triager deve devolver `note_plan` exaustivo com todas
   as notas `create_note` propostas para aquele chat. Grave esse JSON em arquivo
   temporário e aplique `triage --note-plan <note-plan.json>` ou `discard` em
   série via `med_ops.py`, seguindo `canonical_parent_commands` do plano. Se a
   próxima ação era apenas triagem, pare aqui com resumo e nova próxima ação.
7. Atualize `list-triados --summary`. Para chats triados, rode:

   ```bash
   uv run python "<med_ops.py>" plan-subagents --phase architect --temp-root <tmp-agents> --limit <N>
   ```

   Omita `--limit` somente quando o usuário pediu o workflow completo. Para cada
   `work_item.raw_file` retornado, lance no máximo um `med-knowledge-architect`,
   seguindo `batches`. Omita `--max-concurrency` para usar o default de 5, ou
   reduza para 2/3 em modo econômico. Passe `work_id`, `raw_file`, `temp_dir`,
   `note_plan`, taxonomia canônica, árvore real e snapshot do catálogo. Cada
   architect escreve somente no próprio `temp_dir`.
   Use `canonical_parent_commands` do plano para validação, fix, staging,
   dry-run e publish; não invente nomes alternativos de flags.
   Cada architect deve escrever um `coverage.json` no `temp_dir` que corresponda
   exatamente ao `note_plan` da triagem. Se o plano parecer insuficiente, bloqueie
   e volte à triagem; não aceite "top N" nem conjunto representativo.
8. Antes de staging, valide cada nota temporária:

   ```bash
   uv run python "<med_ops.py>" validate-note --content <temp.md> --title <title> --raw-file <raw.md> --json
   ```

   Se `requires_llm_rewrite` aparecer, não tente resolver só com `fix-note`:
   retorne o `rewrite_prompt` ao mesmo architect ou faça uma tentativa
   substituta após a anterior terminar; limite a 2 tentativas por nota. Use
   `fix-note` para erros determinísticos/remediáveis e, depois de uma reescrita
   LLM, como normalizador final. Isso inclui YAML variável gerado pelo agente: o
   fix deve reduzir o frontmatter da Wiki a `aliases`, `tags` e `images_*`, ou
   removê-lo quando todos estiverem vazios.
9. Monte um único manifest para o lote atual apenas com `stage-note --coverage
   <coverage.json>`. O `stage-note` aceita vários raw chats no mesmo manifest e
   cria `batches` internamente; não crie um manifest por raw chat salvo se o
   usuário pediu isolamento explícito. Se taxonomia/estilo/cobertura bloquear,
   corrija a nota, o inventário ou a escolha de taxonomia; não edite o manifest
   manualmente.
10. Rode `med-catalog-curator` em série para atualizar/validar
    `CATALOGO_WIKI.json`, usando o caminho configurado ou
    `~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json`.
11. Rode uma única vez para o manifest do lote:

    ```bash
    uv run python "<med_ops.py>" publish-batch --manifest <manifest.json> --dry-run
    ```

    Revise colisões, destinos e `taxonomy_new_dirs`.
12. Acione `med-publish-guard` com o manifest e o dry-run. Publique apenas se
    ele retornar `approve`.
13. Rode `publish-batch` real uma única vez para o mesmo manifest e, somente
    depois de publicar o lote inteiro, rode:

    ```bash
    uv run python "<med_ops.py>" run-linker
    ```

    O `run-linker` faz preflight de grafo, atualiza o `_Índice_Medicina` mesmo
    quando links semânticos ficam bloqueados e retorna auditoria final. Confira
    `index_files_changed`, `index_entries_planned` e
    `index_refreshed_while_blocked` no resumo. Se houver `blocker_count > 0`,
    não sugira deleção manual como primeira ação: recomende
    `/mednotes:fix-wiki --dry-run` para limpar links quebrados/self/ambíguos e
    identificar duplicatas exatas. Duplicatas não-idênticas continuam como
    decisão humana de fusão.
14. Responda usando o contrato de saída, com status emoji, triados,
    descartados, notas criadas, raw chats processados, canonizações de
    taxonomia, colisões, resultado do linker, warnings de estilo e próxima ação.

## Paralelização

- A unidade indivisível é o raw chat; nunca divida um raw chat, nota temporária
  ou nota final entre dois subagents.
- Se um raw chat gerar várias notas, o mesmo `med-knowledge-architect` decide
  todas.
- A primeira entrega de conteúdo é da triagem: o `note_plan` dirige todas as
  notas. Todos os itens `create_note` precisam aparecer na cobertura e no
  manifest; toda nota staged precisa estar no `note_plan`.
- Se houver 0 ou 1 item, use zero ou um subagent; não crie paralelismo artificial.
- Quando `plan-subagents` retornar `truncated: true`, termine a fase atual antes
  de planejar o próximo lote; não misture itens fora do plano limitado.
- Para `/mednotes:fix-wiki`, a unidade indivisível muda para uma nota Wiki
  existente e o planejamento usa `--phase style-rewrite`.
