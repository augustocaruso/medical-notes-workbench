---
name: med-auto-linker
description: Linkador com Exatidão Semântica. Utiliza um catálogo gerado por IA com sinônimos médicos estritos para evitar falsos positivos e links genéricos.
---

# Med AI Linker (O Tecelão Semântico)

Esta skill resolve o problema de links genéricos e ambíguos na Wiki. Em vez de quebrar palavras ou usar regex cegas, ela depende de um **Catálogo de Entidades Médicas** (`CATALOGO_WIKI.json`) onde cada arquivo possui uma lista de sinônimos e siglas mapeadas pela Inteligência Artificial.

## Capacidades de Alta Precisão
- **Filtro Anti-Stopwords:** Palavras como "Diagnóstico", "Tratamento", "Agudo", "Paciente" jamais serão linkadas, pois não fazem parte das entidades mapeadas no catálogo.
- **Longest-Match First:** Se o texto tiver "Doença Celíaca", a skill linka para a nota de doença celíaca e não apenas a palavra "Doença".
- **Siglas Precisas:** Linka automaticamente termos como "SDR", "PECARN", "IAM" sem erros de limite de palavra.

## Como Usar

### 1. Criar/Atualizar o Catálogo (Pré-requisito)
O catálogo `C:\Users\leona\CATALOGO_WIKI.json` já foi gerado pela IA com a taxonomia exata e os sinônimos clínicos. **Se adicionar novas notas**, você como IA deverá atualizar este arquivo JSON com as novas entidades antes de rodar o linker.

### 2. Linkagem em Lote (Vault Inteiro)
Para processar todas as notas da Wiki e criar a teia:
`run_shell_command("python C:\Users\leona\.gemini\skills\med-auto-linker\med_linker.py")`

### 3. Linkagem Direcionada (Nota Única)
Para linkar uma nota recém-criada:
`run_shell_command("python C:\Users\leona\.gemini\skills\med-auto-linker\med_linker.py \"<caminho_da_nota>\"")`

## Regras de Ouro
- Nunca confie em scripts de regex simples para extrair sinônimos. Use seu próprio conhecimento médico (como IA) para mapear os termos exatos de cada nota no JSON.
- Apenas a primeira ocorrência do termo na nota é linkada para não poluir visualmente o arquivo.

## Adaptação na extensão

O script empacotado em `scripts/mednotes/med_linker.py` deve usar
`CATALOGO_WIKI.json` como fonte primária de vocabulário. Nomes de arquivo e
aliases YAML são apenas fallback quando o catálogo não existe ou está
incompleto.

Antes de aplicar links em lote, rode dry-run auditável:

```bash
python scripts/mednotes/med_linker.py --wiki-dir "<Wiki_Medicina>" --catalog "<CATALOGO_WIKI.json>" --dry-run --json
```

Depois aplique sem `--dry-run` se o plano estiver coerente.
