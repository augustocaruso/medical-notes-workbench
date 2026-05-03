# Gemini CLI Extension

## Layout

- `extension/GEMINI.md`: roteador compacto e invariantes globais.
- `extension/commands/`: launchers curtos dos slash commands publicos.
- `extension/skills/`: runbooks oficiais, um por workflow.
- `extension/knowledge/`: contratos duraveis e metodologia preservada.
- `extension/knowledge/workflow-output-contract.md`: contrato de resposta
  visivel ao usuario no Gemini CLI.
- `extension/agents/`: agentes especializados chamados pelos runbooks.
- `extension/hooks/`: declaracao dos hooks.
- `extension/scripts/`: scripts empacotados no bundle.

Estado editavel do usuario nao deve ser salvo dentro da pasta instalada em
`~/.gemini/extensions/medical-notes-workbench`, pois updates podem recriar esse
bundle. Use `~/.gemini/medical-notes-workbench` para `config.toml`, `.env`,
cache/indices locais e a venv persistente gerenciada pelo `uv` quando o
workflow precisar de Python.

Em instalações Gemini CLI, rode Python com `uv run python` a partir da raiz da
extensão. Antes de comandos manuais, aponte `UV_PROJECT_ENVIRONMENT` para
`~/.gemini/medical-notes-workbench/.venv` para evitar criar `.venv` dentro do
bundle auto-updatable. No Windows, `scripts/bootstrap_windows_python_uv.ps1`
atualiza o reset script e reconstrói esse ambiente com Python gerenciado pelo
`uv`. Quando a máquina tiver Python global conflitando, o bootstrap instala/usa
`uv` pelo melhor caminho disponível, remove instalações da Python Software
Foundation e o Python Launcher, limpa PATH e sincroniza o projeto.

Hooks usam uma entrada publica unica, `scripts/hooks/mednotes_hook.mjs`. Eles
devem ter matchers estreitos por nome real de ferramenta; nao observe
`run_shell_command` para tentar interpretar comandos depois. Guardas
destrutivas pertencem ao proprio CLI deterministico.

O hook empacotado hoje cobre apenas ferramentas Anki MCP
`mcp_anki(?:-mcp)?_*`. Ele e fail-open e nao abre o Anki por padrao; o auto-start
so acontece quando `MEDNOTES_ANKI_AUTO_START=1`.

O recibo de `publish-batch --dry-run` fica no estado persistente
`~/.gemini/medical-notes-workbench/publish-dry-run-receipts.json` e e validado
pelo `med_ops.py` antes de qualquer `publish-batch` real.

## Comandos Publicos Preservados

- `/mednotes:setup`
- `/mednotes:status`
- `/mednotes:create`
- `/mednotes:enrich`
- `/mednotes:process-chats`
- `/mednotes:fix-wiki`
- `/mednotes:link`
- `/flashcards`

## Regra De Manutencao

Nao duplicar runbooks longos em `GEMINI.md`, TOMLs e README. O comando deve
identificar o workflow e mandar o agente carregar a skill correspondente; a
skill aponta para docs e knowledge quando precisar de detalhe.

Os scripts continuam JSON-first. A fala para o usuario pertence aos launchers e
skills, usando `workflow-output-contract.md` para resumir resultado, avisos e
proxima acao.
