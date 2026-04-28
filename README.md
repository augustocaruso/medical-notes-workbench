# medical-notes-workbench

Workbench para criar, organizar e processar notas médicas didáticas em Markdown/Obsidian. O primeiro módulo empacotado é o `enricher`, uma toolbox Python que dá a um **agente externo** (Gemini CLI hoje, qualquer outro amanhã) primitivas pra enriquecer notas com imagens. Fontes: Wikimedia Commons, busca web (SerpAPI); futuramente Radiopaedia, OpenStax, NIH Open-i, biblioteca PDF.

Uso pessoal/estudo (fair use). Imagens são baixadas localmente para o vault Obsidian e referenciadas via `![[...]]`.

> **Fluxo geral**: `chat Gemini → /mednotes:create ou nota existente → /mednotes:enrich → enricher (chamado pelo agente)`.

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
- Slash commands `/mednotes:setup`, `/mednotes:create`, `/mednotes:enrich` e `/mednotes:status`.
- Skills `create-medical-note` e `enrich-medical-note`.
- Runtime Python mínimo (`src/`, `scripts/run_agent.py`, `pyproject.toml`).

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
dashboard e copie a API key. Sem essa chave, a extensão ainda funciona com
Wikimedia, mas `web_search` fica desativado.

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
└── skills/*/SKILL.md
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
- [ ] Etapa 9: adapters médicos curados (Radiopaedia, OpenStax, NIH Open-i)
- [ ] Etapa 10: biblioteca PDF como source adapter

## Testes

```bash
pytest
```

Sem rede no CI: adapters usam `httpx.MockTransport` com fixtures gravadas.

## Convenções

Ver [`CLAUDE.md`](CLAUDE.md) e [`AGENTS.md`](AGENTS.md) (espelhos).
