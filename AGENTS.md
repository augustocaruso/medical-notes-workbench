# medical-notes-workbench

Workbench para criação, organização e processamento de notas médicas didáticas em Markdown/Obsidian. O primeiro módulo interno é o `enricher`, uma toolbox Python que dá a um **agente externo** (gemini CLI hoje, qualquer outro amanhã) primitivas pra enriquecer notas com imagens de várias fontes (Wikimedia, busca web via SerpAPI; futuramente Radiopaedia, OpenStax, NIH Open-i, biblioteca PDF local). As imagens são baixadas localmente para o vault Obsidian e referenciadas via `![[...]]`.

Uso pessoal/estudo do usuário (estudante/profissional de medicina) — fair use, sem distinção por licença, toda imagem escolhida baixa e embeda.

## Contexto

- **Fluxo geral do enricher**: `chat Gemini → /mednotes:create ou nota existente → /mednotes:enrich → enricher (chamado pelo agente)`.
- **Fluxo geral do chat processor**: `Chats_Raw → /mednotes:process-chats → subagents médicos → Wiki_Medicina → med_linker`.
- **Fluxo geral dos flashcards**: `nota/arquivo/escopo → /flashcards → flashcard_sources.py manifest → anki-mcp-twenty-rules.md → med-flashcard-maker → Anki MCP → Anki`.
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

Saída é log estruturado e flushado em tempo real em stderr/stdout: configuração carregada, âncoras, contagem por fonte, miniaturas, escolha do rerank, download e resumo final. Exit codes: `0` ok / `4` sem vault / `6` nota sem headings / `7` gemini falhou ou retornou JSON inválido mesmo após retry / `8` seção fantasma.

Idempotente: pula notas com `images_enriched: true`. `--force` ignora.

### Extensão Gemini CLI

O repo também gera um bundle em `dist/gemini-cli-extension`:

```bash
npm run build:gemini-cli-extension
gemini extensions validate dist/gemini-cli-extension
```

Fontes versionadas:

- `extension/GEMINI.md`
- `extension/commands/*.toml`
- `extension/commands/mednotes/*.toml`
- `extension/skills/*/SKILL.md`
- `extension/knowledge/*.md`
- `extension/agents/*.md`
- `extension/hooks/hooks.json`
- `extension/scripts/hooks/*.mjs`
- `scripts/build_gemini_cli_extension.py`
- `scripts/publish_gemini_cli_extension_branch.py`

O publish force-pusha o bundle para a branch `gemini-cli-extension`:

```bash
npm run publish:gemini-cli-extension
```

Instalação auto-updatable para usuários:

```bash
gemini extensions install https://www.github.com/augustocaruso/medical-notes-workbench.git --ref=gemini-cli-extension --auto-update --consent
```

O `www.github.com` força o Gemini CLI a instalar via `git clone` direto. Sem
isso, algumas versões tentam buscar uma GitHub Release para o `--ref` antes de
cair para clone e mostram um 404 inofensivo.

Configuração da SerpAPI:

```bash
gemini extensions config medical-notes-workbench SERPAPI_KEY
```

A chave vem do dashboard em https://serpapi.com/. Ela é uma setting sensível da
extensão no escopo user/keychain do Gemini CLI, então updates normais não
pedem a chave novamente. Sem ela, `web_search` devolve `[]` e a extensão usa
apenas as outras fontes habilitadas.

Como `dist/` é artefato gerado, não versionar no `main`.

### Pipeline Gemini CLI: `process-chats`

A extensão empacota um pipeline de subagents para converter chats brutos médicos
em notas Obsidian:

- Comando: `/mednotes:process-chats`.
- Knowledge docs preservados: `extension/knowledge/factory.md`,
  `extension/knowledge/knowledge-architect.md`,
  `extension/knowledge/semantic-linker.md`.
- CLI mecânica: `extension/scripts/mednotes/med_ops.py`.
- Linker: `extension/scripts/mednotes/med_linker.py`.
- Subagents: `med-chat-triager`, `med-knowledge-architect`,
  `med-catalog-curator`, `med-publish-guard`.
- Hooks: somente `BeforeTool`/`AfterTool` com matchers estreitos via
  `extension/scripts/hooks/mednotes_hook.mjs`. O modo `ensure-anki-before` roda
  apenas para ferramentas `mcp_anki-mcp_*`/`mcp_anki_*`; os modos
  `med-ops-before`/`med-ops-after` rodam apenas para `run_shell_command`.

`med_ops.py` é deliberadamente uma CLI determinística, não um hook: hooks só
guardam contexto/segurança. Toda alteração de YAML/status em `Chats_Raw`, todo
staging e todo publish real devem passar por `med_ops.py`.

Paralelização segura dos subagents passa por `med_ops.py plan-subagents`.
Triagem usa `--phase triage --max-concurrency 4`; arquitetura usa
`--phase architect --max-concurrency 3 --temp-root <tmp-agents>`. A unidade
indivisível é o raw chat: nunca lance dois subagents para o mesmo raw chat,
para a mesma nota temporária ou para a mesma nota final. Se um raw chat gerar
várias notas, um único `med-knowledge-architect` decide e devolve todas. Se só
houver um work item, use no máximo um subagent. Consolidação, `triage`,
`discard`, `stage-note`, catálogo, dry-run, publish e linker continuam seriais
no agente principal.

No `/mednotes:fix-wiki`, reescritas por LLM também devem ser planejadas com
`med_ops.py plan-subagents --phase style-rewrite --max-concurrency 3
--temp-root <tmp-rewrites>`. A unidade indivisível é uma nota Wiki existente:
nunca lance dois rewriters para o mesmo target. A validação e aplicação das
reescritas continuam seriais via `apply-style-rewrite`.

Antes de criar notas, o agente principal deve rodar
`scripts/mednotes/wiki_tree.py --max-depth 4 --audit` para obter em um único
JSON a taxonomia canônica, a árvore real existente e a auditoria dry-run. Os
subcomandos `med_ops.py taxonomy-canonical`,
`med_ops.py taxonomy-tree --max-depth 4` e `med_ops.py taxonomy-audit`
continuam disponíveis separadamente. A taxonomia canônica tem 5 grandes áreas:
`1. Clínica Médica`, `2. Cirurgia`,
`3. Ginecologia e Obstetrícia`, `4. Pediatria` e
`5. Medicina Preventiva`. `taxonomy` é só caminho de pastas de categoria sob
essas áreas; `title` vira o arquivo `.md`. O padrão correto é
`1. Clínica Médica/Cardiologia/Arritmias` + `Fibrilacao_Atrial.md`, nunca
`Cardiologia/Arritmias/Fibrilacao_Atrial/Fibrilacao_Atrial.md`. `stage-note` e
`publish-batch --dry-run` canonizam atalhos como `Cardiologia/Arritmias` para a
grande área correta e bloqueiam pastas inventadas; `--allow-new-taxonomy-leaf`
só deve ser usado para uma única folha nova sob pai existente com aprovação
explícita. `taxonomy-audit` é somente dry-run e não move arquivos.
`taxonomy-migrate --dry-run --plan-output <plano.json>` gera um plano de
correção para pastas legadas; `taxonomy-migrate --apply --plan <plano.json>
--receipt <recibo.json>` aplica só movimentos inequívocos sem merge automático;
`taxonomy-migrate --rollback --receipt <recibo.json>` desfaz o que foi aplicado.
Se o plano tiver `blocked`, o agente deve reportar e pedir decisão, não forçar.

O hook de `med_ops.py` bloqueia `publish-batch` real sem um
`publish-batch --dry-run` recente do mesmo manifest. O recibo fica em
`~/.gemini/medical-notes-workbench/hooks/med-ops-dry-runs.json` por 30 minutos
por default, com overrides `MEDNOTES_HOOK_STATE_DIR` e
`MEDNOTES_PUBLISH_DRY_RUN_TTL_MS`. Mensagens ao usuário devem sair pelo JSON do
hook (`systemMessage`/`reason`), nunca por stdout textual.

O conteúdo original das skills médicas funcionais deve ficar preservado ao
máximo em `extension/knowledge/`. Se uma instrução comum for fatorada em agente
ou comando, preserve o sentido e evite reescrever sem necessidade.

Defaults preservados:

- `C:\Users\leona\OneDrive\Chats_Raw`
- `C:\Users\leona\iCloudDrive\iCloud~md~obsidian\Wiki_Medicina`
- `~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json`
- `C:\Users\leona\.gemini\skills\med-auto-linker\med_linker.py`

Overrides aceitos por flags, variáveis `MED_RAW_DIR`, `MED_WIKI_DIR`,
`MED_CATALOG_PATH`, `MED_LINKER_PATH`, ou `[chat_processor]` em `config.toml`.

Regras de segurança do chat processor:

- Nunca sobrescrever nota existente silenciosamente.
- Sempre rodar `publish-batch --dry-run` antes do publish real.
- Só marcar raw chat como `processado` depois que todas as notas derivadas do
  manifest forem escritas.
- Não criar `.bak` por padrão; usar `--backup` apenas quando solicitado.
- Rejeitar taxonomia absoluta, com `..`, drive letter ou caracteres inseguros.
- Rejeitar taxonomia fora das 5 grandes áreas canônicas, que repete o título
  como pasta final ou cria raiz, especialidade/pasta intermediária fora da
  árvore existente.
- Permitir nova pasta apenas com `--allow-new-taxonomy-leaf`, limitada a uma
  folha sob pai existente.
- Corrigir bagunça preexistente somente via `taxonomy-migrate`: primeiro
  dry-run com plano, depois apply com recibo, e rollback disponível.
- Rodar o linker semântico uma vez ao final do lote.
- Preservar aliases exatos, notas relacionadas, callouts e `[[_Índice_Medicina]]`
  conforme `med-knowledge-architect`.
- Notas geradas para `Wiki_Medicina` devem obedecer ao contrato visual legado:
  definição curta após o título, todo `##` começa com emoji semântico, há
  `## 🏁 Fechamento` com `### Resumo`, `### Key Points` e
  `### Frase de Prova`, há `## 🔗 Notas Relacionadas`, e o rodapé final é
  exatamente `---`, `[Chat Original](https://gemini.google.com/app/<fonte_id>)`
  e `[[_Índice_Medicina]]`. `stage-note` e `publish-batch --dry-run` validam
  esse contrato e rejeitam notas fora do padrão. `validate-note`, `fix-note` e
  `validate-wiki` em `med_ops.py` fornecem diagnóstico estruturado, correção
  formal sem inventar conteúdo clínico e auditoria do vault inteiro. O auto-fix
  também espaça callouts standalone e normaliza tabelas Markdown, escapando `|`
  de aliases Obsidian dentro de células. `fix-wiki`
  roda correções formais em lote; use sem `--apply` para preview e com
  `--apply --backup` para escrever em segurança.

### Pipeline Gemini CLI: flashcards Anki

A extensão empacota um módulo de criação de flashcards:

- Comando público: `/flashcards`, que aceita um arquivo, múltiplos arquivos,
  diretórios, globs, tags Obsidian e instruções em linguagem natural.
- Subagent: `med-flashcard-maker`.
- MCP: usar o servidor global existente `anki-mcp`, via
  `@ankimcp/anki-mcp-server` em modo STDIO. A extensão não declara outro Anki
  MCP no manifest, para evitar duplicação com `~/.gemini/settings.json`.
- Prompt upstream: `/twenty_rules` é o prompt MCP puro do Anki MCP, não é um
  comando da extensão e não precisa ser executado antes de `/flashcards`. Como
  subagents não conseguem chamar slash prompts MCP e puxar o conteúdo para o
  próprio contexto, manter uma cópia operacional local em
  `extension/knowledge/anki-mcp-twenty-rules.md`.
- Path de origem do prompt no pacote MCP:
  `@ankimcp/anki-mcp-server/dist/mcp/primitives/essential/prompts/twenty-rules.prompt/content.md`.
  Esse path é proveniência upstream; o carregamento operacional é via
  `read_file` no arquivo local `anki-mcp-twenty-rules.md`.
- Regras locais fatoradas: `extension/knowledge/flashcard-ingestion.md`.
- Roadmap do módulo: `docs/flashcards-roadmap.md`. Use esse documento para
  priorizar melhorias futuras; `flashcard-ingestion.md` continua sendo a fonte
  operacional das regras do agente.
- Hook: `extension/scripts/hooks/mednotes_hook.mjs ensure-anki-before`, que
  tenta abrir/minimizar o Anki antes de ferramentas Anki MCP. O preflight espera
  ate 20s por default (`MEDNOTES_ANKI_START_TIMEOUT_MS`, teto de 20s) e tenta
  preservar foco do terminal por best-effort (`open -g -j` no macOS,
  `Start-Process -WindowStyle Minimized` no Windows).
- Seleção por tag no `/flashcards` usa tags Obsidian apenas para escolher notas;
  os cards criados no Anki continuam sem tags.
- Utilitário determinístico: `extension/scripts/mednotes/obsidian_note_utils.py`
  gera deeplinks portáveis `obsidian://open?vault=...&file=...` e
  adiciona/remove a tag Obsidian `anki` no frontmatter depois de sucesso no
  Anki.
- Resolver determinístico: `extension/scripts/mednotes/flashcard_sources.py`
  expande arquivos, diretórios, globs, pastas em linguagem natural e filtros por
  tag Obsidian para um manifest JSON com `deck`, `deeplink`,
  `vault_relative_path`, tags, hash de conteúdo e `skipped_notes`; o subcomando
  `preview` emite a mesma resolução em texto humano para confirmação.
- Índice local: `extension/scripts/mednotes/flashcard_index.py` filtra
  `candidate_cards` contra
  `~/.gemini/medical-notes-workbench/FLASHCARDS_INDEX.json` e registra somente
  cards aceitos pelo Anki.
- Validador de modelo: `extension/scripts/mednotes/anki_model_validator.py`
  valida que o note type capturado do Anki MCP tem `Frente`, `Verso`,
  `Verso Extra` e `Obsidian`.
- Sync das Twenty Rules: `extension/scripts/mednotes/sync_anki_twenty_rules.py`
  compara a cópia local com o prompt upstream do pacote Anki MCP.
- Relatório/preview: `extension/scripts/mednotes/flashcard_report.py` mostra
  os cards candidatos antes da escrita (`preview-cards`) e consolida notas
  processadas, cards criados, duplicados, pulos e erros (`final`).
- Pipeline determinístico: `extension/scripts/mednotes/flashcard_pipeline.py`
  prepara o plano de escrita (`prepare`) e aplica resultados aceitos (`apply`)
  juntando validação de modelo, idempotência, reprocessamento por hash e
  relatório final.

Contrato do `/flashcards <escopo>`:

1. Resolver o escopo com
   `python extension/scripts/mednotes/flashcard_sources.py resolve --scope "<args>" --dry-run --skip-tag anki`.
2. Ler cada arquivo em `manifest.notes[].path` com `read_file`.
3. Formular `candidate_cards` antes de gravar no Anki e devolver também
   `preferred_model` + `models` capturados via `modelNames`/`modelFieldNames`.
4. Preparar o plano com `flashcard_pipeline.py prepare`.
5. No modo padrão, mostrar os cards no terminal com
   `flashcard_report.py preview-cards` e só gravar depois de confirmação
   explícita do usuário.
6. Se o plano exigir confirmação de reprocessamento por fonte alterada, pedir
   confirmação antes de criar novos cards.
7. Antes de `addNotes`, rodar `findNotes` com as queries do plano e pular cards
   já existentes no Anki.
8. Usar exclusivamente o conteúdo desses arquivos como base factual ("O QUÊ").
9. Aplicar `extension/knowledge/anki-mcp-twenty-rules.md` e as regras locais de
   ingestão como metodologia ("COMO"). Não exigir que o usuário rode
   `/twenty_rules` antes.

Regras locais atuais dos flashcards:

- O deck do Anki espelha o caminho Obsidian. Exemplo:
  `Wiki_Medicina/Cardiologia/Ponte_Miocardica.md` vira
  `Wiki_Medicina::Cardiologia::Ponte_Miocardica`.
- Não adicionar tags Anki por enquanto.
- Todo card vindo de arquivo Markdown deve preencher o campo Anki `Obsidian`
  com o deeplink da nota-fonte gerado por
  `python extension/scripts/mednotes/obsidian_note_utils.py deeplink <nota.md>`.
  O link deve usar nome do vault + path relativo, não path absoluto, para abrir
  no Windows e no iPhone quando o mesmo vault está no iCloud.
- Ao preencher `Verso Extra`, prefixar o campo com uma quebra visual antes do
  conteúdo (`\n\n` em texto puro ou `<br><br>` em HTML).
- Depois que pelo menos um card de uma nota for criado, marcar somente essa
  nota com a tag Obsidian `anki` usando
  `python extension/scripts/mednotes/obsidian_note_utils.py add-tag --tag anki <nota.md>`.
  Para desfazer, usar `remove-tag --tag anki`.
- Por padrão, `/flashcards` pula notas que já têm tag Obsidian `anki` para
  evitar duplicação; se o usuário pedir refazer/regenerar, rode o resolver sem
  `--skip-tag anki`.
- Antes de gravar no Anki, use `flashcard_index.py check` para pular cards já
  registrados no índice local. Depois de sucesso no Anki, use
  `flashcard_index.py record` para registrar apenas os cards aceitos.
- Por padrão, `/flashcards` mostra os cards candidatos no terminal e pede
  confirmação antes de chamar `addNotes`. Modo direto só quando o usuário pedir
  explicitamente `--create`, `--direct`, `--yes`, `--no-preview`, "criar
  diretamente", "crie direto", "sem preview", "sem previa" ou "sem confirmação".
- Ao final, use `flashcard_report.py final` quando houver dados estruturados da
  execução para produzir um resumo consistente.
- O fluxo preferido e consolidado é `flashcard_pipeline.py prepare` antes do
  Anki MCP e `flashcard_pipeline.py apply` depois dos cards aceitos.
- `/flashcards` deve pedir confirmação antes de gravar lotes com mais de 10
  arquivos ou mais de 40 cards candidatos.
- Anki Desktop precisa estar instalado e o add-on AnkiConnect precisa responder
  em `http://127.0.0.1:8765`.

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
4. **Magic number > extensão da URL**: URLs do Google/Bing podem servir HTML quando o asset some — `Pillow.Image.open` é a única validação de que veio imagem real. Coberto por teste em `test_download.py`. **Headers browser-like**: `download.py` envia User-Agent configurável, `Accept` de imagem e `Referer` da página-fonte quando disponível. Isso destrava alguns CDNs/hotlink simples; Wikimedia também aceita. Quando SerpAPI fornece `thumbnail_url`, o orquestrador usa esse thumbnail como fallback se o original bloquear. Pra modo "respeitoso/identificável" troque `[download].user_agent` pra `medical-notes-workbench/0.1 (...)`.
5. **Dedupe SHA-256**: imagens iguais via fontes diferentes só baixam uma vez; o `image_sources` do frontmatter conta a primeira origem que achou.

## Regras de contribuição

- **Mínimo de dependências de runtime.** Hoje: `httpx`, `Pillow`, `PyYAML`. PDF (`pdfplumber`, `pdf2image`, `pytesseract`) é extra opcional `[pdf]`. Enricher **não chama LLM** — a inteligência semântica é do agente externo. Adicionar deps exige justificativa.
- Toda mudança em `frontmatter.py`, `insert.py` e `cli.py` precisa de teste em `tests/`.
- Toda mudança em `extension/scripts/mednotes/med_ops.py`
  precisa de teste em `tests/`.
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
