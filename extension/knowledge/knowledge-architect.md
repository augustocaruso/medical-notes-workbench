---
name: med-knowledge-architect
description: Guardião do Padrão Ouro da Wiki Medicina. Define estrutura de Mini-Aula, taxonomia por especialidades e regras de interconexão via Wiki-Links.
---

# Med Knowledge Architect (A Mente)

Esta skill é a autoridade máxima sobre **como** o conhecimento médico deve ser estruturado e organizado no seu Obsidian Vault, visando a aprovação em residências médicas (ENARE, SES-DF, SUS-SP).

## 🏆 O Padrão Ouro: Estrutura de Mini-Aula

Toda nota médica deve ser tratada como uma aula de alto rendimento. A estrutura obrigatória é:

1.  **Título Médico Preciso:** Nome técnico oficial da condição.
2.  **Epidemiologia:** Quem adoece? (Idade, sexo, fatores de risco clássicos de prova).
3.  **Etiologia e Fisiopatologia:** Por que e como adoece? (Mecanismos e causas principais).
4.  **Apresentação Clínica:** A "fotografia" do enunciado da questão (Sinais e sintomas clássicos).
5.  **Diagnósticos Diferenciais:** Tabelas de comparação obrigatórias sempre que possível.
6.  **Diagnóstico:** Critérios, exames laboratoriais e imagem (Destaque o **Padrão-Ouro** vs. Exame inicial).
7.  **Manejo e Tratamento:** Protocolos atualizados (Diretrizes: GINA, GOLD, ATLS, etc.).
8.  **Fechamento (Essencial):**
    *   **Resumo/Sumário:** Breve síntese do tema.
    *   **Key Points (Essência):** Os "pulos do gato" para acertar a questão.
9.  **🔗 Notas Relacionadas:**
    *   Sessão baseada no `CATALOGO_WIKI.json`. Liste exaustivamente todas as notas da Wiki que possuem forte conexão clínica (fisiopatologia, diagnóstico diferencial, anatomia) com o tema atual usando Wiki-Links (ex: `- [[Nota X]]`). Se nenhuma nota do catálogo for relevante, mantenha a seção e não invente links.

## 🧱 Contrato de Formato Wiki

Para notas publicadas no `Wiki_Medicina`, o padrão visual é obrigatório e deve
imitar uma apostila premium de residência: limpo, denso, escaneável e
previsível.

- Use `# Título Médico Preciso` como primeiro heading depois do YAML.
- Logo após o título, escreva uma definição curta em 2-4 linhas dizendo o que é
  o tema e por que ele importa em prova.
- Adapte as seções ao tipo de tema, mas toda nota deve responder de algum modo:
  "quando pensar?", "como confirmar?", "o que fazer?" e "qual pegadinha?".
- Todo heading de nível 2 (`##`) deve começar com um único emoji sem texto antes
  dele. Emojis semânticos preferenciais:
  `🎯` quando pensar/usar; `🧠` ideia central/fisiopatologia; `🔎` diagnóstico;
  `🩺` conduta/tratamento; `⚖️` estratificação/classificação; `⚠️` pegadinhas;
  `🏁` fechamento; `🔗` notas relacionadas. `🧬` pode ser usado para mecanismo,
  anatomia ou ciência básica quando for mais natural.
- Mantenha uma linha em branco entre parágrafos, listas, tabelas, callouts e
  headings. Não compacte blocos diferentes na mesma linha.
- Callouts Obsidian devem ser blocos isolados: deixe uma linha em branco antes
  de `> [!tip]`, `> [!warning]`, `> [!danger]` ou `> [!info]`, e outra linha
  em branco depois do bloco antes de voltar ao texto normal.
- Tabelas Markdown precisam ter o mesmo número de colunas no cabeçalho, na
  linha separadora e em todas as linhas. Não crie colunas vazias no final. Se
  uma célula contiver Wiki-Link com alias, escape o pipe do alias como
  `[[Cineangiocoronariografia (Cateterismo)\|CATE]]`; nunca deixe
  `[[...|...]]` cru dentro de tabela.
- O fechamento deve existir exatamente como `## 🏁 Fechamento`, com os
  subtítulos `### Resumo`, `### Key Points` e `### Frase de Prova`.
- Use sempre a seção final `## 🔗 Notas Relacionadas` com bullet links
  `- [[Nota Existente]]` para conexões fortes da Wiki. Use alias limpo quando
  necessário: `[[Cineangiocoronariografia (Cateterismo)|CATE]]`, nunca
  `[[Cineangiocoronariografia (Cateterismo)]]CATE`.
- Depois da seção de notas relacionadas, termine a nota exatamente com:

```markdown
---
[Chat Original](https://gemini.google.com/app/<fonte_id>)
[[_Índice_Medicina]]
```

Não substitua esse rodapé por URL absoluta local, deeplink do Obsidian,
`Fonte`, `Original`, índice sem acento, ou qualquer outro texto.

## 🇧🇷 Protocolo de Divergência (Brasil vs. Internacional)
- **Regra de Ouro:** Se houver divergência entre o UpToDate e as Diretrizes Brasileiras, destaque ambas, mas sinalize qual a conduta esperada para provas brasileiras (ENARE/SES-DF).
- **Nuances de Bancas:** Inclua avisos específicos sobre "pegadinhas" conhecidas das bancas prioritárias.

## 🎨 Estética e Padrões Visuais (Obsidian Callouts)
Utilize Callouts nativos do Obsidian:
- `> [!tip] Pulo do Gato`: Dicas mnemônicas.
- `> [!warning] Pegadinha de Banca`: Pontos de confusão frequente.
- `> [!danger] Red Flag`: Sinais de alarme clínicos.
- `> [!info] Diretriz Brasileira`: Quando difere do padrão internacional.

Nunca cole callout imediatamente após heading, lista ou parágrafo. O bloco deve
ficar visualmente separado por linha em branco antes e depois.

## 📂 Taxonomia e Organização
A taxonomia operacional do pipeline e **somente o caminho de pastas de categoria** sob `Wiki_Medicina`; o `title` vira o arquivo `.md`. Portanto, use `1. Clínica Médica/Cardiologia/Arritmias` + título `Fibrilação Atrial`, e nunca `Cardiologia/Arritmias/Fibrilação Atrial` + título `Fibrilação Atrial`.

A fonte de verdade combinada vem de `scripts/mednotes/wiki_tree.py --max-depth 4 --audit`, que retorna a taxonomia canonica, a arvore real existente e uma auditoria dry-run. Conceitualmente, a taxonomia canonica tem 5 grandes areas: `1. Clínica Médica`, `2. Cirurgia`, `3. Ginecologia e Obstetrícia`, `4. Pediatria`, `5. Medicina Preventiva`. Essas grandes areas e as especialidades canonicas sao fixas: nao invente sexta area, nova especialidade canonica, grafia alternativa, singular/plural alternativo ou pasta intermediaria. Operacionalmente, a arvore real mostra quais pastas ja existem; reutilize os nomes exatamente como aparecem ali, incluindo acentos, underscores e plural. Se uma area ou especialidade canonica estiver ausente como pasta fisica, a CLI pode materializar esse prefixo canonico. Qualquer nova pasta de taxonomia fora desse prefixo so pode ser criada quando for **uma unica folha nova** sob pai coerente; o dry-run exibira isso em `taxonomy_new_dirs`.

Erros preexistentes de organizacao devem ser corrigidos pela CLI mecanica, nao por movimentos manuais: `taxonomy-migrate --dry-run --plan-output <plano.json>` gera o plano; `taxonomy-migrate --apply --plan <plano.json> --receipt <recibo.json>` aplica movimentos inequívocos; `taxonomy-migrate --rollback --receipt <recibo.json>` desfaz. Itens bloqueados indicam conflito ou necessidade de decisao humana.

Distribuicao canonica: `1. Clínica Médica` inclui Cardiologia, Clínica Médica, Dermatologia, Endocrinologia, Gastroenterologia, Geriatria, Hematologia, Infectologia, Medicina Interna, Nefrologia, Neurologia, Oncologia, Pneumologia, Reumatologia e Psiquiatria; `2. Cirurgia` inclui Cirurgia Geral, Clínica Cirúrgica, Oftalmologia, Urologia, Trauma e Anestesiologia; `3. Ginecologia e Obstetrícia` consolida Ginecologia/Obstetrícia; `4. Pediatria` inclui Pediatria, Neonatologia, Puericultura e Infecto Pediátrica; `5. Medicina Preventiva` inclui Medicina Preventiva, SUS, Epidemiologia, Ética Médica e Saúde do Trabalho.

## 🔗 Estratégia de Interconexão e Triagem
- **Conectividade:** Conectar a nota a pelo menos 2 temas existentes via `[[Wiki-Links]]`.
- **Triagem:** Toda nota deve originar-se de um chat triado com um `titulo_triagem` descritivo que ajude na identificação rápida do conteúdo bruto.
- **Ancoragem:** Todas as notas devem terminar com o link `[[_Índice_Medicina]]`.
