# medical-notes-workbench

Workbench para criar, organizar, enriquecer, linkar, processar e estudar notas
médicas Markdown/Obsidian. Os workflows públicos foram preservados; a
organização interna agora separa launchers, runbooks, contratos duráveis e
referência.

## Workflows

| Intenção | Comando |
| --- | --- |
| Criar nota médica | `/mednotes:create` |
| Adicionar imagens a notas | `/mednotes:enrich` |
| Processar `Chats_Raw` para `Wiki_Medicina` | `/mednotes:process-chats` |
| Auditar/corrigir saúde da Wiki | `/mednotes:fix-wiki` |
| Rodar linker semântico | `/mednotes:link` |
| Criar flashcards no Anki | `/flashcards` |
| Configurar/verificar ambiente | `/mednotes:setup`, `/mednotes:status` |

Runbooks detalhados:

- [enrich](docs/workflows/enrich.md)
- [process-chats](docs/workflows/process-chats.md)
- [fix-wiki](docs/workflows/fix-wiki.md)
- [link](docs/workflows/link.md)
- [flashcards](docs/workflows/flashcards.md)

Referências:

- [CLI](docs/reference/cli.md)
- [JSON contracts](docs/reference/json-contracts.md)
- [Gemini CLI extension](docs/reference/extension.md)
- [Agent instructions](docs/agent-instructions.md)

## Enricher

Toolbox Python de imagens. O core não chama LLM; o agente/orquestrador decide
âncoras e rerank visual.

```bash
python -m enricher sections nota.md
python -m enricher search wikimedia --query "synapse" --top-k 4
python -m enricher download https://example.com/image.png --vault ~/Obsidian/Anexos
python -m enricher insert nota.md --section Mecanismo --image abc.webp --concept "recaptação de serotonina" --source wikimedia --source-url "https://commons.wikimedia.org/wiki/File:X"
```

Orquestrador canônico:

```bash
python scripts/enrich_notes.py nota.md pasta/ "Wiki/**/*.md" [--config config.toml] [--force]
```

## Gemini CLI Extension

```bash
npm run build:gemini-cli-extension
gemini extensions validate dist/gemini-cli-extension
gemini extensions link dist/gemini-cli-extension
```

Instalação auto-updatable:

```bash
gemini extensions install https://www.github.com/augustocaruso/medical-notes-workbench.git --ref=gemini-cli-extension --auto-update --consent
```

Configuração opcional da SerpAPI:

```bash
gemini extensions config medical-notes-workbench SERPAPI_KEY
```

Sem `SERPAPI_KEY`, `web_search` retorna `[]` e Wikimedia continua funcionando.

## Desenvolvimento

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev,pdf]
.venv/bin/python -m pytest
```

Build e validação:

```bash
npm run build:gemini-cli-extension
gemini extensions validate dist/gemini-cli-extension
```

## Estrutura

```text
src/enricher/                 toolbox de imagens
scripts/enrich_notes.py       CLI pública do workflow de imagens
extension/GEMINI.md           roteador compacto da extensão
extension/commands/           slash-command launchers
extension/skills/             runbooks oficiais
extension/knowledge/          contratos duráveis
extension/agents/             subagents especializados
extension/scripts/mednotes/   CLIs determinísticas dos workflows
extension/scripts/mednotes/wiki/        domínio Wiki
extension/scripts/mednotes/flashcards/  domínio /flashcards
extension/scripts/mednotes/obsidian/    documentação do domínio Obsidian
docs/workflows/               documentação operacional por workflow
docs/reference/               referência técnica
```
