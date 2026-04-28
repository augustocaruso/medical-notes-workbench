# medical-notes-enricher

Toolbox Python que dá a um **agente externo** (gemini CLI hoje, qualquer outro amanhã) primitivas pra enriquecer notas médicas didáticas em Markdown com imagens de várias fontes (Wikimedia, busca web via SerpAPI; futuramente Radiopaedia, OpenStax, NIH Open-i, biblioteca PDF local). As imagens são baixadas localmente para o vault Obsidian e referenciadas via `![[...]]`.

Uso pessoal/estudo do usuário (estudante/profissional de medicina) — fair use, sem distinção por licença, toda imagem escolhida baixa e embeda.

## Contexto

- **Fluxo geral**: `chat Gemini → skill upstream (chat → nota didática) → enricher (chamado pelo agente)`. A skill upstream **não é parte deste projeto**. Quando ela existir, define o frontmatter da nota didática.
- **Entrada**: arquivo `.md` da nota didática. Schema do frontmatter é **livre** — o enricher é agnóstico. Pode até não ter frontmatter.
- **Saída**: o mesmo `.md`, in-place, com:
  - Imagens inseridas via `![[...]]` no fim das seções alvo, com caption (`*Figura: <conceito>.* *Fonte: <source> — <url>*`).
  - Frontmatter aditivo: `images_enriched: true`, `images_enriched_at`, `image_count`, `image_sources: [{source, count}]`.
  - **Princípio único**: enricher é **additive-only no frontmatter** — nunca remove nem altera chaves preexistentes; só anexa as suas no fim.
- **Quem decide âncoras e re-rank**: o agente. Ele tem visão multimodal e contexto pedagógico. O enricher não invoca LLM.

## Arquitetura

Toolbox de **subcomandos componíveis** (CLI), cada um devolvendo JSON na stdout pra ser consumido pelo agente:

| Subcomando | Função |
|---|---|
| `enricher sections <nota.md>` | Lista headings com `section_path`, `level`, `start_line`, `end_line`. O agente usa pra saber paths válidos antes de inserir. |
| `enricher search <source> --query <q> [--visual-type T] [--top-k N]` | Devolve `list[ImageCandidate]` da fonte indicada (`wikimedia`, `web_search`, ...). |
| `enricher download <url> [--vault PATH] [--max-dim N]` | Baixa, valida magic number, redimensiona, dedupe SHA-256, devolve `{sha, filename, width, height, bytes, cached}`. |
| `enricher insert <nota.md> --section P --image F --concept C --source S --source-url U` | Insere bloco no fim da seção e devolve JSON com o novo frontmatter resumido. |

Loop típico do agente: `sections` → decide âncoras lendo a nota → `search <source>` por âncora → escolhe a melhor candidata (visão multimodal própria) → `download` → `insert`. Repete por âncora.

### Orquestrador de referência: `scripts/run_agent.py`

O repo inclui um orquestrador-exemplo que dirige o gemini CLI ponta a ponta:

```bash
python scripts/run_agent.py path/da/nota.md [--config config.toml] [--force]
```

Fluxo: anchors prompt → fan-out de `search` → baixa thumbs (256px, sem cache) → rerank visual com gemini multimodal → `download` (full size, com cache) → `insert_images` em batch no fim. Se o gemini devolver texto em vez de JSON, o orquestrador tenta uma autocorreção antes de falhar.

A configuração específica do orquestrador vive em `[gemini]` no `config.toml` (binary, model_anchors, model_rerank, timeout_seconds). O **toolbox em si não invoca LLM** — esse script é uma camada acima e pode ser substituído por outro orquestrador (Claude Code skill, sistema próprio etc.) sem mudar o enricher.

**Idioma preferido das figuras**: `[enrichment].preferred_language` aceita `"pt-br"` (gemini gera 1 query PT + EN; SerpAPI usa `hl=pt-br&gl=br`; rerank prefere figura com texto em PT em empates), `"en"` ou `"any"` (default; só EN). Apenas `web_search.py` usa o param; Wikimedia não tem facets de idioma.

Cache: SQLite único (`cache.db`) compartilhado entre subcomandos:
- `candidates` (`(source, query, visual_type)` + TTL 30d) — evita re-bater APIs.
- `images` (`sha256` permanente) — evita re-baixar e mantém dedupe entre invocações.
- `anchors` — tabela existe por compat, mas hoje **não é populada pelo enricher** (anchors são do agente). Pode ser usada pelo agente como cache próprio se quiser.

## Interface com o agente

Existem **dois níveis** de uso, cada um adequado a um perfil de agente:

```
NÍVEL 2 (alto): scripts/run_agent.py nota.md  →  loop completo embutido
NÍVEL 1 (baixo): subcomandos compostos pelo agente — máximo controle
```

### Nível 1 — toolbox (contratos JSON)

Agente roda subcomandos via shell, parseia stdout, decide próximos passos. **Cada subcomando = uma operação atômica, sem estado escondido entre chamadas** (exceto via `cache.db`, que é só otimização).

| Subcomando | Args principais | Stdout (JSON) | Exit codes |
|---|---|---|---|
| `enricher sections <nota>` | — | `[{section_path: [str], level: int, text: str, start_line: int, end_line: int}, …]` | `0` ok |
| `enricher search <source> --query <q>` | `--top-k N`, `--visual-type T` | `[ImageCandidate, …]` (lista vazia se sem key/sem resultado) | `0` ok |
| `enricher download <url>` | `--vault P`, `--max-dim N`, `--source S`, `--source-url U` | `{sha, filename, path, width, height, bytes, source, source_url, cached}` | `0` ok / `4` sem vault / `5` falha download |
| `enricher insert <nota>` | `--section P` (repetível, do topo à folha), `--image F`, `--concept C`, `--source S`, `--source-url U` | `{note, inserted, image_count, image_sources, images_enriched_at}` | `0` ok / `3` seção fantasma |

`ImageCandidate` (schema do `search`):
```json
{
  "source": "wikimedia",
  "source_url": "https://commons.wikimedia.org/wiki/File:X",
  "image_url": "https://upload.wikimedia.org/.../X_1600px.png",
  "thumbnail_url": "https://serpapi.com/.../thumb.jpg",
  "title": "File:X",
  "description": "…",
  "width": 1600, "height": 1200,
  "license": "CC BY-SA 4.0",
  "score": null
}
```

**Loop canônico do agente** (4 chamadas por âncora):
1. `sections nota.md` → conhece os paths válidos.
2. Lê o conteúdo da nota com seu próprio file-read e decide as âncoras.
3. Por âncora: `search wikimedia/web_search` → escolhe candidata olhando thumbs (visão multimodal) → `download <url>` → `insert nota.md --section ... --image ...`.
4. Repete até ter coberto a nota.

Convenções:
- **stdout = JSON parseável**, sempre. **stderr = mensagens humanas**.
- `--config PATH`: opcional, busca `config.toml` na árvore acima do CWD por default.
- `--section` no `insert` é **repetível** pra paths nested (`--section "ISRS" --section "Mecanismo"`).
- Falhas são **fail-soft no contrato do agente**: `search` devolve `[]` se a fonte não tem key (não levanta), e adapters individuais não derrubam outros.

### Nível 2 — orquestrador embutido

`scripts/run_agent.py` implementa o loop acima usando o `gemini` CLI internamente. Pro agente que apenas quer "enriquecer essa nota e me devolver", a interface é:

```bash
python scripts/run_agent.py path/da/nota.md [--config config.toml] [--force]
```

Saída é log estruturado em stderr/stdout (etapas numeradas, decisões do gemini). Exit codes: `0` ok / `4` sem vault / `6` nota sem headings / `7` gemini falhou ou retornou JSON inválido mesmo após retry / `8` seção fantasma.

Idempotente: pula notas com `images_enriched: true`. `--force` ignora.

### Extensão Gemini CLI

O repo também gera um bundle em `dist/gemini-cli-extension`:

```bash
npm run build:gemini-cli-extension
gemini extensions validate dist/gemini-cli-extension
```

Fontes versionadas:

- `gemini-cli-extension/GEMINI.md`
- `gemini-cli-extension/commands/enricher/*.toml`
- `gemini-cli-extension/skills/enrich-medical-note/SKILL.md`
- `scripts/build_gemini_cli_extension.py`
- `scripts/publish_gemini_cli_extension_branch.py`

O publish force-pusha o bundle para a branch `gemini-cli-extension`:

```bash
npm run publish:gemini-cli-extension
```

Instalação auto-updatable para usuários:

```bash
gemini extensions install https://github.com/augustocaruso/medical-notes-enricher.git --ref=gemini-cli-extension --auto-update --consent
```

Configuração da SerpAPI:

```bash
gemini extensions config medical-notes-enricher SERPAPI_KEY
```

A chave vem do dashboard em https://serpapi.com/. Sem ela, `web_search` devolve
`[]` e a extensão usa apenas as outras fontes habilitadas.

Como `dist/` é artefato gerado, não versionar no `main`.

### Adaptando pra outro orquestrador (Claude Code skill, Cursor, etc.)

`scripts/run_agent.py` é uma **implementação de referência**, não a única forma. Pra plugar outro agente:

1. Copie o padrão de chamadas (subprocess + parse JSON da stdout) — ou use a API Python diretamente (`from enricher import insert; insert.parse_sections(...)`).
2. Adapte `_invoke_gemini` (ou equivalente) pra chamar o LLM do seu agente — qualquer LLM multimodal serve.
3. Mantenha o fluxo: anchors → search → fetch_thumbs → rerank visual → download → insert.
4. Reutilize os prompts em `_ANCHORS_PROMPT_TEMPLATE` e `_RERANK_PROMPT_TEMPLATE` (genéricos, em PT-BR, funcionam com qualquer LLM razoável).

O **enricher core não muda** quando o agente muda — esse é o ponto da arquitetura toolbox.

## Pontos frágeis

1. **Markdown surgery (`insert.py`)**: identificar a seção alvo por `section_path` é onde mais bug aparece. Headings podem repetir, ter caracteres especiais, ou a nota usa setext (`===`/`---` underline) em vez de ATX (`#`). Sempre escrever teste antes da mudança.
2. **Frontmatter aditivo**: pyyaml reordena chaves se não passar `sort_keys=False`. Já fixado em `frontmatter.write`, mas verificar em todo round-trip. Nunca assumir schema da nota — qualquer chave preexistente sai intacta.
3. **Adapters de fonte**: APIs mudam silenciosamente. Cada adapter precisa de teste contra fixture HTTP local (`httpx.MockTransport`), não rede ao vivo no CI.
4. **Magic number > extensão da URL**: URLs do Google/Bing podem servir HTML quando o asset some — `Pillow.Image.open` é a única validação de que veio imagem real. Coberto por teste em `test_download.py`. **Headers browser-like**: `download.py` envia User-Agent configurável, `Accept` de imagem e `Referer` da página-fonte quando disponível. Isso destrava alguns CDNs/hotlink simples; Wikimedia também aceita. Quando SerpAPI fornece `thumbnail_url`, o orquestrador usa esse thumbnail como fallback se o original bloquear. Pra modo "respeitoso/identificável" troque `[download].user_agent` pra `medical-notes-enricher/0.1 (...)`.
5. **Dedupe SHA-256**: imagens iguais via fontes diferentes só baixam uma vez; o `image_sources` do frontmatter conta a primeira origem que achou.

## Regras de contribuição

- **Mínimo de dependências de runtime.** Hoje: `httpx`, `Pillow`, `PyYAML`. PDF (`pdfplumber`, `pdf2image`, `pytesseract`) é extra opcional `[pdf]`. Enricher **não chama LLM** — a inteligência semântica é do agente externo. Adicionar deps exige justificativa.
- Toda mudança em `frontmatter.py`, `insert.py` e `cli.py` precisa de teste em `tests/`.
- Adapters de fonte precisam de teste com fixture (HTTP/JSON gravado, via `httpx.MockTransport`).
- Cada subcomando do CLI deve emitir JSON parseável na stdout em sucesso, e mensagem humana em stderr + exit code != 0 em erro.
- Commits em português, Conventional Commits.
- **Documentação viva**: mudança que altere comportamento observável atualiza `README.md` + `CLAUDE.md` + `AGENTS.md` no mesmo commit. `CLAUDE.md` e `AGENTS.md` são espelhos.
- Antes de fechar tarefa: `pytest` verde.

## Fluxo de desenvolvimento

```bash
# instalar dev
pip install -e .[dev,pdf]

# subcomandos
python -m enricher sections nota.md
python -m enricher search wikimedia --query "synapse" --top-k 4
python -m enricher insert nota.md --section Mecanismo \
    --image abc.webp --concept "..." --source wikimedia --source-url "..."

# testes
pytest
```

Pra busca via SerpAPI, defina `SERPAPI_KEY` no ambiente ou no `.env` do projeto. Sem a chave, `search web_search` devolve `[]` (silencioso, por contrato).

## Política de licença e ética

Uso pessoal/estudo, fair use. Vault local, não publicado. Toda imagem escolhida pelo agente é baixada e embutida — sem ramo "link externo" para licenças desconhecidas. A URL da fonte fica registrada na caption pra rastreabilidade pessoal, não pra obrigação legal.
