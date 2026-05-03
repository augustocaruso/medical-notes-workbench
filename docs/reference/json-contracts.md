# JSON Contracts

Todos os utilitarios operacionais emitem JSON parseavel na stdout em sucesso.
Mensagens humanas e erros ficam em stderr com exit code diferente de zero.
No Gemini CLI, a resposta final ao usuario segue
`extension/knowledge/workflow-output-contract.md`: o agente transforma JSON em
resumo curto, acionavel e com emoji de status. JSON bruto so deve aparecer
quando solicitado.

## Principios

- Incluir `schema` em contratos compostos e manifests.
- Incluir caminhos resolvidos quando uma operacao puder escrever arquivos.
- Preferir listas vazias a falhas para ausencia normal de resultados.
- Usar erro fatal para cota paga esgotada ou operacao que poderia repetir custo.
- Em workflows publicos, expor campos operacionais estaveis quando fizer sentido:
  `status`, `phase`, `blocked_reason`, `next_action`, `required_inputs` e
  `human_decision_required`.

## Matriz De Invariantes Operacionais

- `process-chats`: antes de mutar, exigir `note_plan` exaustivo, inventario
  `coverage_path` compativel, targets unicos por normalizacao de acento/caixa e
  manifests HTML validos quando houver artefatos Gemini.
- `publish-batch`: publish real so vale com recibo recente de
  `publish-batch --dry-run` para o mesmo manifest/cwd/caminhos/opcoes.
- `fix-wiki`: o comando deve aplicar rotas deterministicas antes de encerrar e
  bloquear o linker real quando houver `write_errors`, `requires_llm_rewrite`,
  blockers de grafo ou decisao humana pendente.
- `link`: roda apenas grafo/linker/indice; nao corrige estilo, YAML,
  publicacao ou taxonomia.
- Mudanca observavel em workflow publico deve declarar fase alterada,
  pre-condicoes novas, JSON afetado e teste de regressao correspondente.

## Familias Atuais

- `medical-notes-workbench.subagent-plan.v1`
- `medical-notes-workbench.triage-note-plan.v1`
- `medical-notes-workbench.raw-coverage.v1`
- `gemini-md-export.artifact-html-manifest.v1`
- `medical-notes-workbench.artifact-html-validation.v1`
- `medical-notes-workbench.taxonomy-migration-plan.v1`
- `medical-notes-workbench.taxonomy-migration-receipt.v1`
- `medical-notes-workbench.wiki-health-fix.v1`
- `medical-notes-workbench.blocker-resolution.v1`
- `medical-notes-workbench.wiki-graph-fix.v1`
- `medical-notes-workbench.wiki-graph-audit.v1`
- `medical-notes-workbench.backup-cleanup.v1`
- `medical-notes-workbench.wiki-hygiene.v1`
- `medical-notes-workbench.wiki-hygiene-cleanup.v1`
- `medical-notes-workbench.fix-wiki-run-state.v1`
- `medical-notes-workbench.flashcard-sources.v1`
- `medical-notes-workbench.flashcard-write-plan.v1`
- `medical-notes-workbench.flashcard-report.v1`
- `medical-notes-workbench.flashcard-card-preview.v1`

Novos contratos devem seguir a mesma familia e ser cobertos por teste antes de
entrar em um workflow publico.

## Campos De Escrita Bloqueada

Workflows que aplicam reparos em notas podem retornar `write_error_count` e
`write_errors` no JSON. Esses campos indicam que a auditoria terminou, mas uma
ou mais escritas falharam mesmo após retry local, normalmente por lock de
Obsidian, iCloud Drive, antivírus ou outro processo. Em `fix-wiki`, qualquer
erro desse tipo pula o linker real com `linker_skipped_reason: write_errors` e
retorna código de IO.

## Fix-Wiki Orquestrado

`medical-notes-workbench.wiki-health-fix.v1` é o contrato do `fix-wiki`.
Além dos relatórios detalhados de estilo, grafo, linker e taxonomia, ele deve
expor campos operacionais estáveis para agentes:

- `status`: `completed`, `completed_with_warnings`, `blocked` ou `failed`;
- `summary`: frase curta sobre o resultado;
- `next_command`, `resume_command` e `rollback_command`;
- `human_decision_required` e `human_decisions`;
- `hygiene_before`, `hygiene_pre_cleanup`, `hygiene_cleanup` e
  `hygiene_after`;
- `final_validation.graph`, `final_validation.hygiene` e
  `final_validation.taxonomy`;
- `compact_report_path`, `full_report_path` e `run_state_path`.

Movimentos determinísticos de taxonomia são planejados e aplicados pelo próprio
`fix-wiki --apply --backup --json` usando o mesmo mecanismo de
`taxonomy-migrate`, com recibo e `rollback_command`. Backups `.bak` e arquivos
`.rewrite` não devem permanecer dentro do vault; eles são arquivados fora da
Wiki em `~/.gemini/backup_archive/fix-wiki/<data>/<run_id>/`.

## Resolução De Blockers

`medical-notes-workbench.blocker-resolution.v1` aparece dentro de
`fix-wiki` como `blocker_resolution`. Ele transforma blockers em rotas
acionáveis, em vez de deixar o workflow parar no `linker_skipped_reason`.
Rotas determinísticas ou orquestráveis incluem `graph_fix_retry`,
`catalog_repair`, `style_rewrite` e `taxonomy_migrate`; rotas que exigem
intervenção externa ou decisão humana incluem `io_retry`,
`duplicate_merge_required` e `unknown_graph_blocker`.

Enquanto `blocker_resolution.linker_can_apply` for falso, `fix-wiki --apply`
não aplica o linker real. O campo `linker_skipped_reason` deve apontar a causa
operacional, por exemplo `write_errors`, `requires_llm_rewrite`,
`graph_blockers` ou `taxonomy_action_required`.

Quando `human_decision_required=true`, `human_decisions` deve carregar não só a
decisão pendente, mas a pergunta ao humano e o caminho de continuação:
`prompt`, `options`, `next_action` e `continue_after_choice`. O agente não deve
tratar isso como encerramento; deve coletar a escolha humana e seguir pela rota
segura indicada.

Relatórios do linker podem incluir `links_rewritten` e `plans[].rewrites`.
Esses campos indicam canonicalização determinística de WikiLinks existentes com
base no catálogo; o texto visível é preservado e apenas o target muda.

## Planos De Subagents

`medical-notes-workbench.subagent-plan.v1` deve incluir
`canonical_parent_commands` com templates dos comandos seriais canônicos que o
agente principal deve usar depois que subagents retornarem. Esses templates são
contrato operacional, não alias de conveniência: slash commands devem seguir os
nomes e flags públicos documentados pela CLI. O payload tambem deve expor
`phase`, `status`, `blocked_reason`, `next_action`, `required_inputs` e
`human_decision_required` para deixar claro se o lote esta pronto, parcialmente
bloqueado ou totalmente bloqueado antes do spawn.

## Cobertura De Raw Chats

`medical-notes-workbench.triage-note-plan.v1` é o plano exaustivo criado pelo
`med-chat-triager` e gravado no frontmatter do raw chat como `note_plan`.
Campos mínimos: `schema`, `raw_file`, `exhaustive: true` e `items`. Cada item
tem `id`, `title` e `action`: `create_note`, `covered_by_existing` ou
`not_a_note`. Itens `create_note` definem as notas que o architect deve criar;
itens dispensados precisam de `reason`, e `covered_by_existing` também precisa
de `existing_title`.

`medical-notes-workbench.raw-coverage.v1` é o inventário exaustivo criado pelo
`med-knowledge-architect` antes de staged notes, derivado do `note_plan` da
triagem. Campos mínimos: `schema`, `raw_file`, `exhaustive: true` e `items`.
Itens `create_note` devem bater com o `note_plan` e com os títulos staged.
`stage-note` e `publish-batch` devem refletir essa exigência em
`required_inputs` e falhar antes de escrita/publicação quando a cobertura estiver
ausente, divergente ou incompleta.

## Artefatos HTML Do Gemini

`gemini-md-export.artifact-html-manifest.v1` é produzido pelo
`gemini-md-export` quando um chat possui artefatos interativos exportados como
HTML isolado. O workbench trata `savedCount > 0` como insumo obrigatório:
`plan-subagents --phase architect`, `validate-note`, `stage-note` e
`publish-batch` descobrem manifests `artifact-<chatId>-manifest.json` pelo
`fonte_id` do raw chat. A busca usa `artifact_dir` quando configurado e também
locais próximos do raw chat.

O grupo de notas staged derivado de um raw chat com artefatos precisa incluir,
no conjunto, cada arquivo `.html` listado no manifesto. A nota que carregar um
artefato deve incluir:

- um `<iframe src="file:///...">` apontando para o arquivo HTML isolado;
- um link Markdown auditável para o mesmo `file:///...`;
- um comentário `gemini-artifact` com `chat_id`, caminho do `manifest`, caminho
  do `file` e `sha256`.

O Markdown nunca deve inlinear o HTML capturado. Se o arquivo faltar, não for
`.html`, tiver hash diferente, ou o grupo de notas staged não declarar todos os
artefatos, o workflow bloqueia antes de considerar o raw chat pronto.

`medical-notes-workbench.artifact-html-validation.v1` aparece no JSON de
`validate-note`, `stage-note` e no plano de `publish-batch --dry-run` para
resumir `required`, contagem de manifests e arquivos, caminhos usados e hashes.
Em `validate-note`/`stage-note`, ausência de um artefato na nota individual é
informativa; o bloqueio de cobertura completa acontece no batch do
`publish-batch`.
