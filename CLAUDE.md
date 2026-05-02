# medical-notes-workbench

Workbench para criação, organização, enriquecimento, linkagem, processamento e
estudo de notas médicas Markdown/Obsidian. O uso é pessoal/estudo, em português
do Brasil por padrão.

## Workflows Públicos

Preserve estes nomes. Eles são a interface do usuário:

- `/mednotes:create`: cria nota médica didática.
- `/mednotes:enrich`: adiciona imagens/captions/frontmatter do enricher.
- `/mednotes:process-chats`: processa `Chats_Raw` para `Wiki_Medicina`.
- `/mednotes:fix-wiki`: audita/corrige saúde geral da Wiki; não publica chats;
  taxonomia, quando necessária, é via `taxonomy-migrate` com plano, recibo e
  rollback.
- `/mednotes:link`: roda apenas grafo/linker.
- `/flashcards`: cria cards no Anki, preview-first por padrão.
- `/mednotes:setup` e `/mednotes:status`: ambiente local.

Runbooks canônicos:

- `docs/workflows/enrich.md`
- `docs/workflows/process-chats.md`
- `docs/workflows/fix-wiki.md`
- `docs/workflows/link.md`
- `docs/workflows/flashcards.md`

Referências:

- `docs/reference/cli.md`
- `docs/reference/json-contracts.md`
- `docs/reference/extension.md`
- `extension/knowledge/workflow-output-contract.md`

## Fontes De Verdade

- `extension/GEMINI.md`: roteador compacto da extensão.
- `extension/commands/`: launchers curtos dos comandos públicos.
- `extension/skills/`: runbooks oficiais dos workflows.
- `extension/knowledge/`: contratos duráveis e metodologia preservada.
- `extension/knowledge/workflow-output-contract.md`: resposta final dos
  workflows no Gemini CLI, com resumo acionável e emoji de status.
- `extension/agents/`: subagents especializados.
- `src/enricher/`: toolbox de imagens; não chama LLM.
- `scripts/enrich_notes.py`: CLI pública do workflow de imagens com Gemini CLI.
- `extension/scripts/mednotes/med_ops.py`: CLI pública determinística dos
  workflows Wiki; imports Python devem usar `wiki.api` ou módulos `wiki.*`.

## Regras Operacionais

- Estado mutável do usuário/extensão (`config.toml`, `.env`, `.venv` gerenciada
  pelo `uv`, cache, índices e catálogos) deve viver em
  `~/.gemini/medical-notes-workbench`, nunca como única cópia dentro de
  `~/.gemini/extensions/medical-notes-workbench`.
- Nunca reescreva frontmatter existente do enricher; ele é additive-only.
- YAML de notas Wiki é canônico: preserve `aliases`, `tags` e metadados
  `images_*`; omita o bloco somente quando todos estiverem vazios.
- Nunca edite YAML/status de raw chats manualmente; use `med_ops.py`.
- Sempre rode `publish-batch --dry-run` antes de publish real.
- `fix-wiki` deve resolver problemas determinísticos da Wiki; migração de
  pastas é sempre `taxonomy-migrate` com plano, recibo e rollback.
- `link` não corrige estilo, YAML ou publicação.
- `process-chats` publica notas novas com um manifest por lote e roda linker
  uma vez ao final.
- `/flashcards` usa o MCP global `anki-mcp`, não cria comando local
  `/twenty_rules`, não adiciona tags Anki e marca tag Obsidian `anki` somente
  depois de sucesso real no Anki.
- `Wiki_Medicina` usa taxonomia como caminho de pastas de categoria; `title`
  vira o arquivo `.md`.

## Desenvolvimento

- Mantenha dependências runtime mínimas.
- Mudanças em `frontmatter.py`, `insert.py`, `cli.py` e `med_ops.py` exigem
  testes.
- Adapters de fonte precisam de teste com fixture HTTP local.
- Subcomandos CLI devem emitir JSON parseável na stdout em sucesso.
- Respostas visíveis no Gemini CLI devem resumir JSON/logs conforme
  `extension/knowledge/workflow-output-contract.md`, sem despejar JSON bruto por
  padrão.
- Mudança observável deve atualizar README, docs canônicos e os espelhos
  `AGENTS.md`/`CLAUDE.md` quando necessário.
- Antes de fechar tarefa: `uv run python -m pytest`.

## Build Da Extensão

```bash
npm run build:gemini-cli-extension
gemini extensions validate dist/gemini-cli-extension
```

Publicação auto-updatable:

```bash
npm run publish:gemini-cli-extension
```
