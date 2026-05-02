---
name: enrich-medical-note
description: Enriquece notas médicas em Markdown com imagens usando o módulo enricher empacotado no Medical Notes Workbench. Use quando o usuário pedir para enriquecer, ilustrar, adicionar figuras ou buscar imagens para uma ou mais notas médicas `.md`.
---

# Skill: enrich-medical-note

Resumo canônico do workflow: `docs/workflows/enrich.md`.
Resposta ao usuário: `knowledge/workflow-output-contract.md`.

## Quando usar

- O usuário pede para enriquecer/ilustrar uma ou mais notas Markdown médicas.
- O usuário aponta um ou mais `.md` e quer figuras de anatomia, histologia, mecanismos,
  esquemas, radiologia ou fotos clínicas.
- O usuário quer embutir imagens no formato Obsidian `![[...]]`.

Não usar para:

- Geração de imagens novas. O projeto busca e baixa imagens externas/locais.
- Reescrever livremente o conteúdo textual da nota.

## Raiz da extensão

Use `${extensionPath}` como raiz da extensão somente para ler o bundle e executar
scripts empacotados. Se o conteúdo não tiver sido hidratado pelo Gemini CLI, use
o caminho padrão:

```bash
~/.gemini/extensions/medical-notes-workbench
```

Estado editável do usuário deve ficar fora desse bundle auto-updatable:

```bash
~/.gemini/medical-notes-workbench
```

Esse diretório persistente guarda `config.toml`, `.env`, cache/índices locais e
a `.venv` do workflow quando necessário. Não grave a única cópia de segredo ou
config em `${extensionPath}`.

## Pré-condições

1. Cada nota alvo é um arquivo `.md` legível.
2. `~/.gemini/medical-notes-workbench/config.toml` existe e tem `[vault].path`
   preenchido.
3. `~/.gemini/medical-notes-workbench/.venv` existe com o pacote instalado em
   modo editável a partir de `${extensionPath}`.
4. O `gemini` CLI está autenticado, pois `scripts/enrich_notes.py` chama o Gemini
   para âncoras e rerank visual.

Se faltar ambiente Python:

```powershell
# Windows PowerShell, rodando a partir de ${extensionPath}
New-Item -ItemType Directory -Force "$HOME\.gemini\medical-notes-workbench"
py -3 -m venv "$HOME\.gemini\medical-notes-workbench\.venv"
& "$HOME\.gemini\medical-notes-workbench\.venv\Scripts\python.exe" -m pip install -e .
```

```bash
# macOS/Linux, rodando a partir de ${extensionPath}
mkdir -p ~/.gemini/medical-notes-workbench
python3 -m venv ~/.gemini/medical-notes-workbench/.venv
~/.gemini/medical-notes-workbench/.venv/bin/python -m pip install -e .
```

Se faltar configuração:

```powershell
# Windows PowerShell, rodando a partir de ${extensionPath}
New-Item -ItemType Directory -Force "$HOME\.gemini\medical-notes-workbench"
Copy-Item config.example.toml "$HOME\.gemini\medical-notes-workbench\config.toml"
```

```bash
# macOS/Linux, rodando a partir de ${extensionPath}
mkdir -p ~/.gemini/medical-notes-workbench
cp config.example.toml ~/.gemini/medical-notes-workbench/config.toml
```

Depois peça o caminho do vault Obsidian e preencha `[vault].path` no config
persistente.

Se houver `config.toml` ou `.env` antigo dentro de `${extensionPath}`, migre
para `~/.gemini/medical-notes-workbench` antes de editar.

## Como executar

```powershell
cd "${extensionPath}"
# Windows
& "$HOME\.gemini\medical-notes-workbench\.venv\Scripts\python.exe" scripts\enrich_notes.py "<caminho-da-nota.md>" --config "$HOME\.gemini\medical-notes-workbench\config.toml"
```

```bash
cd "${extensionPath}"
# macOS/Linux
~/.gemini/medical-notes-workbench/.venv/bin/python scripts/enrich_notes.py "<caminho-da-nota.md>" --config ~/.gemini/medical-notes-workbench/config.toml
```

Para enriquecer várias notas na mesma invocação:

```powershell
cd "${extensionPath}"
# Windows
& "$HOME\.gemini\medical-notes-workbench\.venv\Scripts\python.exe" scripts\enrich_notes.py "<nota1.md>" "<nota2.md>" --config "$HOME\.gemini\medical-notes-workbench\config.toml"
```

```bash
cd "${extensionPath}"
# macOS/Linux
~/.gemini/medical-notes-workbench/.venv/bin/python scripts/enrich_notes.py "<nota1.md>" "<nota2.md>" --config ~/.gemini/medical-notes-workbench/config.toml
```

Também é possível passar diretórios e globs; diretórios são expandidos
recursivamente para `.md`, com dedupe e ignorando anexos/cache:

```powershell
cd "${extensionPath}"
# Windows
& "$HOME\.gemini\medical-notes-workbench\.venv\Scripts\python.exe" scripts\enrich_notes.py "<pasta-de-notas>" "**\*.md" --config "$HOME\.gemini\medical-notes-workbench\config.toml"
```

```bash
cd "${extensionPath}"
# macOS/Linux
~/.gemini/medical-notes-workbench/.venv/bin/python scripts/enrich_notes.py "<pasta-de-notas>" "**/*.md" --config ~/.gemini/medical-notes-workbench/config.toml
```

Para refazer notas já enriquecidas, aplique `--force` ao lote:

```powershell
cd "${extensionPath}"
# Windows
& "$HOME\.gemini\medical-notes-workbench\.venv\Scripts\python.exe" scripts\enrich_notes.py "<nota1.md>" "<nota2.md>" --config "$HOME\.gemini\medical-notes-workbench\config.toml" --force
```

```bash
cd "${extensionPath}"
# macOS/Linux
~/.gemini/medical-notes-workbench/.venv/bin/python scripts/enrich_notes.py "<nota1.md>" "<nota2.md>" --config ~/.gemini/medical-notes-workbench/config.toml --force
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

Use o contrato de saída para transformar logs e JSON em resumo curto com status
emoji, contagens, arquivos relevantes, warnings e próxima ação. Não despeje JSON
bruto por padrão.

## Falhas comuns

- **Vault não configurado**: peça o caminho e atualize
  `~/.gemini/medical-notes-workbench/config.toml`.
- **Gemini CLI sem login**: peça para autenticar o Gemini CLI.
- **Gemini CLI não encontrado no Windows**: o orquestrador resolve `gemini`
  para `gemini.cmd` no PATH ou em `%APPDATA%\npm`. Se ainda falhar, ajuste
  `[gemini].binary` no config persistente para o caminho absoluto do
  `gemini.cmd`.
- **Sem `SERPAPI_KEY`/`SERPAPI_API_KEY`**: `web_search` retorna `[]`; Wikimedia
  ainda funciona.
  Para habilitar, peça ao usuário criar conta em https://serpapi.com/, copiar a
  API key do dashboard e rodar
  `gemini extensions config medical-notes-workbench SERPAPI_KEY`.
  Fallback persistente: gravar `SERPAPI_KEY=...` ou `SERPAPI_API_KEY=...` em
  `~/.gemini/medical-notes-workbench/.env`. Não grave a chave dentro de
  `${extensionPath}`.
- **Cota/limite SerpAPI esgotado**: o lote para imediatamente com `rc=9` e
  aviso claro para evitar novas chamadas à API. Oriente o usuário a renovar a
  cota/chave ou rodar novamente só com fontes disponíveis.
- **Downloads 403**: o downloader tenta headers browser-like e fallback de
  thumbnail SerpAPI quando disponível; se ainda falhar, pule a candidata.
