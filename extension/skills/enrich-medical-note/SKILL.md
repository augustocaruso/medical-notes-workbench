---
name: enrich-medical-note
description: Enriquece notas médicas em Markdown com imagens usando o módulo enricher empacotado no Medical Notes Workbench. Use quando o usuário pedir para enriquecer, ilustrar, adicionar figuras ou buscar imagens para uma ou mais notas médicas `.md`.
---

# Skill: enrich-medical-note

Resumo canônico do workflow: `docs/workflows/enrich.md`.

## Quando usar

- O usuário pede para enriquecer/ilustrar uma ou mais notas Markdown médicas.
- O usuário aponta um ou mais `.md` e quer figuras de anatomia, histologia, mecanismos,
  esquemas, radiologia ou fotos clínicas.
- O usuário quer embutir imagens no formato Obsidian `![[...]]`.

Não usar para:

- Geração de imagens novas. O projeto busca e baixa imagens externas/locais.
- Reescrever livremente o conteúdo textual da nota.

## Raiz da extensão

Use `${extensionPath}` como raiz da extensão. Se o conteúdo não tiver sido
hidratado pelo Gemini CLI, use o caminho padrão:

```bash
~/.gemini/extensions/medical-notes-workbench
```

## Pré-condições

1. Cada nota alvo é um arquivo `.md` legível.
2. `${extensionPath}/config.toml` existe e tem `[vault].path` preenchido.
3. `${extensionPath}/.venv` existe com o pacote instalado em modo editável.
4. O `gemini` CLI está autenticado, pois `scripts/enrich_notes.py` chama o Gemini
   para âncoras e rerank visual.

Se faltar ambiente Python:

```bash
cd "${extensionPath}"
# Windows
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

# macOS/Linux
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Se faltar configuração:

```bash
cd "${extensionPath}"
cp config.example.toml config.toml
```

Depois peça o caminho do vault Obsidian e preencha `[vault].path`.

## Como executar

```bash
cd "${extensionPath}"
# Windows
.\.venv\Scripts\python.exe scripts/enrich_notes.py "<caminho-da-nota.md>" --config config.toml

# macOS/Linux
.venv/bin/python scripts/enrich_notes.py "<caminho-da-nota.md>" --config config.toml
```

Para enriquecer várias notas na mesma invocação:

```bash
cd "${extensionPath}"
# Windows
.\.venv\Scripts\python.exe scripts/enrich_notes.py "<nota1.md>" "<nota2.md>" --config config.toml

# macOS/Linux
.venv/bin/python scripts/enrich_notes.py "<nota1.md>" "<nota2.md>" --config config.toml
```

Também é possível passar diretórios e globs; diretórios são expandidos
recursivamente para `.md`, com dedupe e ignorando anexos/cache:

```bash
cd "${extensionPath}"
# Windows
.\.venv\Scripts\python.exe scripts/enrich_notes.py "<pasta-de-notas>" "**\*.md" --config config.toml

# macOS/Linux
.venv/bin/python scripts/enrich_notes.py "<pasta-de-notas>" "**/*.md" --config config.toml
```

Para refazer notas já enriquecidas, aplique `--force` ao lote:

```bash
cd "${extensionPath}"
# Windows
.\.venv\Scripts\python.exe scripts/enrich_notes.py "<nota1.md>" "<nota2.md>" --config config.toml --force

# macOS/Linux
.venv/bin/python scripts/enrich_notes.py "<nota1.md>" "<nota2.md>" --config config.toml --force
```

## Como interpretar

Reporte ao usuário:

- Número de âncoras encontradas.
- Quantas imagens foram inseridas.
- Notas puladas por `images_enriched: true`.
- Notas sem inserção e falhas por nota.
- Fontes usadas (`wikimedia`, `web_search`, etc.).
- Caminhos finais das notas.
- Falhas toleradas, como downloads `403` ou thumbs indisponíveis.

## Falhas comuns

- **Vault não configurado**: peça o caminho e atualize `config.toml`.
- **Gemini CLI sem login**: peça para autenticar o Gemini CLI.
- **Sem `SERPAPI_KEY`**: `web_search` retorna `[]`; Wikimedia ainda funciona.
  Para habilitar, peça ao usuário criar conta em https://serpapi.com/, copiar a
  API key do dashboard e rodar
  `gemini extensions config medical-notes-workbench SERPAPI_KEY`.
  A chave é uma setting sensível da extensão e não precisa ser digitada a cada
  update normal.
- **Cota/limite SerpAPI esgotado**: o lote para imediatamente com `rc=9` e
  aviso claro para evitar novas chamadas à API. Oriente o usuário a renovar a
  cota/chave ou rodar novamente só com fontes disponíveis.
- **Downloads 403**: o downloader tenta headers browser-like e fallback de
  thumbnail SerpAPI quando disponível; se ainda falhar, pule a candidata.
