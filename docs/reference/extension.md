# Gemini CLI Extension

## Layout

- `extension/GEMINI.md`: roteador compacto e invariantes globais.
- `extension/commands/`: launchers curtos dos slash commands publicos.
- `extension/skills/`: runbooks oficiais, um por workflow.
- `extension/knowledge/`: contratos duraveis e metodologia preservada.
- `extension/agents/`: agentes especializados chamados pelos runbooks.
- `extension/hooks/`: declaracao dos hooks.
- `extension/scripts/`: scripts empacotados no bundle.

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

