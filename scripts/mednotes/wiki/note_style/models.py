"""Shared constants and models for the Wiki_Medicina style contract."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STYLE_REPORT_SCHEMA = "medical-notes-workbench.wiki-note-style-report.v1"
STYLE_AUDIT_SCHEMA = "medical-notes-workbench.wiki-note-style-audit.v1"
STYLE_FIX_SCHEMA = "medical-notes-workbench.wiki-note-style-fix.v1"
WIKI_INDEX_LINK = "[[_Índice_Medicina]]"

PREFERRED_H2_EMOJIS = {"🎯", "🧠", "🔎", "🩺", "⚖️", "⚠️", "🏁", "🔗", "🧬"}

REQUIRED_SECTION_LINES = (
    "## 🏁 Fechamento",
    "### Resumo",
    "### Key Points",
    "### Frase de Prova",
    "## 🔗 Notas Relacionadas",
)

REWRITE_REQUIRED_CODES = {
    "missing_title_heading",
    "missing_h2_sections",
    "missing_required_section",
}


@dataclass(frozen=True)
class StyleIssue:
    code: str
    message: str
    severity: str
    line: int | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.line is not None:
            data["line"] = self.line
        return data
