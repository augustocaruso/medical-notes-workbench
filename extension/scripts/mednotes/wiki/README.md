# Wiki Scripts

Este diretorio marca o dominio wiki dentro da extensao. A fachada publica ainda
e `../med_ops.py`, que preserva subcomandos como `fix-wiki`,
`publish-batch`, `taxonomy-migrate`, `graph-audit`, `run-linker` e
`plan-subagents`.

Entradas publicas preservadas:

- `ops.py`: delega para `../med_ops.py`.
- `tree.py`: delega para `../wiki_tree.py`.
- `../wiki_graph.py`: shim para `wiki.graph`.
- `../med_linker.py`: shim para `wiki.linker`.

Módulos internos:

- `api.py`: superfície programática legada que antes era importada de `med_ops.py`.
- `cli.py`: parser e dispatch dos subcomandos públicos.
- `config.py`: paths, variáveis de ambiente e `config.toml`.
- `raw_chats.py`: leitura/listagem/mutação de frontmatter dos chats brutos.
- `taxonomy/`: subdomínio de taxonomia com schema, normalização, resolução,
  auditoria, migração e rollback.
- `publish.py`: `stage-note`, `publish-batch` e colisões de destino.
- `style.py`: validação e correções formais de notas Wiki.
- `health.py`: orquestração do `fix-wiki`.
- `graph.py`: auditoria de grafo, WikiLinks, catálogo e aliases.
- `linker.py`: vocabulário, planejamento, aplicação e CLI do linker.
- `link_terms.py`: helpers compartilhados de aliases, catálogo e normalização.
- `linking.py`: chamada direta do linker e auditoria do grafo para `med_ops`.

`med_ops.py` deve permanecer como shim mínimo de compatibilidade.
