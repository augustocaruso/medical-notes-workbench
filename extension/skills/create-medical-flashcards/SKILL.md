---
name: create-medical-flashcards
description: Cria flashcards médicos no Anki a partir de notas, pastas, tags Obsidian ou texto, usando Twenty Rules, flashcard_pipeline.py e o MCP global anki-mcp. Use com /flashcards.
---

# Skill: create-medical-flashcards

Resumo canônico do workflow: `docs/workflows/flashcards.md`.
Resposta ao usuário: `knowledge/workflow-output-contract.md`.

## Quando usar

Use para `/flashcards`: arquivos Markdown, múltiplos arquivos, diretórios,
globs, tags Obsidian, filtros em linguagem natural ou texto/briefing colado.

## Fontes de verdade

- Metodologia: `${extensionPath}/knowledge/anki-mcp-twenty-rules.md`.
- Regras locais: `${extensionPath}/knowledge/flashcard-ingestion.md`.
- Resolver fontes: `${extensionPath}/scripts/mednotes/flashcard_sources.py`.
- Plano/aplicação: `${extensionPath}/scripts/mednotes/flashcard_pipeline.py`.
- Relatórios: `${extensionPath}/scripts/mednotes/flashcard_report.py`.
- Saída visível: `${extensionPath}/knowledge/workflow-output-contract.md`.
- Deeplink/tag Obsidian: `${extensionPath}/scripts/mednotes/obsidian_note_utils.py`.

`/twenty_rules` sem namespace é o prompt MCP do servidor global `anki-mcp`.
Não crie comando local com esse nome e não peça ao usuário para executá-lo
antes de `/flashcards`.

## Modos

- Padrão: preview-first. Resolva fontes, gere candidatos, valide/filtre, mostre
  cards no terminal e só escreva no Anki após confirmação explícita.
- Direto: pule a confirmação somente se o usuário pedir `--create`, `--direct`,
  `--yes`, `--no-preview`, "criar diretamente", "crie direto", "sem preview",
  "sem prévia" ou "sem confirmação".
- Mesmo em modo direto, pare se o modelo Anki estiver bloqueado ou se o Anki MCP
  falhar.

## Fluxo

1. Resolva o escopo antes de ler notas:

   ```bash
   python "${extensionPath}/scripts/mednotes/flashcard_sources.py" resolve --scope "<args>" --dry-run --skip-tag anki
   ```

   Omita `--skip-tag anki` somente se o usuário pedir refazer/regenerar/incluir
   notas já marcadas.
2. Se o manifest pedir confirmação por lote grande ou escopo amplo, mostre uma
   prévia consistente com:

   ```bash
   python "${extensionPath}/scripts/mednotes/flashcard_sources.py" preview --scope "<args>" --dry-run --skip-tag anki
   ```

3. Use `manifest.notes` como a lista final. Para cada nota, leia `path`, use
   `deck`, `deeplink`, `vault_relative_path`, tags e `content_sha256` do
   manifest. Tags Obsidian selecionam fontes, mas nunca viram tags Anki.
4. Se `manifest.notes` vier vazio e houver texto útil no pedido, trate como
   fonte colada e use `Medicina::Inbox`, salvo deck explícito.
5. Leia `anki-mcp-twenty-rules.md` e `flashcard-ingestion.md`; o conteúdo das
   fontes selecionadas é a única base factual.
6. Chame `med-flashcard-maker` em modo candidato. Ele deve usar
   `mcp_anki-mcp_modelNames`/`mcp_anki-mcp_modelFieldNames` e retornar JSON com
   `preferred_model`, `models` e `candidate_cards`, sem chamar `addNotes`.
7. Prepare o plano:

   ```bash
   python "${extensionPath}/scripts/mednotes/flashcard_pipeline.py" prepare --input -
   ```

   Pare se `blocked` for verdadeiro. Se houver confirmação de reprocessamento,
   pergunte antes de escrever.
8. Mostre o preview de cards:

   ```bash
   python "${extensionPath}/scripts/mednotes/flashcard_report.py" preview-cards --input -
   ```

   No modo padrão, não chame Anki antes da confirmação. Confirmação também é
   obrigatória para lotes com mais de 40 cards candidatos.
9. Chame `med-flashcard-maker` em modo gravação apenas com `new_cards` aprovados
   pelo plano e com `anki_find_queries`. Antes de `addNotes`, ele deve rodar
   `mcp_anki-mcp_findNotes` e pular duplicados existentes no Anki.
10. Depois de sucesso no Anki, aplique resultados:

    ```bash
    python "${extensionPath}/scripts/mednotes/flashcard_pipeline.py" apply --input -
    ```

11. Marque somente notas com pelo menos um card aceito:

    ```bash
    python "${extensionPath}/scripts/mednotes/obsidian_note_utils.py" add-tag --tag anki <arquivos...>
    ```

12. Quando houver dados estruturados, gere o resumo final:

    ```bash
    python "${extensionPath}/scripts/mednotes/flashcard_report.py" final --input -
    ```

    Use o contrato de saída para terminar com status emoji, fontes, candidatos,
    duplicados, criados, notas marcadas com `anki`, bloqueios e próxima ação.

## Requisitos Anki

- Usar exclusivamente o MCP global `anki-mcp` existente em
  `~/.gemini/settings.json`.
- Ferramentas aparecem como `mcp_anki-mcp_*`; não use nomes crus como
  `addNotes`.
- Anki Desktop com AnkiConnect precisa responder em `http://127.0.0.1:8765`.
- Todo card vindo de Markdown precisa preencher o campo `Obsidian` com o
  deeplink portátil do manifest.
