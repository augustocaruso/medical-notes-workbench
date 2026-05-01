---
name: enrich-medical-note
description: Enriquece notas médicas em Markdown com imagens. Use quando o usuário pedir para "enriquecer nota(s)", "adicionar imagens à(s) nota(s)", "ilustrar nota médica" ou referir uma ou mais notas .md e quiser figuras de anatomia, histologia, mecanismos, esquemas ou imagens radiológicas embutidas no texto.
---

# Skill: enrich-medical-note

## Quando disparar

- Usuário pede para enriquecer/ilustrar uma ou mais notas Markdown médicas.
- Usuário aponta `.md` exportado pelo `gemini-md-export` (frontmatter tem `chat_id`, `url`, `source: gemini-web`).
- Usuário pede para "adicionar figuras" ou "buscar imagens" para arquivo(s) `.md` específico(s).

Não disparar para:
- Geração de imagens novas (não existe geração; só busca em fontes externas/locais).
- Edição livre do conteúdo textual da nota — o escopo é exclusivamente inserção de imagens + atualização aditiva do frontmatter.

## Pré-condições antes de invocar o script

1. Cada arquivo apontado é um `.md` legível. Frontmatter é opcional e o schema é livre.
2. `~/Documents/medical-notes-workbench/config.toml` existe e tem `[vault].path` preenchido. Se estiver ausente ou vazio, peça o caminho do vault Obsidian antes de prosseguir.
3. O `gemini` CLI está instalado/autenticado, ou `[gemini].binary` no `config.toml` aponta para o binário correto. O projeto usa OAuth/login do CLI; não exige `GEMINI_API_KEY`.

## Como invocar

```bash
cd ~/Documents/medical-notes-workbench
source .venv/bin/activate  # se ainda não estiver ativo
python scripts/enrich_notes.py <nota.md|pasta|glob> [outro-alvo ...] [--config config.toml] [--force]
```

Para enriquecer várias notas:

```bash
python scripts/enrich_notes.py <nota1.md> <nota2.md> --config config.toml
```

Também aceita diretórios e globs:

```bash
python scripts/enrich_notes.py <pasta-de-notas> "Wiki_Medicina/**/*.md" --config config.toml
```

## Como interpretar a saída

A CLI imprime relatório por etapa (`[1/3] ... [3/3] ...`). Reporte ao usuário:
- Total de âncoras encontradas e quantas foram preenchidas.
- Fontes usadas e contagem por fonte.
- Caminhos finais das notas atualizadas.
- Notas puladas, sem inserção e erros por nota, com sugestão de causa provável.

## Limites

- Máx 5 imagens por nota (cap em `config.toml` e no prompt).
- Lote serial: várias notas, diretórios e globs podem ser passados na mesma invocação.
- Diretórios são expandidos recursivamente para `.md`; anexos/cache comuns são ignorados.
- Toda imagem escolhida pelo re-rank é baixada e embutida via `![[...]]` (uso pessoal/estudo, fair use). Não há diferenciação por licença.

## Falhas comuns e o que fazer

- **Vault não configurado** → peça o caminho e atualize `config.toml`.
- **`gemini` CLI ausente ou sem login** → peça para instalar/autenticar o CLI ou ajustar `[gemini].binary`.
- **Cota/limite SerpAPI esgotado** → o lote para com `rc=9` para evitar novas chamadas à API; peça ao usuário renovar cota/chave ou reexecutar com outra fonte.
- **Etapa 2 (busca) falha em todas as fontes** → nota fica intacta; reporte âncoras descobertas mas vazias.
- **Re-rodar a nota** → idempotente por `images_enriched: true`; ofereça `--force` se o usuário quiser refazer escolhas.
