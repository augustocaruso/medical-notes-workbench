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
    *   Sessão baseada no `CATALOGO_WIKI.json`. Liste exaustivamente todas as notas da Wiki que possuem forte conexão clínica (fisiopatologia, diagnóstico diferencial, anatomia) com o tema atual usando Wiki-Links (ex: `- [[Nota X]]`). Se nenhuma nota do catálogo for relevante, omita a sessão.

## 🇧🇷 Protocolo de Divergência (Brasil vs. Internacional)
- **Regra de Ouro:** Se houver divergência entre o UpToDate e as Diretrizes Brasileiras, destaque ambas, mas sinalize qual a conduta esperada para provas brasileiras (ENARE/SES-DF).
- **Nuances de Bancas:** Inclua avisos específicos sobre "pegadinhas" conhecidas das bancas prioritárias.

## 🎨 Estética e Padrões Visuais (Obsidian Callouts)
Utilize Callouts nativos do Obsidian:
- `> [!tip] Pulo do Gato`: Dicas mnemônicas.
- `> [!warning] Pegadinha de Banca`: Pontos de confusão frequente.
- `> [!danger] Red Flag`: Sinais de alarme clínicos.
- `> [!info] Diretriz Brasileira`: Quando difere do padrão internacional.

## 📂 Taxonomia e Organização
A taxonomia operacional do pipeline e **somente o caminho de pastas de categoria** sob `Wiki_Medicina`; o `title` vira o arquivo `.md`. Portanto, use `1. Clínica Médica/Cardiologia/Arritmias` + título `Fibrilação Atrial`, e nunca `Cardiologia/Arritmias/Fibrilação Atrial` + título `Fibrilação Atrial`.

A fonte de verdade combinada vem de `scripts/mednotes/wiki_tree.py --max-depth 4 --audit`, que retorna a taxonomia canonica, a arvore real existente e uma auditoria dry-run. Conceitualmente, a taxonomia canonica tem 5 grandes areas: `1. Clínica Médica`, `2. Cirurgia`, `3. Ginecologia e Obstetrícia`, `4. Pediatria`, `5. Medicina Preventiva`. Operacionalmente, a arvore real mostra quais pastas ja existem. Reutilize os nomes exatamente como aparecem ali, incluindo acentos, underscores e plural. Nao invente raiz, grande area, especialidade, grafia alternativa, singular/plural alternativo ou pasta intermediaria. Uma nova pasta de taxonomia so pode ser proposta como **uma unica folha nova** sob um pai existente, e depende de aprovacao explicita do agente principal/usuario via `--allow-new-taxonomy-leaf`.

Distribuicao canonica: `1. Clínica Médica` inclui Cardiologia, Clínica Médica, Dermatologia, Endocrinologia, Gastroenterologia, Geriatria, Hematologia, Infectologia, Medicina Interna, Nefrologia, Neurologia, Oncologia, Pneumologia, Reumatologia e Psiquiatria; `2. Cirurgia` inclui Cirurgia Geral, Clínica Cirúrgica, Oftalmologia, Urologia, Trauma e Anestesiologia; `3. Ginecologia e Obstetrícia` consolida Ginecologia/Obstetrícia; `4. Pediatria` inclui Pediatria, Neonatologia, Puericultura e Infecto Pediátrica; `5. Medicina Preventiva` inclui Medicina Preventiva, SUS, Epidemiologia, Ética Médica e Saúde do Trabalho.

## 🔗 Estratégia de Interconexão e Triagem
- **Conectividade:** Conectar a nota a pelo menos 2 temas existentes via `[[Wiki-Links]]`.
- **Triagem:** Toda nota deve originar-se de um chat triado com um `titulo_triagem` descritivo que ajude na identificação rápida do conteúdo bruto.
- **Ancoragem:** Todas as notas devem terminar com o link `[[_Índice_Medicina]]`.
