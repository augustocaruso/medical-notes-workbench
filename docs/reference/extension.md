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

Hooks usam uma entrada publica unica, `scripts/hooks/mednotes_hook.mjs`. A logica
interna fica em `scripts/hooks/mednotes_hook/` para manter guardas, recibos,
preflight do Anki e runtime JSON separados sem mudar o contrato de `hooks.json`.

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
