---
name: enrich-medical-note
description: Enriquece notas médicas em Markdown com imagens. Use quando o usuário pedir para "enriquecer nota", "adicionar imagens à nota", "ilustrar nota médica" ou referir uma nota .md vinda do gemini-md-export e quiser figuras de anatomia, histologia, mecanismos, esquemas ou imagens radiológicas embutidas no texto.
---

# Skill: enrich-medical-note

## Quando disparar

- Usuário pede para enriquecer/ilustrar uma nota Markdown médica.
- Usuário aponta um `.md` exportado pelo `gemini-md-export` (frontmatter tem `chat_id`, `url`, `source: gemini-web`).
- Usuário pede para "adicionar figuras" ou "buscar imagens" para um arquivo `.md` específico.

Não disparar para:
- Geração de imagens novas (não existe geração; só busca em fontes externas/locais).
- Edição livre do conteúdo textual da nota — o escopo é exclusivamente inserção de imagens + atualização aditiva do frontmatter.

## Pré-condições antes de invocar o script

1. O arquivo apontado é um `.md` legível. Frontmatter é opcional e o schema é livre.
2. `~/Documents/medical-notes-enricher/config.toml` existe e tem `[vault].path` preenchido. Se estiver ausente ou vazio, peça o caminho do vault Obsidian antes de prosseguir.
3. O `gemini` CLI está instalado/autenticado, ou `[gemini].binary` no `config.toml` aponta para o binário correto. O projeto usa OAuth/login do CLI; não exige `GEMINI_API_KEY`.

## Como invocar

```bash
cd ~/Documents/medical-notes-enricher
source .venv/bin/activate  # se ainda não estiver ativo
python scripts/run_agent.py <caminho-da-nota> [--config config.toml] [--force]
```

Para enriquecer várias notas:

```bash
# Não há batch oficial ainda. Itere sobre os arquivos chamando run_agent.py.
for note in <pasta-de-notas>/*.md; do
  python scripts/run_agent.py "$note" --config config.toml
done
```

## Como interpretar a saída

A CLI imprime relatório por etapa (`[1/3] ... [3/3] ...`). Reporte ao usuário:
- Total de âncoras encontradas e quantas foram preenchidas.
- Fontes usadas e contagem por fonte.
- Caminho final da nota atualizada.
- Erros por etapa (se houver), com sugestão de causa provável.

## Limites

- Máx 5 imagens por nota (cap em `config.toml` e no prompt).
- 1 nota por invocação por padrão.
- Toda imagem escolhida pelo re-rank é baixada e embutida via `![[...]]` (uso pessoal/estudo, fair use). Não há diferenciação por licença.

## Falhas comuns e o que fazer

- **Vault não configurado** → peça o caminho e atualize `config.toml`.
- **`gemini` CLI ausente ou sem login** → peça para instalar/autenticar o CLI ou ajustar `[gemini].binary`.
- **Etapa 2 (busca) falha em todas as fontes** → nota fica intacta; reporte âncoras descobertas mas vazias.
- **Re-rodar a nota** → idempotente por `images_enriched: true`; ofereça `--force` se o usuário quiser refazer escolhas.
