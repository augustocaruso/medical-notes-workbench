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

`/mednotes:process-chats` exige inventário de cobertura exaustivo por raw chat
antes de publicar, para que chats longos gerem todas as notas duráveis em vez
de um subconjunto representativo.

Referências:

- [CLI](docs/reference/cli.md)
- [JSON contracts](docs/reference/json-contracts.md)
- [Gemini CLI extension](docs/reference/extension.md)
- [Agent instructions](docs/agent-instructions.md)

## Enricher

Toolbox Python de imagens. O core não chama LLM; o agente/orquestrador decide
âncoras e rerank visual.

```bash
uv run python -m enricher sections nota.md
uv run python -m enricher search wikimedia --query "synapse" --top-k 4
uv run python -m enricher download https://example.com/image.png --vault ~/Obsidian/Anexos
uv run python -m enricher insert nota.md --section Mecanismo --image abc.webp --concept "recaptação de serotonina" --source wikimedia --source-url "https://commons.wikimedia.org/wiki/File:X"
```

Orquestrador canônico:

```bash
uv run python scripts/enrich_notes.py nota.md pasta/ "Wiki/**/*.md" [--config config.toml] [--force]
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

Fallback persistente, útil em Windows e em reinstalações:

```bash
# macOS/Linux
mkdir -p ~/.gemini/medical-notes-workbench
cp config.example.toml ~/.gemini/medical-notes-workbench/config.toml
cp .env.example ~/.gemini/medical-notes-workbench/.env
```

```powershell
# Windows PowerShell
New-Item -ItemType Directory -Force "$HOME\.gemini\medical-notes-workbench"
Copy-Item config.example.toml "$HOME\.gemini\medical-notes-workbench\config.toml"
Copy-Item .env.example "$HOME\.gemini\medical-notes-workbench\.env"
```

Edite o `config.toml` e a `.env` persistentes, não arquivos dentro de
`~/.gemini/extensions/medical-notes-workbench`. Essa pasta pertence ao bundle
auto-updatable e pode ser recriada a cada update. O enricher aceita
`SERPAPI_KEY` e `SERPAPI_API_KEY`; sem chave, `web_search` retorna `[]` e
Wikimedia continua funcionando.

### Python com uv

O projeto usa `uv` como interface oficial de Python. Em instalações da extensão,
mantenha a venv fora do bundle:

```powershell
# Windows PowerShell, a partir de ~/.gemini/extensions/medical-notes-workbench
.\scripts\reset_windows_python_uv.ps1
```

Para limpar Python global da Python Software Foundation/py launcher e deixar o
workbench rodando só com Python gerenciado pelo `uv`, use o fluxo completo:

```powershell
# PowerShell, a partir de ~/.gemini/extensions/medical-notes-workbench
.\scripts\bootstrap_windows_python_uv.ps1
```

Ou, se estiver no `cmd.exe`:

```bat
"%USERPROFILE%\.gemini\extensions\medical-notes-workbench\scripts\bootstrap_windows_python_uv.cmd"
```

O bootstrap atualiza o reset script, instala/atualiza `uv` se faltar, remove
Python global da PSF/py launcher, limpa entradas Python do PATH, desativa aliases
`python.exe`/`python3.exe` do WindowsApps quando possível, recria a venv
persistente e roda os checks.
Para inventariar antes de remover:

```powershell
.\scripts\reset_windows_python_uv.ps1 -RemoveGlobalPython
```

Se `where python` ainda apontar para `Microsoft\WindowsApps`, desative os
aliases `python.exe`/`python3.exe` nas configurações do Windows.

```bash
# macOS/Linux, a partir de ~/.gemini/extensions/medical-notes-workbench
mkdir -p ~/.gemini/medical-notes-workbench
export UV_PROJECT_ENVIRONMENT="$HOME/.gemini/medical-notes-workbench/.venv"
uv sync
uv run python -m enricher --help
```

Para comandos manuais da extensão, use `uv run python ...`. No Windows:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$HOME\.gemini\medical-notes-workbench\.venv"
uv run python scripts\mednotes\med_ops.py fix-wiki --dry-run --json
```

## Desenvolvimento

```bash
uv sync --extra dev --extra pdf
uv run python -m pytest
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
