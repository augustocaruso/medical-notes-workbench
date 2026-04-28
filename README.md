# medical-notes-enricher

Toolbox Python que dá a um **agente externo** (gemini CLI hoje, qualquer outro amanhã) primitivas pra enriquecer notas médicas didáticas em Markdown com imagens. Fontes: Wikimedia Commons, busca web (SerpAPI); futuramente Radiopaedia, OpenStax, NIH Open-i, biblioteca PDF.

Uso pessoal/estudo (fair use). Imagens são baixadas localmente para o vault Obsidian e referenciadas via `![[...]]`.

> **Fluxo geral**: `chat Gemini → skill upstream (chat → nota didática) → enricher (chamado pelo agente)`. A skill upstream não é parte deste projeto.

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

Faz: gemini decide âncoras → busca em todas as fontes habilitadas → baixa thumbs → gemini ranqueia visualmente → baixa imagens escolhidas → insere blocos. Idempotente: se a nota já tem `images_enriched: true`, pula (use `--force` pra refazer).

Pré-requisitos:
- `gemini` no PATH (ou ajuste `[gemini].binary` em `config.toml`)
- Login OAuth feito (`gemini auth` ou equivalente do seu CLI)

Ajustes em `[gemini]` do `config.toml`:
- `binary`, `model_anchors`, `model_rerank`
- `image_flag` (default `--image`) — adapte se seu CLI usa outro flag pra anexar imagens
- `max_candidates_per_anchor` — teto de candidatas que vão pro rerank

## Setup

```bash
git clone <este-repo> ~/Documents/medical-notes-enricher
cd ~/Documents/medical-notes-enricher

python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]              # core + testes
pip install -e .[dev,pdf]          # +biblioteca PDF (pdfplumber, pdf2image, pytesseract)

cp config.example.toml config.toml  # editar [vault].path

# Opcional: chave SerpAPI pra busca web genérica.
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

## Estrutura

```
src/enricher/
├── cli.py            entry point com subcomandos (python -m enricher <cmd>)
├── config.py         carrega config.toml + defaults
├── frontmatter.py    leitura/escrita aditiva do YAML
├── insert.py         markdown surgery (parse_sections, insert_images)
├── download.py       fetch + Pillow + SHA-256 dedupe (em construção)
├── cache.py          SQLite: candidates (TTL 30d), images (permanente)
└── sources/          adapters plugáveis (wikimedia, web_search, ...)
```

## Status

Em construção:

- [x] Etapa 1: andaime
- [x] Etapa 2: `frontmatter` + `insert` com testes
- [x] Etapa 3: cache SQLite + adapter Wikimedia
- [x] Etapa 4: realinhamento toolbox (CLI subcomandos `sections`/`search`/`insert` + adapter `web_search` SerpAPI)
- [x] Etapa 5: `download.py` + subcomando `download`
- [x] Etapa 6: orquestrador `scripts/run_agent.py` (gemini CLI)
- [ ] Etapa 6: adapters médicos curados (Radiopaedia, OpenStax, NIH Open-i)
- [ ] Etapa 7: biblioteca PDF como source adapter

## Testes

```bash
pytest
```

Sem rede no CI: adapters usam `httpx.MockTransport` com fixtures gravadas.

## Convenções

Ver [`CLAUDE.md`](CLAUDE.md) e [`AGENTS.md`](AGENTS.md) (espelhos).
