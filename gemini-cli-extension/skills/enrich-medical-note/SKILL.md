---
name: enrich-medical-note
description: Enriquece notas médicas em Markdown com imagens usando o medical-notes-enricher empacotado nesta extensão Gemini CLI. Use quando o usuário pedir para enriquecer, ilustrar, adicionar figuras ou buscar imagens para uma nota médica `.md`.
---

# Skill: enrich-medical-note

## Quando usar

- O usuário pede para enriquecer/ilustrar uma nota Markdown médica.
- O usuário aponta um `.md` e quer figuras de anatomia, histologia, mecanismos,
  esquemas, radiologia ou fotos clínicas.
- O usuário quer embutir imagens no formato Obsidian `![[...]]`.

Não usar para:

- Geração de imagens novas. O projeto busca e baixa imagens externas/locais.
- Reescrever livremente o conteúdo textual da nota.

## Raiz da extensão

Use `${extensionPath}` como raiz da extensão. Se o conteúdo não tiver sido
hidratado pelo Gemini CLI, use o caminho padrão:

```bash
~/.gemini/extensions/medical-notes-enricher
```

## Pré-condições

1. A nota é um arquivo `.md` legível.
2. `${extensionPath}/config.toml` existe e tem `[vault].path` preenchido.
3. `${extensionPath}/.venv` existe com o pacote instalado em modo editável.
4. O `gemini` CLI está autenticado, pois `scripts/run_agent.py` chama o Gemini
   para âncoras e rerank visual.

Se faltar ambiente Python:

```bash
cd "${extensionPath}"
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
.venv/bin/python scripts/run_agent.py "<caminho-da-nota.md>" --config config.toml
```

Para refazer uma nota já enriquecida:

```bash
cd "${extensionPath}"
.venv/bin/python scripts/run_agent.py "<caminho-da-nota.md>" --config config.toml --force
```

## Como interpretar

Reporte ao usuário:

- Número de âncoras encontradas.
- Quantas imagens foram inseridas.
- Fontes usadas (`wikimedia`, `web_search`, etc.).
- Caminho final da nota.
- Falhas toleradas, como downloads `403` ou thumbs indisponíveis.

## Falhas comuns

- **Vault não configurado**: peça o caminho e atualize `config.toml`.
- **Gemini CLI sem login**: peça para autenticar o Gemini CLI.
- **Sem `SERPAPI_KEY`**: `web_search` retorna `[]`; Wikimedia ainda funciona.
- **Downloads 403**: o downloader tenta headers browser-like e fallback de
  thumbnail SerpAPI quando disponível; se ainda falhar, pule a candidata.
