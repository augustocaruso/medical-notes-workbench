# medical-notes-workbench

Workbench para criar, organizar e processar notas médicas didáticas em Markdown/Obsidian. O primeiro módulo empacotado é o `enricher`, uma toolbox Python que dá a um **agente externo** (Gemini CLI hoje, qualquer outro amanhã) primitivas pra enriquecer notas com imagens. A extensão também empacota um pipeline de subagents Gemini CLI que converte chats médicos brutos de `Chats_Raw` em notas no `Wiki_Medicina` usando uma CLI determinística (`med_ops.py`) para YAML, staging, publicação e linkagem.

Uso pessoal/estudo (fair use). Imagens são baixadas localmente para o vault Obsidian e referenciadas via `![[...]]`.

> **Fluxos gerais**:
> - `chat Gemini → /mednotes:create ou nota existente → /mednotes:enrich → enricher (chamado pelo agente)`.
> - `Chats_Raw → /mednotes:process-chats → subagents médicos → Wiki_Medicina → linker semântico`.
> - `nota/arquivo → /twenty_rules (prompt MCP) → /mednotes:twenty_rules <path> ou /mednotes:flashcards → med-flashcard-maker → Anki MCP → Anki`.

## Subcomandos (toolbox)

Cada subcomando faz uma coisa e devolve JSON na stdout.

| Comando | Função |
|---|---|
| `enricher sections <nota.md>` | Lista headings com `section_path`, `level`, `start_line`, `end_line`. |
| `enricher search <source> --query <q> [--visual-type T] [--top-k N]` | Devolve candidatas da fonte (`wikimedia`, `web_search`). |
| `enricher download <url> [--vault P] [--max-dim N]` | Baixa, valida, dedupe SHA-256. *(em construção)* |
| `enricher insert <nota.md> --section P --image F --concept C --source S --source-url U` | Insere bloco e atualiza frontmatter aditivamente. |

Loop típico do agente: `sections` → escolhe âncoras lendo a nota → `search` por âncora → escolhe melhor candidata (visão multimodal) → `download` → `insert`.

## Orquestrador (gemini CLI)

O repo inclui `scripts/run_agent.py` — um orquestrador end-to-end que dirige o gemini CLI:

```bash
python scripts/run_agent.py ~/Obsidian/Medicina/isrs.md
```

Faz: gemini decide âncoras → busca em todas as fontes habilitadas → baixa thumbs → gemini ranqueia visualmente → baixa imagens escolhidas → insere blocos. Durante a execução, imprime progresso estruturado em tempo real: configuração carregada, âncoras, contagem por fonte, miniaturas, escolha do rerank, download e resumo final. Quando SerpAPI fornece thumbnail, ele vira fallback se a imagem original bloquear. Se o Gemini devolver texto em vez de JSON, o orquestrador tenta uma autocorreção antes de falhar. Idempotente: se a nota já tem `images_enriched: true`, pula (use `--force` pra refazer).

Pré-requisitos:
- `gemini` no PATH (ou ajuste `[gemini].binary` em `config.toml`)
- Login OAuth feito (`gemini auth` ou equivalente do seu CLI)

Ajustes em `[gemini]` do `config.toml`:
- `binary`, `model_anchors`, `model_rerank`
- `max_candidates_per_anchor` — teto de candidatas que vão pro rerank
- `timeout_seconds` — timeout por chamada ao gemini CLI (default: 120)

## Setup

```bash
git clone https://github.com/augustocaruso/medical-notes-workbench.git ~/Documents/medical-notes-workbench
cd ~/Documents/medical-notes-workbench

python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]              # core + testes
pip install -e .[dev,pdf]          # +biblioteca PDF (pdfplumber, pdf2image, pytesseract)

cp config.example.toml config.toml  # editar [vault].path

# Opcional: chave SerpAPI pra busca web genérica.
# O adapter lê SERPAPI_KEY do ambiente ou deste .env.
# Sem ela, `search web_search` devolve [] silenciosamente.
cp .env.example .env
```

> O enricher **não invoca LLM**. O agente que orquestra (gemini CLI etc.) é quem decide âncoras e ranqueia. Sem `gemini auth` aqui — isso é configuração do agente.

## Uso

```bash
# 1. listar seções de uma nota
python -m enricher sections nota.md

# 2. buscar imagens (Wikimedia)
python -m enricher search wikimedia --query "synapse" --top-k 4

# 2b. buscar via Google Images (SerpAPI)
SERPAPI_KEY=... python -m enricher search web_search --query "synapse diagram"

# 3. inserir uma imagem já baixada
python -m enricher insert nota.md \
    --section Mecanismo \
    --image abc123.webp \
    --concept "recaptação de serotonina" \
    --source wikimedia \
    --source-url https://commons.wikimedia.org/wiki/File:X
```

## Gemini CLI Extension

O projeto também pode ser empacotado como extensão do Gemini CLI:

```bash
npm run build:gemini-cli-extension
gemini extensions validate dist/gemini-cli-extension
gemini extensions link dist/gemini-cli-extension
```

A extensão inclui:

- `GEMINI.md` com contexto operacional.
- Slash commands `/mednotes:setup`, `/mednotes:create`, `/mednotes:enrich`, `/mednotes:process-chats`, `/mednotes:link`, `/mednotes:flashcards`, `/mednotes:twenty_rules` e `/mednotes:status`.
- Skills `create-medical-note` e `enrich-medical-note`.
- Subagents Gemini para triagem, arquitetura clínica, curadoria de catálogo, guarda de publicação e criação de flashcards.
- Knowledge docs preservando a redação original das skills médicas funcionais.
- Hooks Gemini leves para contexto, guardrails do `med_ops.py` e inicialização do Anki antes de ferramentas Anki MCP.
- MCP `anki` via `@ankimcp/anki-mcp-server`, incluindo o prompt MCP `twenty_rules`.
- Runtime Python mínimo (`src/`, `scripts/run_agent.py`, `pyproject.toml`).

### Med Chat Processor

O comando `/mednotes:process-chats` usa subagents Gemini CLI para transformar arquivos `.md` brutos de `Chats_Raw` em notas Obsidian no `Wiki_Medicina`.

Os subagents fazem raciocínio clínico e escrita; o script `scripts/mednotes/med_ops.py` faz as operações mecânicas:

```bash
python scripts/mednotes/med_ops.py validate
python scripts/mednotes/med_ops.py list-pending
python scripts/mednotes/med_ops.py list-triados
python scripts/mednotes/med_ops.py triage --raw-file chat.md --titulo "..."
python scripts/mednotes/med_ops.py stage-note --manifest batch.json --raw-file chat.md --taxonomy "Psiquiatria/ISRS" --title "ISRS" --content nota-temp.md
python scripts/mednotes/med_ops.py publish-batch --manifest batch.json --dry-run
python scripts/mednotes/med_ops.py publish-batch --manifest batch.json
python scripts/mednotes/med_ops.py run-linker
```

Defaults internos preservam os caminhos Windows reais de raw/wiki/linker. O catálogo fica em `~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json`, fora da pasta auto-updatable da extensão. Para testar em macOS/Linux, use flags, variáveis `MED_RAW_DIR`/`MED_WIKI_DIR`/`MED_CATALOG_PATH`/`MED_LINKER_PATH`, ou `[chat_processor]` no `config.toml`.

O subagent `med-knowledge-architect` segue o Padrão Ouro preservado em
`extension/knowledge/knowledge-architect.md`; o linker roda no final do lote. O
linker também pode ser chamado diretamente:

```bash
python scripts/mednotes/med_linker.py --wiki-dir ~/Wiki_Medicina
python scripts/mednotes/med_linker.py ~/Wiki_Medicina/Cardiologia/Arritmias/Fibrilacao_Atrial.md
```

Para auditoria antes de alterar o grafo, use:

```bash
python scripts/mednotes/med_linker.py \
  --wiki-dir ~/Wiki_Medicina \
  --catalog ~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json \
  --dry-run --json
```

O catálogo é a fonte primária de vocabulário; nomes de arquivos e aliases YAML
entram como fallback.

Subagents do pipeline:

- `med-chat-triager`
- `med-knowledge-architect`
- `med-catalog-curator`
- `med-publish-guard`

### Anki Flashcards

O módulo de flashcards usa o MCP `anki` empacotado pela extensão com
`@ankimcp/anki-mcp-server` em modo STDIO. Ele depende do Anki Desktop com o
add-on AnkiConnect respondendo em `http://127.0.0.1:8765`; o hook
`mednotes-ensure-anki` tenta abrir/minimizar o Anki antes de ferramentas Anki.

O prompt MCP puro é `/twenty_rules`. Ele fica reservado para o Anki MCP; a
extensão não cria um comando local com esse nome para não causar colisão. Para
arquivo único, carregue o prompt MCP e depois use o wrapper da extensão:

```bash
/twenty_rules
/mednotes:twenty_rules ~/Wiki_Medicina/Cardiologia/Ponte_Miocardica.md
```

Fluxo obrigatório: o agente lê o arquivo com `read_file`, usa somente esse
conteúdo como base factual, aplica o prompt MCP `/twenty_rules` como metodologia
e segue `extension/knowledge/flashcard-ingestion.md` para as regras locais:

- deck do Anki espelha o caminho Obsidian, por exemplo `Wiki_Medicina::Cardiologia::Ponte_Miocardica`;
- sem tags por enquanto;
- campo `Verso Extra` começa com uma quebra visual antes do conteúdo.

O comando mais geral `/mednotes:flashcards` usa o mesmo subagent
`med-flashcard-maker`, mas aceita briefing, trecho colado ou fonte sem caminho.

Para publicar uma branch auto-updatable:

```bash
npm run publish:gemini-cli-extension
```

Isso força o conteúdo de `dist/gemini-cli-extension` para a branch
`gemini-cli-extension`, com `gemini-extension.json` na raiz.

Instalação auto-updatable para usuários:

```bash
gemini extensions install https://www.github.com/augustocaruso/medical-notes-workbench.git --ref=gemini-cli-extension --auto-update --consent
```

O `www.github.com` força o Gemini CLI a instalar via `git clone` direto. Sem
isso, algumas versões tentam buscar uma GitHub Release para o `--ref` antes de
cair para clone e mostram um 404 inofensivo.

Durante/apos a instalação, configure a SerpAPI para busca web:

```bash
gemini extensions config medical-notes-workbench SERPAPI_KEY
```

Para obter a chave, crie uma conta em [SerpAPI](https://serpapi.com/), abra o
dashboard e copie a API key. A setting é sensível e fica no escopo user/keychain
do Gemini CLI; updates normais da extensão não pedem a chave de novo. Sem essa
chave, a extensão ainda funciona com Wikimedia, mas `web_search` fica
desativado.

## Estrutura

```
src/enricher/
├── cli.py            entry point com subcomandos (python -m enricher <cmd>)
├── config.py         carrega config.toml + defaults
├── frontmatter.py    leitura/escrita aditiva do YAML
├── insert.py         markdown surgery (parse_sections, insert_images)
├── download.py       fetch browser-like + Pillow + SHA-256 dedupe
├── cache.py          SQLite: candidates (TTL 30d), images (permanente)
└── sources/          adapters plugáveis (wikimedia, web_search, ...)
```

Fontes da extensão Gemini CLI:

```
extension/
├── GEMINI.md
├── commands/mednotes/*.toml
├── skills/*/SKILL.md
├── knowledge/*.md
├── agents/*.md
├── hooks/hooks.json
└── scripts/
    ├── hooks/*.mjs
    └── mednotes/*.py
```

## Status

Em construção:

- [x] Etapa 1: andaime
- [x] Etapa 2: `frontmatter` + `insert` com testes
- [x] Etapa 3: cache SQLite + adapter Wikimedia
- [x] Etapa 4: realinhamento toolbox (CLI subcomandos `sections`/`search`/`insert` + adapter `web_search` SerpAPI)
- [x] Etapa 5: `download.py` + subcomando `download`
- [x] Etapa 6: orquestrador `scripts/run_agent.py` (gemini CLI)
- [x] Etapa 7: empacotamento como extensão Gemini CLI
- [x] Etapa 8: migração para Medical Notes Workbench
- [x] Etapa 9: pipeline Gemini CLI com subagents, knowledge docs e `med_ops.py` seguro
- [x] Etapa 10: módulo de flashcards Anki MCP (`/twenty_rules`, `/mednotes:twenty_rules`, `/mednotes:flashcards`)
- [ ] Etapa 11: adapters médicos curados (Radiopaedia, OpenStax, NIH Open-i)
- [ ] Etapa 12: biblioteca PDF como source adapter

## Testes

```bash
pytest
```

Sem rede no CI: adapters usam `httpx.MockTransport` com fixtures gravadas.

## Convenções

Ver [`CLAUDE.md`](CLAUDE.md) e [`AGENTS.md`](AGENTS.md) (espelhos).
