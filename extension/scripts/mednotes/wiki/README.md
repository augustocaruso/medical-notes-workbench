# Wiki Scripts

Este diretorio marca o dominio wiki dentro da extensao. A CLI publica
preservada e `../med_ops.py`, que preserva subcomandos como `fix-wiki`,
`publish-batch`, `taxonomy-migrate`, `graph-audit`, `run-linker` e
`plan-subagents`.

Entradas publicas preservadas:

- `../wiki_graph.py`: alias publico de CLI para `wiki.graph`.
- `../med_linker.py`: alias publico de CLI para `wiki.linker`.

Módulos internos:

- `api.py`: superfície programática explícita para imports Python.
- `cli.py`: parser e dispatch dos subcomandos públicos.
- `config.py`: paths, variáveis de ambiente e `config.toml`.
- `raw_chats.py`: leitura/listagem/mutação de frontmatter dos chats brutos.
- `note_plan.py`: contrato exaustivo de notas criado pela triagem.
- `coverage.py`: inventário exaustivo de temas por raw chat antes do publish.
- `taxonomy/`: subdomínio de taxonomia com schema, normalização, resolução,
  auditoria, migração e rollback.
- `publish.py`: `stage-note`, `publish-batch` e colisões de destino.
- `style.py`: validação e correções formais de notas Wiki.
- `note_style/`: contrato de estilo das notas, com frontmatter, validação,
  fixes determinísticos, tabelas e prompt de reescrita controlada.
- `health.py`: orquestração do `fix-wiki`.
- `graph.py`: auditoria de grafo, WikiLinks, catálogo e aliases.
- `graph_fixes.py`: correções determinísticas de grafo antes do linker
  (`dangling_link`, `self_link`, links ambíguos e duplicatas exatas).
- `linker.py`: vocabulário, planejamento, aplicação e CLI do linker.
- `link_terms.py`: helpers compartilhados de aliases, catálogo e normalização.
- `linking.py`: chamada direta do linker e auditoria do grafo para `med_ops`.

`med_ops.py` deve permanecer como alias público de CLI; imports Python devem
usar `wiki.api` ou os módulos `wiki.*`.
