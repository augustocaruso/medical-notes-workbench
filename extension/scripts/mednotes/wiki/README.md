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

Ao extrair codigo de `med_ops.py`, mover primeiro para modulos deste dominio e
manter `med_ops.py` como CLI fina.
