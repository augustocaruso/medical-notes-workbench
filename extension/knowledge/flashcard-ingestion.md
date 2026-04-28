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

2. Tags: nao adicionar tags por enquanto. Omita o campo `tags` ou envie lista
   vazia quando a ferramenta exigir esse campo.

3. Formatacao do campo: antes de inserir conteudo no campo `Verso Extra`, adicione
   um espaco visual no inicio do campo. Use uma quebra de linha em texto puro
   (`\n\n`) ou `<br><br>` quando o conteudo for HTML.

## Regra De Base De Conhecimento

`/twenty_rules` sem namespace e reservado para o prompt MCP `twenty_rules` do
servidor `anki`. O wrapper da extensao para um arquivo local e
`/mednotes:twenty_rules <path>` para evitar colisao com o prompt MCP.

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
