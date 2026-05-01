---
name: med-auto-linker
description: Linkador com Exatidão Semântica. Utiliza um catálogo gerado por IA com sinônimos médicos estritos para evitar falsos positivos e links genéricos.
---

# Semantic Linker Contract

Este contrato orienta a linkagem semântica da `Wiki_Medicina`. Em vez de
quebrar palavras ou usar regex cegas, o workflow depende de um catálogo de
entidades médicas (`CATALOGO_WIKI.json`) onde cada arquivo possui sinônimos e
siglas clínicas estritas.

## Capacidades de Alta Precisão
- **Filtro Anti-Stopwords:** Palavras como "Diagnóstico", "Tratamento", "Agudo", "Paciente" jamais serão linkadas, pois não fazem parte das entidades mapeadas no catálogo.
- **Longest-Match First:** Se o texto tiver "Doença Celíaca", a skill linka para a nota de doença celíaca e não apenas a palavra "Doença".
- **Siglas Precisas:** Linka automaticamente termos como "SDR", "PECARN", "IAM" sem erros de limite de palavra.

## Como Usar Na Extensão

### 1. Criar/Atualizar o Catálogo (Pré-requisito)
Use o catálogo configurado por `--catalog`/`MED_CATALOG_PATH`; quando não houver
override, a convenção operacional é
`~/.gemini/medical-notes-workbench/CATALOGO_WIKI.json`. Se novas notas forem
publicadas, atualize ou proponha entradas com sinônimos médicos estritos antes
de aplicar linkagem em lote.

### 2. Linkagem em Lote (Vault Inteiro)
Rode dry-run auditável primeiro:

```bash
python scripts/mednotes/med_linker.py --dry-run --json
```

Depois aplique sem `--dry-run` somente se o plano estiver coerente e sem
blockers de grafo.

### 3. Linkagem Direcionada (Nota Única)
Para linkar uma nota específica:

```bash
python scripts/mednotes/med_linker.py "<caminho_da_nota>" --dry-run --json
```

## Regras de Ouro
- Nunca confie em scripts de regex simples para extrair sinônimos. Use seu próprio conhecimento médico (como IA) para mapear os termos exatos de cada nota no JSON.
- Apenas a primeira ocorrência do termo na nota é linkada para não poluir visualmente o arquivo.

## Implementação

O script empacotado em `scripts/mednotes/med_linker.py` deve usar
`CATALOGO_WIKI.json` como fonte primária de vocabulário. Nomes de arquivo e
aliases YAML são apenas fallback quando o catálogo não existe ou está
incompleto. A auditoria objetiva do grafo vive em
`scripts/mednotes/wiki_graph.py` e verifica links quebrados, self-links,
aliases conflitantes, targets ausentes e notas órfãs.

Quando precisar apontar outro vault/catálogo:

```bash
python scripts/mednotes/med_linker.py --wiki-dir "<Wiki_Medicina>" --catalog "<CATALOGO_WIKI.json>" --dry-run --json
```

Para auditoria pura, use `med_ops.py graph-audit --json`,
`wiki_graph.py --json` ou `med_linker.py --audit --json`.
