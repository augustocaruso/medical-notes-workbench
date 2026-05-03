# Flashcard Ingestion Design

Este documento e a fonte unica das regras locais de ingestao para criacao de
flashcards medicos no Anki. A metodologia de formulacao dos cards vive em
`extension/knowledge/anki-mcp-twenty-rules.md`, uma copia operacional do prompt
MCP `/twenty_rules` fornecido pelo servidor Anki MCP global `anki-mcp`. Essa
copia local existe porque subagents Gemini CLI nao conseguem chamar slash
prompts MCP e puxar o conteudo para o proprio contexto. Este documento define
as decisoes de design da extensao Medical Notes Workbench.

## Modelos Anki Gerenciados

A skill mantém **dois** note types no Anki, ambos provisionados via Anki MCP a
partir dos arquivos em `extension/knowledge/anki-templates/`:

- `Medicina` (Q&A, `isCloze: false`) — campos `Frente`, `Verso`, `Verso Extra`,
  `Obsidian`. Cards de pergunta/resposta clássica.
- `Medicina Cloze` (cloze, `isCloze: true`) — campos `Texto`, `Verso Extra`,
  `Obsidian`. O campo `Texto` carrega `{{c1::...}}`, `{{c2::...}}`. Um card é
  gerado por grupo de cloze.

**Roteamento por card:** o subagent decide o modelo por candidato. Use
`Medicina Cloze` quando o card é definição/fato encadeado/enumeração curta
(Twenty Rules #5, #9). Use `Medicina` quando faz mais sentido reformular como
pergunta com resposta atômica. Cada `candidate_card` precisa declarar
`note_model` igual ao nome do modelo escolhido.

**Provisão dos modelos:** antes de gravar cards, a skill chama
`mcp_anki-mcp_modelNames` + `mcp_anki-mcp_modelFieldNames` para os dois nomes
acima e roda:

```bash
uv run python ${extensionPath}/scripts/mednotes/flashcards/install_models.py ensure --existing - --output -
```

O JSON resultante traz uma lista `actions` com chamadas `mcp_anki-mcp_createModel`
(quando o modelo não existe) ou `mcp_anki-mcp_updateModelTemplates` +
`mcp_anki-mcp_updateModelStyling` (quando o HTML/CSS divergiu da versão local).
Se algum modelo aparecer como `incompatible` (mesmo nome, campos diferentes),
pare e peça ao usuário para apagar/renomear no Anki Desktop antes de continuar.

Os arquivos HTML/CSS em `extension/knowledge/anki-templates/` são fonte de
verdade. Não edite os modelos manualmente no Anki Desktop — qualquer alteração
local é sobrescrita no próximo run.

## Regras De Conteúdo Para Cards Bonitos

Os templates só dão consistência visual; conteúdo limpo é responsabilidade da
skill. Aplique sempre:

- **Frente Q&A:** uma pergunta atômica, idealmente até 120 caracteres. Sem
  ponto-final desnecessário, sem prefixo "Pergunta:".
- **Verso Q&A:** 1-2 frases curtas, direto ao ponto. Não repita a pergunta,
  não comece com "A resposta é".
- **Verso Extra (ambos modelos):** raciocínio, contexto, mnemônicos, fontes
  curtas. Comece com `\n\n` em texto puro ou `<br><br>` em HTML para preservar
  o espaço visual exigido pelos templates. Use bullets `<ul><li>` ou `-` para
  enumerações curtas. Nunca repita o Verso/cloze.
- **Cloze (`Texto`):** enunciado fluente. Máximo 2-3 grupos `{{cN::...}}` por
  card. Cada cloze deve esconder uma unidade atômica de informação; nunca um
  parágrafo inteiro. Mantenha contexto suficiente para que o cloze fechado
  ainda permita ler o resto da frase com sentido.
- **Obsidian:** sempre o deeplink puro com o path real da nota
  (`obsidian://open?path=<absolute-note-path>`). O template renderiza como
  botão "Abrir no Obsidian" no rodapé.
- **Sem markdown solto:** evite headings (`#`, `##`), negrito Markdown
  (`**...**`) e código com crase. Use HTML quando precisar de ênfase
  (`<strong>`, `<em>`, `<code>`); o Anki não converte Markdown.

## Especificacoes De Design

1. Hierarquia de decks: reproduza fielmente a estrutura de diretorios do
   Obsidian como subdecks no Anki.

   Exemplo:

   ```text
   Wiki_Medicina/Cardiologia/Ponte_Miocardica.md
   -> Wiki_Medicina::Cardiologia::Ponte_Miocardica
   ```

   Para arquivos dentro de `Wiki_Medicina`, use `Wiki_Medicina` como raiz do
   deck, preserve os diretorios intermediarios e use o nome do arquivo sem
   `.md` como folha do deck.

   Nao reduza nem achate a hierarquia para caber em limitacoes de uma
   ferramenta. Se `mcp_anki-mcp_createDeck` recusar mais de dois niveis, tente
   criar os cards diretamente no deck completo com `mcp_anki-mcp_addNotes`/
   `mcp_anki-mcp_addNote`; se o MCP/Anki ainda recusar, reporte a falha sem
   trocar o deck por outro.

2. Tags Anki: nao adicionar tags por enquanto. Omita o campo `tags` ou envie
   lista vazia quando a ferramenta exigir esse campo. Tags Obsidian podem ser
   usadas para selecionar notas, mas nao devem virar tags Anki.

3. Formatacao do campo: antes de inserir conteudo no campo `Verso Extra`, adicione
   um espaco visual no inicio do campo. Use uma quebra de linha em texto puro
   (`\n\n`) ou `<br><br>` quando o conteudo for HTML.

4. Campo de origem: todo card criado a partir de uma nota Markdown precisa
   preencher um campo Anki chamado `Obsidian` com o deeplink da nota-fonte.
   Gere o deeplink do path real com o script deterministico:

   ```bash
   uv run python ${extensionPath}/scripts/mednotes/obsidian_note_utils.py deeplink <nota.md>
   ```

   O formato canonico para cards e
   `obsidian://open?path=<absolute-note-path>`, usando o path real resolvido da
   nota que o agente ja acessou. Isso evita prender o card a um vault inferido
   ou a um nome de vault especifico. Nao dependa da Obsidian CLI para extrair
   esse link; a CLI pode abrir/inspecionar notas, mas o deeplink deve ser
   calculado deterministicamente a partir do arquivo-fonte.

   O resolver ainda pode inferir a raiz do vault por `--vault-root`,
   `MED_WIKI_DIR`, um diretorio `.obsidian` ancestral ou a pasta
   `Wiki_Medicina` para preencher metadata (`vault_root`, `vault_relative_path`)
   e deck, mas o link do campo `Obsidian` nao deve depender dessa inferencia.
   Use `--vault-file` no utilitario apenas quando o usuario pedir
   explicitamente o formato `vault=...&file=...`.

5. Marcacao da nota-fonte: depois que pelo menos um card de uma nota for criado
   com sucesso no Anki, marque apenas essa nota com a tag Obsidian `anki` no
   frontmatter usando:

   ```bash
   uv run python ${extensionPath}/scripts/mednotes/obsidian_note_utils.py add-tag --tag anki <nota.md>
   ```

   Para desfazer a marcacao, use:

   ```bash
   uv run python ${extensionPath}/scripts/mednotes/obsidian_note_utils.py remove-tag --tag anki <nota.md>
   ```

   Nao marque notas sem cards criados. Em sucesso parcial, marque somente os
   arquivos que tiveram pelo menos um card aceito pelo Anki MCP.

## Regra De Base De Conhecimento

`/twenty_rules` sem namespace e reservado para o prompt MCP `twenty_rules` do
servidor global `anki-mcp`. A extensao nao declara outro Anki MCP no manifest,
para evitar duplicacao com `~/.gemini/settings.json`. A extensao tambem nao cria
um comando local chamado `/twenty_rules`, para evitar colisao com o prompt MCP.
Referencia de origem do prompt no pacote MCP:
`@ankimcp/anki-mcp-server/dist/mcp/primitives/essential/prompts/twenty-rules.prompt/content.md`.
Esse path e rastreabilidade/proveniencia upstream; o agente deve carregar a
metodologia por `read_file` em
`${extensionPath}/knowledge/anki-mcp-twenty-rules.md`.
O comando `/flashcards` aceita um arquivo, multiplos arquivos, diretorios,
globs, filtros por tag Obsidian e instrucoes em linguagem natural.
Tags Obsidian podem selecionar notas, mas nao devem virar tags Anki. A tag
Obsidian `anki` e reservada para marcar notas que ja geraram cards com sucesso.

Ao receber `/flashcards <escopo>`, o agente deve:

1. Resolver o escopo com `flashcard_sources.py resolve --scope "<escopo>" --dry-run`.
2. Usar `read_file` para extrair o conteudo de cada arquivo em
   `manifest.notes[].path`.
3. Formular cards candidatos sem gravar no Anki.
4. Preparar o plano com `flashcard_pipeline.py prepare`.
5. No modo padrao, mostrar os cards no terminal e pedir confirmacao antes de
   gravar. Criacao direta so e permitida quando o usuario pedir explicitamente
   modo direto.
6. Utilizar exclusivamente o conteudo lido desses arquivos como base de
   conhecimento, isto e, o "O QUE" dos flashcards.
7. Aplicar rigorosamente
   `${extensionPath}/knowledge/anki-mcp-twenty-rules.md` e as especificacoes
   deste documento como "COMO".

Nao use conhecimento externo para acrescentar fatos aos cards. Conhecimento
medico geral pode ser usado apenas para entender, segmentar e redigir melhor o
conteudo que ja esta presente no arquivo.

## Resolucao De Escopo Para `/flashcards`

1. Use o resolver deterministico antes de ler notas ou chamar o subagent:

   ```bash
   uv run python ${extensionPath}/scripts/mednotes/flashcard_sources.py resolve --scope "<argumentos>" --dry-run --skip-tag anki
   ```

   Ele devolve JSON parseavel na stdout com `schema`, `summary`, `scope`,
   `notes`, `skipped_notes` e `warnings`.

2. Arquivos explicitos, diretorios e globs: o resolver inclui apenas Markdown
   (`.md`/`.markdown`) e ignora `dist/`, `.git/`, caches, anexos, imagens e
   arquivos nao Markdown.
3. Tags Obsidian: o resolver filtra por frontmatter `tags`/`tag` e hashtags
   inline. A tag e apenas criterio de selecao, exceto pela marcacao pos-sucesso
   `anki` descrita acima.
4. Pastas em linguagem natural: para frases como `notas com tag #revisar na
   pasta Cardiologia`, o resolver procura a pasta dentro de `--vault-root`,
   `--wiki-dir`, `MED_WIKI_DIR`, `[chat_processor].wiki_dir` ou `[vault].path`.
5. Escopo ambiguo: se o resolver falhar pedindo raiz, pergunte ao usuario qual
   vault/wiki deve ser vasculhado e rode de novo com `--vault-root <pasta>` ou
   `--wiki-dir <pasta>`.
6. Notas ja processadas: por padrao, `/flashcards` deve passar
   `--skip-tag anki` para evitar duplicacao acidental. Se o usuario pedir
   explicitamente para refazer/regenerar/incluir notas ja marcadas, rode o
   resolver sem esse filtro. Notas puladas aparecem em `skipped_notes` com
   `skip_reason: "skip_tag"` e `skip_tags: ["anki"]`.
7. Manifest por nota: cada item em `notes` traz `path`, `deck`, `deeplink`,
   `vault_relative_path`, `link_mode`, `tags`, `already_marked_anki`,
   `content_sha256`, `line_count` e `heading_count`. Use esses campos como
   fonte operacional de deck/link; leia o conteudo factual separadamente com
   `read_file`.
8. Lotes grandes: se `summary.requires_confirmation` for verdadeiro, mostre a
   previa do manifest e peça confirmacao antes de formular/gravar no Anki.
   Para uma previa textual padronizada, use o subcomando irmao:

   ```bash
   uv run python ${extensionPath}/scripts/mednotes/flashcard_sources.py preview --scope "<argumentos>" --dry-run --skip-tag anki
   ```

   `preview` usa a mesma resolucao de `resolve`, mas emite texto humano em vez
   de JSON.

## Manifest De Cards Candidatos E Idempotencia

Depois de resolver fontes e ler os arquivos com `read_file`, o agente deve
formular cards candidatos antes de chamar o Anki MCP. O formato minimo e:

```json
{
  "source_manifest": {},
  "preferred_models": {
    "qa": "Medicina",
    "cloze": "Medicina Cloze"
  },
  "models": {
    "Medicina": ["Frente", "Verso", "Verso Extra", "Obsidian"],
    "Medicina Cloze": ["Texto", "Verso Extra", "Obsidian"]
  },
  "candidate_cards": [
    {
      "source_path": "/path/nota.md",
      "source_content_sha256": "sha256-da-nota",
      "deck": "Wiki_Medicina::Cardiologia::Ponte_Miocardica",
      "note_model": "Medicina",
      "fields": {
        "Frente": "...",
        "Verso": "...",
        "Verso Extra": "\n\n...",
        "Obsidian": "obsidian://open?path=..."
      }
    },
    {
      "source_path": "/path/nota.md",
      "source_content_sha256": "sha256-da-nota",
      "deck": "Wiki_Medicina::Cardiologia::Ponte_Miocardica",
      "note_model": "Medicina Cloze",
      "fields": {
        "Texto": "A {{c1::ponte miocárdica}} envolve mais frequentemente a {{c2::DA}}.",
        "Verso Extra": "\n\nDescrita pela primeira vez em 1737.",
        "Obsidian": "obsidian://open?path=..."
      }
    }
  ]
}
```

`preferred_model` (singular) ainda é aceito como atalho legado quando todos os
cards são Q&A. Para o fluxo padrão, use `preferred_models` com as duas chaves.

Antes de gravar no Anki, filtre duplicados locais:

```bash
uv run python ${extensionPath}/scripts/mednotes/flashcard_index.py check --candidates <candidate_cards.json>
```

Grave somente `new_cards`. Depois que o Anki MCP aceitar os cards, registre
somente os cards aceitos:

```bash
uv run python ${extensionPath}/scripts/mednotes/flashcard_index.py record --accepted <accepted_cards.json>
```

O indice padrao fica em
`~/.gemini/medical-notes-workbench/FLASHCARDS_INDEX.json` e pode ser sobrescrito
por `MED_FLASHCARDS_INDEX` ou `--index`. A tag Obsidian `anki` continua sendo um
marcador visual/filtro simples, mas a idempotencia real passa pelo indice local.

Para o fluxo completo, prefira o orquestrador deterministico:

```bash
uv run python ${extensionPath}/scripts/mednotes/flashcard_pipeline.py prepare --input <run.json>
uv run python ${extensionPath}/scripts/mednotes/flashcard_pipeline.py apply --input <accepted-run.json>
```

`prepare` combina validacao de modelo, status de fontes alteradas, checagem de
duplicidade, queries de `findNotes` e payload `anki_notes` para `addNotes`.
`apply` registra os cards aceitos e devolve um relatorio estruturado.

O payload de `prepare` precisa incluir os campos de modelo capturados do Anki
MCP. Em modo candidato, o subagent deve chamar `mcp_anki-mcp_modelNames` e
`mcp_anki-mcp_modelFieldNames`, escolher `preferred_model` quando houver um
modelo compativel e devolver `models` como mapa `{modelo: [campos...]}` ou lista
de objetos `{name, fields}`. Em modo de gravacao, use `anki_find_queries` do
plano para rodar `mcp_anki-mcp_findNotes` antes de `addNotes`; cards encontrados
no Anki devem ser pulados e reportados como duplicados.

## Preview Antes Da Escrita

O comportamento padrao de `/flashcards` e preview-first: depois de formular
`candidate_cards` e rodar `flashcard_pipeline.py prepare`, mostre os cards que
seriam criados no terminal e aguarde confirmacao explicita do usuario antes de
chamar `mcp_anki-mcp_addNotes`/`mcp_anki-mcp_addNote`.

Use o plano retornado por `prepare` como entrada:

```bash
uv run python ${extensionPath}/scripts/mednotes/flashcard_report.py preview-cards --input <write-plan.json>
```

Se o usuario nao confirmar, finalize sem escrever no Anki, sem registrar no
`FLASHCARDS_INDEX.json` e sem marcar notas com tag `anki`.

Modo direto opcional: se o usuario pedir explicitamente `--create`, `--direct`,
`--yes`, `--no-preview`, "criar diretamente", "crie direto", "sem preview",
"sem previa" ou "sem confirmacao", pule apenas essa confirmacao de preview dos
cards. O fluxo direto ainda precisa validar modelo, filtrar duplicados, respeitar
falhas do Anki MCP e registrar apenas cards aceitos.

Se houver mais de 40 cards candidatos, o modo padrao deve mostrar o preview
completo e pedir confirmacao antes de qualquer escrita.

## Validacao De Modelo Anki

Antes de chamar `mcp_anki-mcp_addNotes`/`mcp_anki-mcp_addNote`, valide que o
modelo escolhido tem os campos necessarios:

```bash
uv run python ${extensionPath}/scripts/mednotes/anki_model_validator.py validate --models-json <models.json>
```

O JSON de entrada deve representar o resultado de `modelNames` +
`modelFieldNames`, por exemplo:

```json
{
  "Medicina": ["Frente", "Verso", "Verso Extra", "Obsidian"],
  "Medicina Cloze": ["Texto", "Verso Extra", "Obsidian"]
}
```

Para validar os dois modelos juntos, use `validate-set`:

```bash
uv run python ${extensionPath}/scripts/mednotes/anki_model_validator.py validate-set --models-json <models.json>
```

Se algum dos dois modelos faltar campos obrigatórios, pare antes de gravar e
rode `flashcards/install_models.py ensure` para instalar/atualizar os modelos
faltantes.

## Sincronizacao Das Twenty Rules

Para auditar a copia local da metodologia contra o pacote Anki MCP instalado:

```bash
uv run python ${extensionPath}/scripts/mednotes/sync_anki_twenty_rules.py check
```

Use `--source <content.md>` para apontar explicitamente para o prompt upstream.
Use `write` somente quando quiser substituir a copia local pela upstream.

## Relatorio Final

Quando o fluxo tiver dados estruturados de fontes, duplicados, cards aceitos,
validacao de modelo e erros do Anki MCP, gere uma resposta final consistente com:

```bash
uv run python ${extensionPath}/scripts/mednotes/flashcard_report.py final --input <run-result.json>
```

O relatorio deve separar notas processadas, cards criados, cards pulados por
duplicidade, notas puladas, erros de modelo/campos e erros do Anki MCP.
