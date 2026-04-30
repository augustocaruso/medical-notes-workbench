---
name: med-chat-processor
description: Processador autônomo que converte notas médicas brutas do Chats_Raw para o Padrão Ouro do Wiki_Medicina. Utiliza automação Python para manipular arquivos e YAML e finaliza executando a linkagem automática da Wiki.
---

# Med Chat Processor (A Fábrica)

Você é o pipeline de processamento oficial entre o "Chats_Raw" (OneDrive) e o "Wiki_Medicina" (iCloud). Sua função é limpar o backlog de anotações brutas e transformá-las em notas de alto rendimento.

## Dependências e Ferramentas
Você utilizará ativamente o script `med_ops.py` contido no diretório desta skill para operações de disco e modificações mecânicas. **Não tente editar propriedades YAML ou o Índice manualmente**, delegue para a CLI do script.

*   `Chats_Raw`: `C:\Users\leona\OneDrive\Chats_Raw`
*   `Wiki_Medicina`: `C:\Users\leona\iCloudDrive\iCloud~md~obsidian\Wiki_Medicina`
*   `CLI Mecânica`: `C:\Users\leona\.gemini\skills\med-chat-processor\med_ops.py`
*   `Linker Semântico`: `C:\Users\leona\.gemini\skills\med-auto-linker\med_linker.py`

## Passo-a-Passo Obrigatório:

### 1. Triagem Automática (Pre-requisito)
Antes de processar qualquer nota, você DEVE garantir que ela possui o YAML correto. Se o usuário pedir para "processar tudo", você deve primeiro varrer os arquivos sem status ou com status `pendente`.
- **Ação:** Leia o conteúdo, gere um **título_triagem** descritivo e curto que resuma o tema médico.
- **Inserção:** Injete ou atualize o bloco YAML:
  ```yaml
  ---
  tipo: medicina
  status: triado
  data_importacao: YYYY-MM-DD
  fonte_id: <chatId>
  titulo_triagem: "Título Descritivo Gerado por IA"
  ---
  ```

### 2. Levantamento
Execute `run_shell_command("python C:\Users\leona\.gemini\skills\med-chat-processor\med_ops.py list-triados")`.
Antes de acionar a escrita clinica, execute
`scripts/mednotes/wiki_tree.py --max-depth 4 --audit` e forneca esse JSON ao
agente de arquitetura. Ele inclui a taxonomia canonica, a arvore existente e a
auditoria dry-run. A taxonomia canonica define as 5 grandes areas; a arvore
existente mostra quais pastas ja existem. Para organizar o vault antes de
publicar, trate `audit` como dry-run, nao como permissao para mover arquivos
automaticamente. Os subcomandos `taxonomy-canonical`, `taxonomy-tree` e
`taxonomy-audit` do `med_ops.py` ficam como equivalentes separados.
Para corrigir pastas legadas de forma reversivel, use `taxonomy-migrate`:
primeiro `--dry-run --plan-output <plano.json>`, depois, com confirmacao
explicita, `--apply --plan <plano.json> --receipt <recibo.json>`. O recibo
permite `--rollback --receipt <recibo.json>`. Nunca faca merge automatico em
destino existente; reporte itens `blocked`.

### 3. Seleção e Leitura
Leia o primeiro arquivo da lista para entender o contexto clínico.

### 4. Processamento Clínico (A Mente)
- Ative suas instruções da skill `med-knowledge-architect`.
- **Carregue o `C:\Users\leona\CATALOGO_WIKI.json` em memória** para guiar a criação da seção de "Notas Relacionadas".
- Formate o texto como a "Mini-Aula" Padrão Ouro. **Atenção:** Gere múltiplas notas se o chat contiver temas distintos. Descarte se não for medicina.
- Determine a Categoria de Taxonomia exata a partir da taxonomia canonica e da arvore existente (Ex: `1. Clínica Médica/Cardiologia/Arritmias`). A taxonomia e apenas pasta de categoria; o titulo vira o arquivo. Nao use `Cardiologia/Arritmias/Fibrilacao_Atrial` quando o titulo tambem sera `Fibrilacao_Atrial`.

### 5. Staging e Aliases (Muito Importante)
Escreva as notas processadas em arquivos temporários.
- **Aliases:** Ao escrever o arquivo temporário, INJETE o bloco YAML no topo contendo os `aliases` (sinônimos exatos ou siglas do título). Não adicione palavras genéricas como "tratamento" ou "doença".
  ```yaml
  ---
  aliases: [Sigla, Sinônimo1]
  ---
  ```
- **Link Original:** Inclua no final o link: `[Chat Original](https://gemini.google.com/app/<fonte_id>)`.

### 6. Staging e Publicação Segura (O Músculo)
Registre cada nota gerada em um manifest de lote usando `stage-note`.
`run_shell_command("python C:\Users\leona\.gemini\skills\med-chat-processor\med_ops.py stage-note --manifest \"<batch_manifest.json>\" --raw-file \"<path_original>\" --taxonomy \"<Categoria/Subcategoria>\" --title \"<Titulo_Exato>\" --content \"C:\Users\leona\.gemini\tmp\leona\temp_gold_note.md\"")`
O `stage-note` canoniza grafia de pastas existentes e bloqueia taxonomia que
repete o titulo como pasta final ou inventa pastas fora da arvore. Se precisar
de nova categoria-folha, pare e peça aprovacao antes de usar
`--allow-new-taxonomy-leaf`.

Depois que todas as notas do lote estiverem no manifest, rode primeiro a simulação:
`run_shell_command("python C:\Users\leona\.gemini\skills\med-chat-processor\med_ops.py publish-batch --manifest \"<batch_manifest.json>\" --dry-run")`

Revise o resultado com o gate operacional `med-publish-guard`. Só se ele retornar `approve`, rode o publish real:
`run_shell_command("python C:\Users\leona\.gemini\skills\med-chat-processor\med_ops.py publish-batch --manifest \"<batch_manifest.json>\"")`

### 7. Loop
Repita os passos 3 a 6 até limpar a lista de arquivos triados.

### 8. Linkagem Automática (Pós-processamento)
**Obrigatório:** Assim que terminar o processamento de todo o lote e não houver mais notas a serem criadas, você **DEVE** executar o linker autônomo para atualizar a teia de conhecimento de toda a Wiki com as novas notas e aliases que você acabou de criar.
`run_shell_command("python C:\Users\leona\.gemini\skills\med-auto-linker\med_linker.py")`
