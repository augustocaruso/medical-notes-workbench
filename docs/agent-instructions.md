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
- Sempre rode `publish-batch --dry-run` antes de publish real; o CLI valida um
  recibo recente do dry-run para o mesmo manifest/caminhos/opções.
- `fix-wiki` deve resolver problemas determinísticos da Wiki; migração de
  pastas é sempre `taxonomy-migrate` com plano, recibo e rollback.
- `link` não corrige estilo, YAML ou publicação.
- `process-chats` publica notas novas com um manifest por lote e roda linker
  uma vez ao final.
- `process-chats` exige `note_plan` exaustivo da triagem
  (`medical-notes-workbench.triage-note-plan.v1`) e cobertura derivada dele
  (`medical-notes-workbench.raw-coverage.v1`); `publish-batch` não deve marcar
  chat como processado sem `note_plan`, `coverage_path` e notas staged batendo.
- `publish-batch` deve bloquear alvos Obsidian duplicados por normalização de
  acento/caixa, tanto contra a Wiki existente quanto dentro do mesmo manifest.
- `plan-subagents --phase architect` deve bloquear `create_note` duplicado
  antes de lançar architects, para evitar gastar tokens escrevendo nota repetida.
- Artefatos interativos do Gemini exportados como
  `gemini-md-export.artifact-html-manifest.v1` são obrigatórios quando
  `savedCount > 0`: o grupo de notas derivado do raw chat deve cobrir todos os
  `.html`; a nota que carregar um artefato deve iframe/linkar o arquivo e
  incluir comentário `gemini-artifact` com `chat_id`, `manifest`, `file` e
  `sha256`; nunca inlinear HTML capturado no Markdown.
- `/flashcards` usa o MCP global `anki-mcp`, não cria comando local
  `/twenty_rules`, não adiciona tags Anki e marca tag Obsidian `anki` somente
  depois de sucesso real no Anki.
- `Wiki_Medicina` usa taxonomia como caminho de pastas de categoria; `title`
  vira o arquivo `.md`.

## Desenvolvimento

- Mantenha dependências runtime mínimas.
- Mudança observável em workflow/CLI deve ser entregue em 3 camadas:
  contrato, implementação e docs/testes.
- Mudanças em `frontmatter.py`, `insert.py`, `cli.py` e `med_ops.py` exigem
  testes.
- Adapters de fonte precisam de teste com fixture HTTP local.
- Subcomandos CLI devem emitir JSON parseável na stdout em sucesso.
- Workflows públicos devem expor, quando fizer sentido, `status`, `phase`,
  `blocked_reason`, `next_action`, `required_inputs` e
  `human_decision_required`.
- Respostas visíveis no Gemini CLI devem resumir JSON/logs conforme
  `extension/knowledge/workflow-output-contract.md`, sem despejar JSON bruto por
  padrão.
- Em revisão de workflow/CLI, confirme pelo menos: quebrou contrato? mudou
  fase? há bloqueio antes de mutar? há teste para o caso patológico? o resumo
  ao usuário bate com o JSON?
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
