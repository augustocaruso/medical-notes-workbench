# Roadmap Do Modulo `/flashcards`

## Objetivo

Consolidar o modulo de flashcards da extensao Medical Notes Workbench em tres
camadas: confiabilidade, ergonomia e ciclo de estudo. O comando publico segue
sendo apenas `/flashcards`; melhorias de setup, reprocessamento ou auditoria
devem entrar como argumentos/fluxos desse comando ou como scripts deterministas
chamados por ele.

Este roadmap preserva o plano original inteiro e registra o estado final da
implementacao local.

## Estado atual

- O comando `/flashcards` usa o subagent `med-flashcard-maker` e o MCP global
  existente `anki-mcp`; a extensao nao declara outro Anki MCP.
- A metodologia Twenty Rules esta vendorada em
  `extension/knowledge/anki-mcp-twenty-rules.md`, com proveniencia no prompt MCP
  `/twenty_rules` do pacote `@ankimcp/anki-mcp-server`.
- `extension/scripts/mednotes/flashcard_sources.py resolve` ja resolve arquivos,
  diretorios, globs, filtros por tag Obsidian e pastas em linguagem natural para
  um manifest JSON com `deck`, `deeplink`, tags e hash da nota.
- `extension/scripts/mednotes/flashcard_sources.py preview` ja gera uma previa
  textual humana usando a mesma resolucao de escopo.
- `--skip-tag anki` evita recriar cards de notas marcadas com a tag Obsidian
  `anki`, mas isso e apenas uma protecao simples. A idempotencia real agora e
  feita pelo indice local e por hashes.
- `extension/scripts/mednotes/flashcard_index.py` ja fornece o indice local
  `FLASHCARDS_INDEX.json` para filtrar e registrar cards aceitos.
- `extension/scripts/mednotes/anki_model_validator.py` ja valida, de forma
  testavel, se um note type capturado do Anki MCP tem os campos obrigatorios.
- `extension/scripts/mednotes/sync_anki_twenty_rules.py` ja compara a copia
  local das Twenty Rules com uma fonte upstream instalada/apontada.
- `extension/scripts/mednotes/flashcard_report.py` ja gera preview deterministico
  dos cards antes da escrita e resumo final a partir dos dados estruturados de
  execucao.
- `extension/scripts/mednotes/flashcard_pipeline.py` ja cobre o fluxo
  deterministico prepare/apply em torno do Anki MCP.

## Prioridade Alta

1. **Resolver escopo com script Python** — **feito**

   Implementado como:

   ```bash
   uv run python extension/scripts/mednotes/flashcard_sources.py resolve ...
   ```

   O script devolve JSON com arquivos finais, tags encontradas, vault root
   quando inferivel, deck destino e deeplink pelo path real da nota. Filtros
   extras, como exclusao de pastas ou modo sem subpastas, ficam como
   refinamentos futuros fora do escopo original.

2. **Dry-run/preview real antes de criar** — **feito**

   Ja existem:

   ```bash
   uv run python extension/scripts/mednotes/flashcard_sources.py resolve ... --dry-run
   uv run python extension/scripts/mednotes/flashcard_sources.py preview ... --dry-run
   ```

   O manifest de fontes ja existe. O contrato de `candidate_cards` tambem foi
   definido para a etapa posterior a formulacao:

   ```json
   {
     "source": "nota.md",
     "deck": "Wiki_Medicina::Cardiologia::Ponte_Miocardica",
     "deeplink": "obsidian://open?path=...",
     "preferred_model": "Medicina",
     "models": {"Medicina": ["Frente", "Verso", "Verso Extra", "Obsidian"]},
     "candidate_cards": []
   }
   ```

   Esse manifest e produzido pelo agente depois da aplicacao das Twenty Rules e
   antes de chamar o Anki MCP. O script `flashcard_pipeline.py prepare` valida e
   transforma esse manifest em plano de escrita testavel antes de qualquer
   gravacao no Anki. Por padrao, o agente mostra esse plano no terminal com
   `flashcard_report.py preview-cards` e so grava depois de confirmacao.

3. **Idempotencia** — **feito**

   Evitar cards duplicados por hash de nota, trecho e card em um indice local:

   ```text
   ~/.gemini/medical-notes-workbench/FLASHCARDS_INDEX.json
   ```

   Implementado como:

   ```bash
   uv run python extension/scripts/mednotes/flashcard_index.py check --candidates candidate_cards.json
   uv run python extension/scripts/mednotes/flashcard_index.py record --accepted accepted_cards.json
   ```

   Esse indice e preferido a poluir o frontmatter da nota. A tag Obsidian `anki`
   continua util como marcador visual e filtro simples, mas nao substitui a
   idempotencia por hash. O fluxo esta coberto por teste end-to-end com Anki MCP
   mockado.

4. **Validador de modelo Anki** — **feito**

   Antes de criar cards, validar que existe um note type compativel com os
   campos necessarios:

   - `Frente`
   - `Verso`
   - `Verso Extra`
   - `Obsidian`

   Implementado como:

   ```bash
   uv run python extension/scripts/mednotes/anki_model_validator.py validate --models-json models.json
   ```

   Se faltar campo/modelo, parar antes de gravar e mostrar mensagem clara. Um
   fluxo futuro de setup pode existir como argumento de `/flashcards`, por
   exemplo `/flashcards setup`, sem criar novo comando publico.

## Prioridade Media

5. **Script para atualizar a copia das Twenty Rules** — **feito**

   Implementado como:

   ```bash
   uv run python extension/scripts/mednotes/sync_anki_twenty_rules.py check
   ```

   O script compara a copia local com o pacote instalado
   `@ankimcp/anki-mcp-server` ou com `--source <content.md>` e mostra diff. O
   objetivo e evitar que a proveniencia fique congelada sem perceber.

6. **Testes com Anki MCP mockado** — **feito**

   Testar o contrato de criacao sem depender do Anki real, cobrindo chamadas
   equivalentes a:

   - `modelFieldNames`
   - `addNotes`
   - `findNotes`

   Existem testes puros para campos obrigatorios e duplicidade local, alem de
   teste end-to-end com MCP mockado cobrindo `modelFieldNames`, `findNotes`,
   `addNotes`, registro no indice e relatorio final. O plano `prepare` gera
   `anki_find_queries`; o subagent usa essas queries antes de gravar para pular
   duplicados que ja existam no Anki.

7. **Reprocessamento de notas alteradas** — **feito**

   Se uma nota marcada com `anki` mudou bastante, detectar hash diferente e
   sugerir uma escolha:

   - criar cards novos;
   - ignorar;
   - futuramente atualizar cards antigos.

   `flashcard_index.py source-status` e `flashcard_pipeline.py prepare` detectam
   diferenca de `source_content_sha256` e sinalizam
   `requires_reprocess_confirmation` antes de criar novos cards. Atualizacao de
   cards antigos continua fora do escopo atual; a primeira versao cobre detectar
   e pedir confirmacao para novos cards.

## Prioridade Baixa

8. **Relatorio final melhor** — **feito**

   Implementado como:

   ```bash
   uv run python extension/scripts/mednotes/flashcard_report.py final --input run-result.json
   ```

   Depois de `/flashcards`, o resumo cobre o formato:

   ```text
   3 notas processadas
   27 cards criados
   2 cards pulados por duplicidade
   1 nota sem campo Obsidian no modelo Anki
   ```

   O relatorio separa sucesso, duplicidade, falhas de modelo/campo e notas que
   foram puladas por ja terem tag `anki`; `flashcard_pipeline.py apply` alimenta
   esse relatorio no fluxo consolidado. O mesmo script tambem fornece
   `preview-cards` para o comportamento padrao de revisar no terminal antes de
   criar no Anki.

9. **CI no GitHub** — **feito**

   Implementado em `.github/workflows/ci.yml` com:

   ```bash
   uv run python -m pytest
   npm run build:gemini-cli-extension
   gemini extensions validate dist/gemini-cli-extension
   ```

   Isso reduz o risco de publicar uma extensao quebrada.

## Decisoes ja tomadas

- Manter um unico comando publico: `/flashcards`.
- Nao recriar `/twenty_rules` como comando da extensao; ele pertence ao Anki
  MCP. A extensao usa copia local vendorada para autonomia do subagent.
- Usar `anki-mcp` global ja configurado pelo usuario, sem declarar outro MCP no
  manifest da extensao.
- Gerar deeplinks Obsidian a partir do path real da nota no formato
  `obsidian://open?path=...`, sem depender de inferencia de vault.
- Marcar notas processadas com a tag Obsidian `anki` somente depois de sucesso
  real no Anki.
- Usar `--skip-tag anki` como protecao simples contra duplicacao acidental,
  mantendo claro que a idempotencia real depende do indice local
  `FLASHCARDS_INDEX.json`.
- Preview-first e o padrao: `/flashcards` mostra os cards no terminal e so
  grava depois de confirmacao. Criacao direta exige pedido explicito como
  `--create`, `--direct`, `--yes`, `--no-preview`, "criar diretamente" ou
  equivalente.

## Proximo passo recomendado

Rodar um smoke test manual com Anki Desktop real.

O roadmap de implementacao local esta completo. O proximo passo operacional e
executar `/flashcards` com uma nota pequena em um ambiente com Anki Desktop e
AnkiConnect reais para validar o comportamento fora do mock.
