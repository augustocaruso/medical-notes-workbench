"""Cache SQLite único para o pipeline.

Três tabelas:
- ``anchors``: chave ``sha256(markdown_body)``, JSON da lista de âncoras
  produzida na Etapa 1 (Gemini). Sem TTL — markdown idêntico → mesma saída.
- ``candidates``: chave ``(source, query, visual_type)``, JSON da lista de
  candidatas devolvida por um adapter na Etapa 2. TTL configurável (default
  30d) porque APIs de fonte mudam.
- ``images``: chave ``sha256`` do conteúdo binário. Mapeia para o filename
  local. Permanente (asset baixado é asset baixado).

API minimalista; só ``get_*`` / ``put_*`` por tabela. Sem migrations — o
schema é idempotente via ``CREATE TABLE IF NOT EXISTS``.

``Cache`` aceita ``clock`` injetável para tornar TTL testável sem manipular
relógio do sistema. Suporta ``":memory:"`` para testes.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from enricher.config import expand_path


__all__ = ["Cache"]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS anchors (
    note_sha   TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    source      TEXT NOT NULL,
    query       TEXT NOT NULL,
    visual_type TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    PRIMARY KEY (source, query, visual_type)
);
CREATE TABLE IF NOT EXISTS images (
    sha        TEXT PRIMARY KEY,
    filename   TEXT NOT NULL,
    source     TEXT NOT NULL,
    source_url TEXT NOT NULL,
    width      INTEGER,
    height     INTEGER,
    bytes      INTEGER,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS url_index (
    image_url  TEXT PRIMARY KEY,
    sha        TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


class Cache:
    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        path_str = str(path)
        if path_str == ":memory:":
            self.path: str | Path = path_str
        else:
            resolved = expand_path(path_str)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self.path = resolved
        self._conn = sqlite3.connect(str(self.path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._clock = clock

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --- anchors -----------------------------------------------------

    def get_anchors(self, note_sha: str) -> list[dict[str, Any]] | None:
        row = self._conn.execute(
            "SELECT payload FROM anchors WHERE note_sha = ?", (note_sha,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put_anchors(self, note_sha: str, anchors: list[dict[str, Any]]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO anchors(note_sha, payload, created_at) "
            "VALUES (?, ?, ?)",
            (note_sha, json.dumps(anchors, ensure_ascii=False), self._clock()),
        )
        self._conn.commit()

    # --- candidates (TTL) --------------------------------------------

    def get_candidates(
        self,
        source: str,
        query: str,
        visual_type: str,
        *,
        ttl_days: int,
    ) -> list[dict[str, Any]] | None:
        row = self._conn.execute(
            "SELECT payload, created_at FROM candidates "
            "WHERE source = ? AND query = ? AND visual_type = ?",
            (source, query, visual_type),
        ).fetchone()
        if not row:
            return None
        payload, created_at = row
        age_days = (self._clock() - created_at) / 86400.0
        if age_days > ttl_days:
            return None
        return json.loads(payload)

    def put_candidates(
        self,
        source: str,
        query: str,
        visual_type: str,
        candidates: list[dict[str, Any]],
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO candidates"
            "(source, query, visual_type, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                source,
                query,
                visual_type,
                json.dumps(candidates, ensure_ascii=False),
                self._clock(),
            ),
        )
        self._conn.commit()

    # --- images (permanente) -----------------------------------------

    def get_image(self, sha: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT filename, source, source_url, width, height, bytes "
            "FROM images WHERE sha = ?",
            (sha,),
        ).fetchone()
        if not row:
            return None
        return {
            "sha": sha,
            "filename": row[0],
            "source": row[1],
            "source_url": row[2],
            "width": row[3],
            "height": row[4],
            "bytes": row[5],
        }

    def put_image(
        self,
        sha: str,
        *,
        filename: str,
        source: str,
        source_url: str,
        width: int | None = None,
        height: int | None = None,
        size_bytes: int | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO images"
            "(sha, filename, source, source_url, width, height, bytes, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sha,
                filename,
                source,
                source_url,
                width,
                height,
                size_bytes,
                self._clock(),
            ),
        )
        self._conn.commit()

    # --- url → sha lookup (evita re-baixar) -------------------------

    def get_sha_for_url(self, image_url: str) -> str | None:
        row = self._conn.execute(
            "SELECT sha FROM url_index WHERE image_url = ?", (image_url,)
        ).fetchone()
        return row[0] if row else None

    def put_url_index(self, image_url: str, sha: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO url_index(image_url, sha, created_at) "
            "VALUES (?, ?, ?)",
            (image_url, sha, self._clock()),
        )
        self._conn.commit()
