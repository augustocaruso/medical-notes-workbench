# Wiki Scripts

Este diretorio marca o dominio wiki dentro da extensao. A fachada publica ainda
e `../med_ops.py`, que preserva subcomandos como `fix-wiki`,
`publish-batch`, `taxonomy-migrate`, `graph-audit`, `run-linker` e
`plan-subagents`.

Wrappers disponíveis:

- `ops.py`: delega para `../med_ops.py`.
- `tree.py`: delega para `../wiki_tree.py`.
- `graph.py`: delega para `../wiki_graph.py`.
- `linker.py`: delega para `../med_linker.py`.

Módulos internos:

- `api.py`: superfície programática legada que antes era importada de `med_ops.py`.
- `cli.py`: parser e dispatch dos subcomandos públicos.
- `config.py`: paths, variáveis de ambiente e `config.toml`.
- `raw_chats.py`: leitura/listagem/mutação de frontmatter dos chats brutos.
- `taxonomy.py`: taxonomia canônica, resolução, auditoria, migração e rollback.
- `publish.py`: `stage-note`, `publish-batch` e colisões de destino.
- `style.py`: validação e correções formais de notas Wiki.
- `health.py`: orquestração do `fix-wiki`.
- `linking.py`: chamada controlada do linker e auditoria do grafo.

`med_ops.py` deve permanecer como shim mínimo de compatibilidade.
