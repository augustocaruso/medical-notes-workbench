# JSON Contracts

Todos os utilitarios operacionais emitem JSON parseavel na stdout em sucesso.
Mensagens humanas e erros ficam em stderr com exit code diferente de zero.

## Principios

- Incluir `schema` em contratos compostos e manifests.
- Incluir caminhos resolvidos quando uma operacao puder escrever arquivos.
- Preferir listas vazias a falhas para ausencia normal de resultados.
- Usar erro fatal para cota paga esgotada ou operacao que poderia repetir custo.

## Familias Atuais

- `medical-notes-workbench.subagent-plan.v1`
- `medical-notes-workbench.taxonomy-migration-plan.v1`
- `medical-notes-workbench.taxonomy-migration-receipt.v1`
- `medical-notes-workbench.wiki-health-fix.v1`
- `medical-notes-workbench.wiki-graph-audit.v1`
- `medical-notes-workbench.flashcard-sources.v1`
- `medical-notes-workbench.flashcard-write-plan.v1`
- `medical-notes-workbench.flashcard-report.v1`
- `medical-notes-workbench.flashcard-card-preview.v1`

Novos contratos devem seguir a mesma familia e ser cobertos por teste antes de
entrar em um workflow publico.

