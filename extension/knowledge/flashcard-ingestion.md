# Flashcard Ingestion Design

Este documento e a fonte unica das regras locais de ingestao para criacao de
flashcards medicos no Anki. O prompt MCP `/twenty_rules`, fornecido pelo
servidor Anki MCP, continua sendo a metodologia de formulacao dos cards. Este
documento define as decisoes de design da extensao Medical Notes Workbench.

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
   ferramenta. Se `mcp_anki_createDeck` recusar mais de dois niveis, tente criar
   os cards diretamente no deck completo com `mcp_anki_addNotes`/
   `mcp_anki_addNote`; se o MCP/Anki ainda recusar, reporte a falha sem trocar
   o deck por outro.

2. Tags Anki: nao adicionar tags por enquanto. Omita o campo `tags` ou envie
   lista vazia quando a ferramenta exigir esse campo. Tags Obsidian podem ser
   usadas para selecionar notas, mas nao devem virar tags Anki.

3. Formatacao do campo: antes de inserir conteudo no campo `Verso Extra`, adicione
   um espaco visual no inicio do campo. Use uma quebra de linha em texto puro
   (`\n\n`) ou `<br><br>` quando o conteudo for HTML.

4. Campo de origem: todo card criado a partir de uma nota Markdown precisa
   preencher um campo Anki chamado `Obsidian` com o deeplink da nota-fonte.
   Gere o deeplink portavel com o script deterministico:

   ```bash
   python ${extensionPath}/scripts/mednotes/obsidian_note_utils.py deeplink <nota.md>
   ```

   O formato canonico e
   `obsidian://open?vault=<vault-name>&file=<vault-relative-note-path>`. Esse
   formato usa o nome do vault e o caminho da nota relativo a raiz do vault, por
   isso funciona em Windows e iPhone quando ambos tem o mesmo vault aberto pelo
   mesmo nome, mesmo que o iCloud use paths locais diferentes. Nao use o ID do
   vault para esse fluxo, porque o ID pode variar por instalacao. Nao dependa da
   Obsidian CLI para extrair esse link; a CLI pode abrir/inspecionar notas, mas
   o deeplink deve ser calculado do path relativo ao vault.

   O script infere a raiz do vault por `--vault-root`, `MED_WIKI_DIR`, um
   diretorio `.obsidian` ancestral ou a pasta `Wiki_Medicina`. Se a inferencia
   falhar, pergunte a raiz/nome do vault antes de criar cards. Use
   `--absolute-path` apenas como fallback local, nunca como padrao para cards
   que precisam abrir no Windows e no iPhone.

5. Marcacao da nota-fonte: depois que pelo menos um card de uma nota for criado
   com sucesso no Anki, marque apenas essa nota com a tag Obsidian `anki` no
   frontmatter usando:

   ```bash
   python ${extensionPath}/scripts/mednotes/obsidian_note_utils.py add-tag --tag anki <nota.md>
   ```

   Para desfazer a marcacao, use:

   ```bash
   python ${extensionPath}/scripts/mednotes/obsidian_note_utils.py remove-tag --tag anki <nota.md>
   ```

   Nao marque notas sem cards criados. Em sucesso parcial, marque somente os
   arquivos que tiveram pelo menos um card aceito pelo Anki MCP.

## Regra De Base De Conhecimento

`/twenty_rules` sem namespace e reservado para o prompt MCP `twenty_rules` do
servidor `anki`. O wrapper da extensao para um arquivo local e
`/mednotes:twenty_rules <path>` para evitar colisao com o prompt MCP.
Referencia de origem do prompt no pacote MCP:
`@ankimcp/anki-mcp-server/dist/mcp/primitives/essential/prompts/twenty-rules.prompt/content.md`.
Esse path e rastreabilidade/proveniencia; o agente deve carregar a metodologia
por `/twenty_rules`, nao por `read_file` nesse path.
O comando top-level `/flashcards` aceita escopos mais amplos: arquivos,
diretorios, globs, filtros por tag Obsidian e instrucoes em linguagem natural.
Tags Obsidian podem selecionar notas, mas nao devem virar tags Anki. A tag
Obsidian `anki` e reservada para marcar notas que ja geraram cards com sucesso.

Ao receber `/mednotes:twenty_rules <path>` ou uma tarefa equivalente que ja
tenha carregado o prompt MCP `/twenty_rules`, o agente deve:

1. Usar `read_file` para extrair o conteudo do arquivo em `<path>`.
2. Utilizar exclusivamente o conteudo lido desse arquivo como base de
   conhecimento, isto e, o "O QUE" dos flashcards.
3. Aplicar rigorosamente o prompt MCP `/twenty_rules` e as especificacoes deste
   documento como "COMO".

Nao use conhecimento externo para acrescentar fatos aos cards. Conhecimento
medico geral pode ser usado apenas para entender, segmentar e redigir melhor o
conteudo que ja esta presente no arquivo.

## Resolucao De Escopo Para `/flashcards`

1. Arquivos explicitos: leia somente os arquivos indicados.
2. Diretorios/globs: inclua apenas arquivos Markdown (`.md`) dentro do escopo.
   Ignore `dist/`, `.git/`, caches, anexos, imagens e arquivos nao Markdown.
3. Tags Obsidian: filtre por frontmatter `tags`/`tag` e hashtags inline. A tag e
   apenas criterio de selecao, exceto pela marcacao pos-sucesso `anki` descrita
   acima.
4. Escopo ambiguo: se a pasta raiz nao estiver clara, use configuracao de wiki
   quando disponivel; caso contrario, pergunte antes de vasculhar.
5. Lotes grandes: para mais de 10 arquivos ou mais de 40 cards candidatos,
   mostre previa e peça confirmacao antes de gravar no Anki.
