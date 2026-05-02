"""Canonical Wiki_Medicina taxonomy schema."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wiki.taxonomy.normalize import _fold_taxonomy_segment, safe_title

CANONICAL_TAXONOMY: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "1. Clínica Médica",
        (
            "Cardiologia",
            "Dermatologia",
            "Endocrinologia",
            "Gastroenterologia",
            "Geriatria",
            "Hematologia",
            "Imunologia",
            "Infectologia",
            "Medicina Interna",
            "Nefrologia",
            "Neurologia",
            "Nutrologia",
            "Oncologia",
            "Pneumologia",
            "Reumatologia",
            "Semiologia",
            "Psiquiatria",
        ),
    ),
    (
        "2. Cirurgia",
        (
            "Cirurgia Geral",
            "Clínica Cirúrgica",
            "Oftalmologia",
            "Urologia",
            "Trauma",
            "Anestesiologia",
        ),
    ),
    (
        "3. Ginecologia e Obstetrícia",
        (
            "Ginecologia e Obstetrícia",
        ),
    ),
    (
        "4. Pediatria",
        (
            "Pediatria",
            "Neonatologia",
            "Puericultura",
            "Infecto Pediátrica",
        ),
    ),
    (
        "5. Medicina Preventiva",
        (
            "Medicina Preventiva",
            "SUS",
            "Epidemiologia",
            "Ética Médica",
            "Saúde do Trabalho",
        ),
    ),
)


CANONICAL_AREA_ALIASES: tuple[tuple[str, str], ...] = (
    ("Clinica Medica", "1. Clínica Médica"),
    ("Clínica Médica", "1. Clínica Médica"),
    ("Cirurgia", "2. Cirurgia"),
    ("Ginecologia_Obstetricia", "3. Ginecologia e Obstetrícia"),
    ("Ginecologia e Obstetricia", "3. Ginecologia e Obstetrícia"),
    ("Ginecologia e Obstetrícia", "3. Ginecologia e Obstetrícia"),
    ("Pediatria", "4. Pediatria"),
    ("Medicina Preventiva", "5. Medicina Preventiva"),
)


CANONICAL_TAXONOMY_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("Medicina Interna", "1. Clínica Médica", "Medicina Interna"),
    ("Cirurgia_Geral", "2. Cirurgia", "Cirurgia Geral"),
    ("Cirurgia Geral", "2. Cirurgia", "Cirurgia Geral"),
    ("Clinica Cirurgica", "2. Cirurgia", "Clínica Cirúrgica"),
    ("Clínica Cirúrgica", "2. Cirurgia", "Clínica Cirúrgica"),
    ("Ginecologia_Obstetricia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Ginecologia e Obstetricia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Ginecologia e Obstetrícia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Ginecologia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Obstetricia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Obstetrícia", "3. Ginecologia e Obstetrícia", "Ginecologia e Obstetrícia"),
    ("Infecto Pediatrica", "4. Pediatria", "Infecto Pediátrica"),
    ("Infecto Pediátrica", "4. Pediatria", "Infecto Pediátrica"),
    ("Infectopediatria", "4. Pediatria", "Infecto Pediátrica"),
    ("Etica Medica", "5. Medicina Preventiva", "Ética Médica"),
    ("Ética Médica", "5. Medicina Preventiva", "Ética Médica"),
    ("Saude do Trabalho", "5. Medicina Preventiva", "Saúde do Trabalho"),
    ("Saúde do Trabalho", "5. Medicina Preventiva", "Saúde do Trabalho"),
)


@dataclass(frozen=True)
class TaxonomyResolution:
    requested_taxonomy: str
    taxonomy: str
    parts: tuple[str, ...]
    canonicalized: tuple[dict[str, str], ...]
    new_dirs: tuple[str, ...]

    @property
    def has_new_dirs(self) -> bool:
        return bool(self.new_dirs)

    def to_json(self, wiki_dir: Path, title: str | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "wiki_dir": str(wiki_dir),
            "requested_taxonomy": self.requested_taxonomy,
            "taxonomy": self.taxonomy,
            "parts": list(self.parts),
            "canonicalized": list(self.canonicalized),
            "new_dirs": list(self.new_dirs),
            "requires_new_folder": self.has_new_dirs,
        }
        if title is not None:
            data["title"] = title
            data["target_path"] = str(wiki_dir.joinpath(*self.parts, f"{safe_title(title)}.md"))
        return data

def _canonical_roots_by_fold() -> dict[str, str]:
    return {_fold_taxonomy_segment(root): root for root, _specialties in CANONICAL_TAXONOMY}


def _canonical_area_aliases_by_fold() -> dict[str, str]:
    mapping = _canonical_roots_by_fold()
    for alias, root in CANONICAL_AREA_ALIASES:
        mapping[_fold_taxonomy_segment(alias)] = root
    return mapping


def _canonical_specialties_by_fold() -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    for root, specialties in CANONICAL_TAXONOMY:
        for specialty in specialties:
            mapping[_fold_taxonomy_segment(specialty)] = (root, specialty)
            mapping[_fold_taxonomy_segment(specialty.replace(" ", "_"))] = (root, specialty)
    for alias, root, specialty in CANONICAL_TAXONOMY_ALIASES:
        mapping[_fold_taxonomy_segment(alias)] = (root, specialty)
    return mapping


def _canonical_specialties_for_root(root: str) -> dict[str, str]:
    specialties = next((items for candidate, items in CANONICAL_TAXONOMY if candidate == root), ())
    mapping = {_fold_taxonomy_segment(specialty): specialty for specialty in specialties}
    for alias, alias_root, specialty in CANONICAL_TAXONOMY_ALIASES:
        if alias_root == root:
            mapping[_fold_taxonomy_segment(alias)] = specialty
    return mapping


def canonical_taxonomy_tree() -> dict[str, Any]:
    areas = []
    for root, specialties in CANONICAL_TAXONOMY:
        areas.append({"area": root, "specialties": list(specialties)})
    return {"schema": "medical-notes-workbench.canonical-taxonomy.v1", "areas": areas}
