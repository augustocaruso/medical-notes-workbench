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

## Familias Atuais

- `medical-notes-workbench.subagent-plan.v1`
- `medical-notes-workbench.triage-note-plan.v1`
- `medical-notes-workbench.raw-coverage.v1`
- `medical-notes-workbench.taxonomy-migration-plan.v1`
- `medical-notes-workbench.taxonomy-migration-receipt.v1`
- `medical-notes-workbench.wiki-health-fix.v1`
- `medical-notes-workbench.blocker-resolution.v1`
- `medical-notes-workbench.wiki-graph-fix.v1`
- `medical-notes-workbench.wiki-graph-audit.v1`
- `medical-notes-workbench.backup-cleanup.v1`
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

Relatórios do linker podem incluir `links_rewritten` e `plans[].rewrites`.
Esses campos indicam canonicalização determinística de WikiLinks existentes com
base no catálogo; o texto visível é preservado e apenas o target muda.

## Planos De Subagents

`medical-notes-workbench.subagent-plan.v1` deve incluir
`canonical_parent_commands` com templates dos comandos seriais canônicos que o
agente principal deve usar depois que subagents retornarem. Esses templates são
contrato operacional, não alias de conveniência: slash commands devem seguir os
nomes e flags públicos documentados pela CLI.

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
