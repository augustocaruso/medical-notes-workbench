# Workflow Output Contract

Use este contrato em todos os workflows públicos da extensão.

## Princípio

- CLIs operacionais podem emitir JSON parseável na stdout; esse JSON é contrato
  para o agente, hooks e testes.
- A resposta visível ao usuário no Gemini CLI deve ser um resumo curto em
  português, não um dump bruto do JSON, salvo se o usuário pedir o JSON.
- Mensagens devem ser acionáveis: dizer o que aconteceu, o que não aconteceu,
  onde olhar e qual é a próxima decisão.

## Formato Da Resposta Ao Usuário

Ao terminar um workflow, responda com:

1. **Status com emoji**: use um marcador curto e consistente, por exemplo
   `✅` aplicado/concluído, `👀` preview, `⚠️` warnings, `⛔` bloqueado/falhou,
   `🧭` próxima ação.
2. **Contagens principais**: itens vistos, itens alterados/criados/planejados,
   falhas e pulos.
3. **Arquivos relevantes**: liste poucos caminhos importantes; se houver muitos,
   mostre exemplos e a contagem total.
4. **Blockers e warnings**: taxonomia, grafo, estilo, Anki, Gemini, cota/API ou
   download.
5. **Próxima ação**: confirmação necessária, comando seguro seguinte ou decisão
   que o usuário precisa tomar.

Quando a próxima ação for um lote parcial, deixe a fase explícita e limitada
(`triagem`, `arquitetura`, `publish dry-run`, etc.). Se o usuário confirmar uma
próxima ação limitada, o turno seguinte deve executar somente essa fase e parar
com novo resumo; confirmação de triagem não autoriza avançar para arquitetura ou
publicação.

Use emojis para escaneabilidade, não para decorar cada frase. Evite mais de um
emoji por bullet.

## Campos Por Workflow

- `enrich`: notas processadas, âncoras, imagens inseridas, fontes, puladas por
  `images_enriched`, sem inserção, falhas por nota.
- `create`: tema, destino quando salvo, se houve sobrescrita evitada,
  pontos visuais sugeridos e próximo workflow recomendado.
- `fix-wiki`: `file_count`, `changed_count`, `written_count`, `error_count`,
  `write_error_count`, `taxonomy_action_required`,
  `requires_llm_rewrite_count`, grafo/linker, backups e exemplos de notas
  afetadas. Se houver `write_errors`, destaque que a escrita ficou bloqueada e
  que o linker real foi pulado.
- `process-chats`: pendentes/triados, work items, notas staged/publicadas,
  chats marcados como processados, dry-run/publish, linker e canonizações de
  taxonomia.
- `link`: links planejados/inseridos, arquivos alterados, blockers de grafo,
  catálogo usado e avisos.
- `flashcards`: fontes resolvidas, notas puladas, cards candidatos, novos,
  duplicados, bloqueios de modelo/Anki, cards criados e notas marcadas com
  `anki`.

## Preview-First

Quando o workflow for preview-first, deixe explícito se nada foi escrito.
Se o usuário ainda precisa confirmar escrita, termine com a decisão concreta
esperada, por exemplo: aplicar com backup, migrar taxonomia, gravar no Anki ou
descartar o plano.
