---
name: link-medical-wiki
description: Roda o linker semântico da Wiki_Medicina com dry-run auditável, catálogo CATALOGO_WIKI.json e aplicação controlada. Use com /mednotes:link.
---

# Skill: link-medical-wiki

Resumo canônico do workflow: `docs/workflows/link.md`.
Resposta ao usuário: `knowledge/workflow-output-contract.md`.

## Quando usar

Use quando o usuário pedir para interconectar notas da `Wiki_Medicina`, rodar o
linker semântico, atualizar links internos ou linkar uma nota recém-criada.

## Fontes de verdade

- Script: `${extensionPath}/scripts/mednotes/med_linker.py`.
- Auditoria objetiva: `${extensionPath}/scripts/mednotes/wiki_graph.py`.
- Regras semânticas: `${extensionPath}/knowledge/semantic-linker.md`.
- Saída visível: `${extensionPath}/knowledge/workflow-output-contract.md`.
- Catálogo preferencial: caminho configurado ou
  `~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json`.

## Fluxo

1. Localize `${extensionPath}` e `${extensionPath}/scripts/mednotes/med_linker.py`.
2. Se o usuário indicar uma nota, passe o caminho como argumento posicional.
3. Use `--catalog`/`MED_CATALOG_PATH` quando `CATALOGO_WIKI.json` existir; o
   catálogo é a fonte primária de vocabulário.
4. Se for necessário apontar outro vault, use `--wiki-dir` ou `MED_WIKI_DIR`.
5. Rode dry-run auditável primeiro:

   ```bash
   uv run python "${extensionPath}/scripts/mednotes/med_linker.py" --dry-run --json
   ```

   Inclua `--wiki-dir`, `--catalog` e/ou o caminho da nota conforme necessário.
6. Revise quantos links seriam inseridos, blockers de `graph_audit_before`,
   quais termos vieram do catálogo e quais vieram do fallback dinâmico.
7. Se não houver blockers, rode sem `--dry-run` para aplicar. O linker bloqueia
   aplicação quando o grafo já tem erro crítico.
8. Responda usando o contrato de saída, com status emoji, arquivos alterados,
   links inseridos, uso do catálogo, blockers, avisos de validação e próxima
   ação.

## Limites

- Não use regex manual para linkar notas.
- Não atualize `CATALOGO_WIKI.json` com aliases genéricos.
- Não rode publish; este skill só linka conteúdo já existente.
