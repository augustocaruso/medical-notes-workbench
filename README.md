# medical-notes-workbench

Workbench para criar, organizar e processar notas médicas didáticas em Markdown/Obsidian. O primeiro módulo empacotado é o `enricher`, uma toolbox Python que dá a um **agente externo** (Gemini CLI hoje, qualquer outro amanhã) primitivas pra enriquecer notas com imagens. A extensão também empacota um pipeline de subagents Gemini CLI que converte chats médicos brutos de `Chats_Raw` em notas no `Wiki_Medicina` usando uma CLI determinística (`med_ops.py`) para YAML, staging, publicação e linkagem.

Uso pessoal/estudo (fair use). Imagens são baixadas localmente para o vault Obsidian e referenciadas via `![[...]]`.

> **Fluxos gerais**:
> - `chat Gemini → /mednotes:create ou nota existente → /mednotes:enrich → enricher (chamado pelo agente)`.
> - `Chats_Raw → /mednotes:process-chats → subagents médicos → Wiki_Medicina → linker semântico`.
> - `nota/arquivo/escopo → /flashcards → flashcard_sources.py manifest → anki-mcp-twenty-rules.md → med-flashcard-maker → Anki MCP → Anki`.

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
- Slash commands `/mednotes:setup`, `/mednotes:create`, `/mednotes:enrich`, `/mednotes:process-chats`, `/mednotes:fix-wiki`, `/mednotes:link`, `/flashcards` e `/mednotes:status`.
- Skills `create-medical-note` e `enrich-medical-note`.
- Subagents Gemini para triagem, arquitetura clínica, curadoria de catálogo, guarda de publicação e criação de flashcards.
- Knowledge docs preservando a redação original das skills médicas funcionais e
  a cópia operacional `anki-mcp-twenty-rules.md`.
- Hooks Gemini leves e estreitos: `mednotes_hook.mjs` bloqueia publishes
  inseguros do `med_ops.py`, registra dry-runs aprovados e faz preflight do Anki
  apenas antes de ferramentas Anki MCP.
- MCP global existente `anki-mcp` via `@ankimcp/anki-mcp-server`, incluindo o
  prompt MCP `twenty_rules`.
- Runtime Python mínimo (`src/`, `scripts/run_agent.py`, `pyproject.toml`).

### Med Chat Processor

O comando `/mednotes:process-chats` usa subagents Gemini CLI para transformar arquivos `.md` brutos de `Chats_Raw` em notas Obsidian no `Wiki_Medicina`.

Os subagents fazem raciocínio clínico e escrita; o script `scripts/mednotes/med_ops.py` faz as operações mecânicas:

```bash
python scripts/mednotes/med_ops.py validate
python scripts/mednotes/wiki_tree.py --max-depth 4 --audit
python scripts/mednotes/med_ops.py taxonomy-canonical
python scripts/mednotes/med_ops.py taxonomy-tree --max-depth 4
python scripts/mednotes/med_ops.py taxonomy-audit
python scripts/mednotes/med_ops.py taxonomy-migrate --dry-run --plan-output plano-taxonomia.json
python scripts/mednotes/med_ops.py taxonomy-migrate --apply --plan plano-taxonomia.json --receipt recibo-taxonomia.json
python scripts/mednotes/med_ops.py taxonomy-migrate --rollback --receipt recibo-taxonomia.json
python scripts/mednotes/med_ops.py taxonomy-resolve --taxonomy "Cardiologia/Arritmias" --title "Fibrilacao Atrial"
python scripts/mednotes/med_ops.py list-pending
python scripts/mednotes/med_ops.py list-triados
python scripts/mednotes/med_ops.py triage --raw-file chat.md --titulo "..."
python scripts/mednotes/med_ops.py stage-note --manifest batch.json --raw-file chat.md --taxonomy "Psiquiatria" --title "ISRS" --content nota-temp.md
python scripts/mednotes/med_ops.py publish-batch --manifest batch.json --dry-run
python scripts/mednotes/med_ops.py publish-batch --manifest batch.json
python scripts/mednotes/med_ops.py run-linker
```

Taxonomia segue uma regra rigida: `taxonomy` e apenas o caminho de pastas de
categoria sob as 5 grandes areas canonicas de `Wiki_Medicina`, e `title` vira o
arquivo `.md`. As areas sao `1. Clínica Médica`, `2. Cirurgia`,
`3. Ginecologia e Obstetrícia`, `4. Pediatria` e
`5. Medicina Preventiva`. Assim, o destino correto e
`1. Clínica Médica/Cardiologia/Arritmias/Fibrilacao_Atrial.md`, nao
`Cardiologia/Arritmias/Fibrilacao_Atrial/Fibrilacao_Atrial.md`. O pipeline
roda `scripts/mednotes/wiki_tree.py --max-depth 4 --audit` antes da escrita
para obter, em um único JSON, a taxonomia canônica, a árvore real existente e a
auditoria dry-run. Os subcomandos `taxonomy-canonical`, `taxonomy-tree` e
`taxonomy-audit` continuam disponíveis separadamente em `med_ops.py`.
`stage-note`/`publish-batch --dry-run`
canonizam especialidades como `Cardiologia` para `1. Clínica Médica/Cardiologia`
ou bloqueiam variacoes incoerentes. `taxonomy-audit` faz apenas dry-run de
organizacao do vault e aponta movimentos sugeridos, duplicatas e pastas sem
mapeamento. `taxonomy-migrate` corrige apenas movimentos inequívocos de
diretórios legados para destinos canônicos inexistentes; destinos já existentes,
duplicados e pastas sem mapeamento ficam bloqueados para revisão. Toda aplicação
gera recibo JSON e pode ser revertida com `--rollback --receipt`. Nova pasta de
taxonomia e excecao: use
`--allow-new-taxonomy-leaf` somente para uma unica folha nova sob um pai
existente e depois de aprovacao explicita.

Dentro do Gemini CLI, o hook bloqueia `publish-batch` real quando nao existe um
`publish-batch --dry-run` recente do mesmo manifest. O recibo fica em
`~/.gemini/medical-notes-workbench/hooks/med-ops-dry-runs.json` por 30 minutos
por padrao; `MEDNOTES_HOOK_STATE_DIR` e `MEDNOTES_PUBLISH_DRY_RUN_TTL_MS`
permitem ajustar esse comportamento. Mensagens uteis aparecem via JSON oficial
do hook (`systemMessage` ou `reason`), nunca como texto solto em stdout.

Defaults internos preservam os caminhos Windows reais de raw/wiki/linker. O catálogo fica em `~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json`, fora da pasta auto-updatable da extensão. Para testar em macOS/Linux, use flags, variáveis `MED_RAW_DIR`/`MED_WIKI_DIR`/`MED_CATALOG_PATH`/`MED_LINKER_PATH`, ou `[chat_processor]` no `config.toml`.

O subagent `med-knowledge-architect` segue o Padrão Ouro preservado em
`extension/knowledge/knowledge-architect.md`. Notas geradas para
`Wiki_Medicina` também precisam cumprir o contrato visual legado: definição
curta após o título, todo `##` começa com emoji semântico, há
`## 🏁 Fechamento` com `### Resumo`, `### Key Points` e
`### Frase de Prova`, há `## 🔗 Notas Relacionadas`, e o rodapé final é
exatamente `---`, `[Chat Original](https://gemini.google.com/app/<fonte_id>)`
e `[[_Índice_Medicina]]`. `stage-note` e `publish-batch --dry-run` rejeitam
notas fora desse padrão. O linker roda no final do lote. O linker também pode
ser chamado diretamente:

```bash
python scripts/mednotes/med_ops.py validate-note --content nota-temp.md --title "Titulo" --raw-file chat.md --json
python scripts/mednotes/med_ops.py fix-note --content nota-temp.md --title "Titulo" --raw-file chat.md --output nota-fixed.md --json
python scripts/mednotes/med_ops.py validate-wiki --wiki-dir ~/Wiki_Medicina --json
python scripts/mednotes/med_ops.py fix-wiki --wiki-dir ~/Wiki_Medicina --json
python scripts/mednotes/med_ops.py fix-wiki --wiki-dir ~/Wiki_Medicina --apply --backup --json
```

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

O módulo de flashcards usa o MCP global existente `anki-mcp` configurado em
`~/.gemini/settings.json` com `@ankimcp/anki-mcp-server`. A extensão não declara
outro servidor Anki MCP no manifest, para evitar duplicação. Ele depende do Anki
Desktop com o add-on AnkiConnect respondendo em `http://127.0.0.1:8765`; o hook
`mednotes-ensure-anki` usa `mednotes_hook.mjs ensure-anki-before` para tentar
abrir/minimizar o Anki antes de ferramentas Anki e falha aberto com uma
mensagem util se o AnkiConnect nao responder. O preflight espera ate 20s por
padrao (`MEDNOTES_ANKI_START_TIMEOUT_MS`, teto de 20s) e usa lancamento sem
foco quando a plataforma permite: `open -g -j` no macOS e PowerShell com
`Start-Process -WindowStyle Minimized` no Windows. Manter o terminal em foco e
best-effort; se o sistema operacional ou o Anki focarem a janela, o hook nao
forca a reversao.

O prompt MCP puro é `/twenty_rules`. Ele fica reservado para o Anki MCP; a
extensão não cria um comando local com esse nome para não causar colisão. A
referência de origem no pacote MCP é
`@ankimcp/anki-mcp-server/dist/mcp/primitives/essential/prompts/twenty-rules.prompt/content.md`;
esse path é proveniência. Como subagents Gemini CLI não conseguem chamar um
slash prompt MCP e puxar seu conteúdo para o próprio contexto, a extensão
importa a metodologia em `extension/knowledge/anki-mcp-twenty-rules.md`.
`/flashcards` usa essa cópia local automaticamente; não é preciso executar
`/twenty_rules` antes.

O plano completo de evolução do módulo está em
[docs/flashcards-roadmap.md](docs/flashcards-roadmap.md).

Para uso diário, o comando top-level `/flashcards` aceita caminhos, múltiplos
arquivos, pastas, globs e filtros por tags Obsidian:

```bash
/flashcards ~/Wiki_Medicina/Cardiologia/Ponte_Miocardica.md
/flashcards ~/Wiki_Medicina/Cardiologia/*.md
/flashcards notas com tag #revisar em ~/Wiki_Medicina/Cardiologia
/flashcards notas na pasta Arritmias
```

Antes de chamar o subagent, `/flashcards` resolve o escopo com um manifest JSON
determinístico:

```bash
python extension/scripts/mednotes/flashcard_sources.py resolve \
  --scope "notas com tag #revisar em ~/Wiki_Medicina/Cardiologia" \
  --dry-run --skip-tag anki
```

O manifest lista apenas notas Markdown válidas e já inclui `deck`,
`obsidian://open?vault=...&file=...`, tags encontradas, hash do conteúdo e a
flag de confirmação para lotes com mais de 10 arquivos. Por padrão, notas já
marcadas com a tag Obsidian `anki` são puladas para evitar duplicação; elas
aparecem em `skipped_notes`. Para refazer cards de notas já marcadas, rode sem
`--skip-tag anki`. Se a raiz do vault não estiver clara, rode novamente com
`--vault-root`/`--wiki-dir`.

Para confirmação humana, o mesmo resolvedor tem uma prévia textual:

```bash
python extension/scripts/mednotes/flashcard_sources.py preview \
  --scope "notas com tag #revisar em ~/Wiki_Medicina/Cardiologia" \
  --dry-run --skip-tag anki
```

Antes de gravar no Anki, o subagent primeiro devolve um manifesto de
`candidate_cards` junto com `preferred_model` e `models` capturados via
`modelNames`/`modelFieldNames`. O fluxo então tem checagens determinísticas:

```bash
python extension/scripts/mednotes/anki_model_validator.py validate --models-json models.json
python extension/scripts/mednotes/flashcard_index.py check --candidates candidate_cards.json
```

Para o caminho consolidado usado pelo agente, prefira:

```bash
python extension/scripts/mednotes/flashcard_pipeline.py prepare --input run.json
python extension/scripts/mednotes/flashcard_pipeline.py apply --input accepted-run.json
```

O `prepare` devolve `anki_find_queries`; o subagent usa essas consultas com
`findNotes` antes de `addNotes` para pular cards que já existam no Anki, além da
idempotência local por hash.

Por padrão, `/flashcards` para aqui e mostra os cards no terminal antes de
gravar no Anki:

```bash
python extension/scripts/mednotes/flashcard_report.py preview-cards --input write-plan.json
```

Só depois da sua confirmação ele chama o Anki MCP. Para criar diretamente depois
das validações, peça explicitamente no comando, por exemplo:

```text
/flashcards --create ~/Wiki_Medicina/Cardiologia/Ponte_Miocardica.md
/flashcards criar diretamente notas com tag #revisar em Cardiologia
```

Depois que o Anki aceitar os cards, registre apenas os aceitos:

```bash
python extension/scripts/mednotes/flashcard_index.py record --accepted accepted_cards.json
```

O índice local padrão fica em
`~/.gemini/medical-notes-workbench/FLASHCARDS_INDEX.json`. Para auditar a cópia
local das Twenty Rules contra o pacote Anki MCP instalado:

```bash
python extension/scripts/mednotes/sync_anki_twenty_rules.py check
```

Para consolidar o fim da execução em um resumo legível:

```bash
python extension/scripts/mednotes/flashcard_report.py final --input run-result.json
```

Fluxo obrigatório: o agente lê o arquivo com `read_file`, usa somente esse
conteúdo como base factual, aplica `extension/knowledge/anki-mcp-twenty-rules.md`
como metodologia e segue `extension/knowledge/flashcard-ingestion.md` para as
regras locais:

- deck do Anki espelha o caminho Obsidian, por exemplo `Wiki_Medicina::Cardiologia::Ponte_Miocardica`;
- sem tags Anki por enquanto;
- cada card vindo de arquivo preenche o campo `Obsidian` com um deeplink
  portavel `obsidian://open?vault=...&file=...` para a nota que o gerou;
- campo `Verso Extra` começa com uma quebra visual antes do conteúdo.

Tags Obsidian servem apenas para selecionar notas; os cards do Anki continuam
sem tags por enquanto. Depois que uma nota gerar pelo menos um card aceito pelo
Anki MCP, a extensão marca a nota-fonte com a tag Obsidian `anki` no
frontmatter usando o utilitário Python:

```bash
python extension/scripts/mednotes/obsidian_note_utils.py add-tag --tag anki nota.md
python extension/scripts/mednotes/obsidian_note_utils.py remove-tag --tag anki nota.md
python extension/scripts/mednotes/obsidian_note_utils.py deeplink nota.md
```

O deeplink usa nome do vault + caminho relativo da nota, e por isso continua
abrindo no Windows e no iPhone quando ambos têm o mesmo vault Obsidian no
iCloud. O formato `path=` absoluto fica disponível só como fallback local via
`--absolute-path`.

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
├── commands/*.toml
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
- [x] Etapa 10: módulo de flashcards Anki MCP (`/flashcards`, com proveniência no prompt MCP `/twenty_rules`)
- [ ] Etapa 11: adapters médicos curados (Radiopaedia, OpenStax, NIH Open-i)
- [ ] Etapa 12: biblioteca PDF como source adapter

## Testes

```bash
pytest
```

Sem rede no CI: adapters usam `httpx.MockTransport` com fixtures gravadas.

## Convenções

Ver [`CLAUDE.md`](CLAUDE.md) e [`AGENTS.md`](AGENTS.md) (espelhos).
