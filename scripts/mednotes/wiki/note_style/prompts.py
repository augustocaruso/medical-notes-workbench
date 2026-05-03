"""LLM rewrite prompts emitted by the deterministic Wiki style validator."""
from __future__ import annotations

from typing import Any

from wiki.note_style.models import WIKI_INDEX_LINK


def rewrite_prompt(title: str, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> str:
    issue_lines = "\n".join(f"- {item['code']}: {item['message']}" for item in errors + warnings)
    return (
        "Reescreva a nota temporária abaixo para cumprir o Modelo Wiki_Medicina "
        "de estudo para residência, sem inventar fatos novos além do material-fonte. "
        f"Preserve o título '# {title}', use headings ## com emoji semântico, inclua "
        "'## 🏁 Fechamento' com '### Resumo', '### Key Points' e "
        "'### Frase de Prova', inclua '## 🔗 Notas Relacionadas' e finalize com "
        f"'---', '[Chat Original](https://gemini.google.com/app/<fonte_id>)' e '{WIKI_INDEX_LINK}'. "
        "Problemas encontrados:\n"
        f"{issue_lines}"
    )
