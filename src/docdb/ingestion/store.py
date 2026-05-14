"""SQLite-backed upsert helpers used by the ingestion pipeline.

DocumentStore is the only writer in the system. Everything else reads.
Each public method runs inside a transaction so partial state (e.g. a
document row without its embedding) cannot be observed.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from typing import Iterable

from docdb.models import (
    Document,
    Entity,
    Tag,
    Todo,
    now_iso,
)


def pack_embedding(vec: Iterable[float]) -> bytes:
    """Pack a float vector into the byte layout sqlite-vec expects."""
    floats = list(vec)
    return struct.pack(f"{len(floats)}f", *floats)


def unpack_embedding(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


class DocumentStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def upsert_document(
        self, doc: Document, *, embedding: list[float] | None = None
    ) -> None:
        metadata_json = json.dumps(doc.metadata or {}, ensure_ascii=False)
        now = now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO documents (
                    id, source_path, source_uri, source_type, title, doc_type,
                    author, created_at, summary, raw_text, content_hash,
                    language, metadata, created_ts, updated_ts
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(content_hash) DO UPDATE SET
                    source_path = excluded.source_path,
                    source_uri  = excluded.source_uri,
                    source_type = excluded.source_type,
                    title       = excluded.title,
                    doc_type    = excluded.doc_type,
                    author      = excluded.author,
                    created_at  = excluded.created_at,
                    summary     = excluded.summary,
                    raw_text    = excluded.raw_text,
                    language    = excluded.language,
                    metadata    = excluded.metadata,
                    updated_ts  = excluded.updated_ts
                """,
                (
                    doc.id,
                    doc.source_path,
                    doc.source_uri,
                    doc.source_type,
                    doc.title,
                    doc.doc_type,
                    doc.author,
                    doc.created_at,
                    doc.summary,
                    doc.raw_text,
                    doc.content_hash,
                    doc.language,
                    metadata_json,
                    now,
                    now,
                ),
            )
            if embedding is not None:
                self._upsert_vec("documents_vec", "document_id", doc.id, embedding)

    def delete_document(self, document_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            self.conn.execute(
                "DELETE FROM documents_vec WHERE document_id = ?", (document_id,)
            )

    def delete_by_source(self, source_path: str) -> int:
        with self.conn:
            rows = self.conn.execute(
                "SELECT id FROM documents WHERE source_path = ?", (source_path,)
            ).fetchall()
            for r in rows:
                self.conn.execute("DELETE FROM documents WHERE id = ?", (r["id"],))
                self.conn.execute(
                    "DELETE FROM documents_vec WHERE document_id = ?", (r["id"],)
                )
        return len(rows)

    # ------------------------------------------------------------------
    # Entities / tags / links
    # ------------------------------------------------------------------
    def upsert_entity(
        self, entity: Entity, *, embedding: list[float] | None = None
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO entities (id, canonical_name, entity_type, aliases, description, metadata)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(canonical_name, entity_type) DO UPDATE SET
                    aliases     = excluded.aliases,
                    description = excluded.description,
                    metadata    = excluded.metadata
                """,
                (
                    entity.id,
                    entity.canonical_name,
                    entity.entity_type,
                    json.dumps(entity.aliases, ensure_ascii=False),
                    entity.description,
                    json.dumps(entity.metadata or {}, ensure_ascii=False),
                ),
            )
            if embedding is not None:
                self._upsert_vec("entities_vec", "entity_id", entity.id, embedding)

    def upsert_tag(self, tag: Tag, *, embedding: list[float] | None = None) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO tags (id, canonical_name, aliases, category)
                VALUES (?,?,?,?)
                ON CONFLICT(canonical_name) DO UPDATE SET
                    aliases  = excluded.aliases,
                    category = excluded.category
                """,
                (
                    tag.id,
                    tag.canonical_name,
                    json.dumps(tag.aliases, ensure_ascii=False),
                    tag.category,
                ),
            )
            if embedding is not None:
                self._upsert_vec("tags_vec", "tag_id", tag.id, embedding)

    def link_document_entity(
        self,
        document_id: str,
        entity_id: str,
        *,
        mention_count: int = 1,
        contexts: list[str] | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO document_entities (document_id, entity_id, mention_count, contexts)
                VALUES (?,?,?,?)
                ON CONFLICT(document_id, entity_id) DO UPDATE SET
                    mention_count = excluded.mention_count,
                    contexts      = excluded.contexts
                """,
                (
                    document_id,
                    entity_id,
                    mention_count,
                    json.dumps(contexts or [], ensure_ascii=False),
                ),
            )

    def link_document_tag(
        self,
        document_id: str,
        tag_id: str,
        *,
        confidence: float = 1.0,
        source: str = "llm",
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO document_tags (document_id, tag_id, confidence, source)
                VALUES (?,?,?,?)
                ON CONFLICT(document_id, tag_id) DO UPDATE SET
                    confidence = excluded.confidence,
                    source     = excluded.source
                """,
                (document_id, tag_id, confidence, source),
            )

    # ------------------------------------------------------------------
    # Todos
    # ------------------------------------------------------------------
    def upsert_todo(self, todo: Todo) -> None:
        now = now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO todos (
                    id, content, status, priority, due_date,
                    source_document_id, source_section, created_at, updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    content            = excluded.content,
                    status             = excluded.status,
                    priority           = excluded.priority,
                    due_date           = excluded.due_date,
                    source_document_id = excluded.source_document_id,
                    source_section     = excluded.source_section,
                    updated_at         = excluded.updated_at
                """,
                (
                    todo.id,
                    todo.content,
                    todo.status,
                    todo.priority,
                    todo.due_date,
                    todo.source_document_id,
                    todo.source_section,
                    todo.created_at or now,
                    now,
                ),
            )

    # ------------------------------------------------------------------
    # Internal: vector upsert
    # ------------------------------------------------------------------
    def _upsert_vec(
        self,
        table: str,
        pk_column: str,
        pk_value: str,
        embedding: list[float],
    ) -> None:
        # sqlite-vec virtual tables don't support ON CONFLICT, so we
        # delete the existing row first when present.
        self.conn.execute(
            f"DELETE FROM {table} WHERE {pk_column} = ?", (pk_value,)
        )
        self.conn.execute(
            f"INSERT INTO {table} ({pk_column}, embedding) VALUES (?, ?)",
            (pk_value, pack_embedding(embedding)),
        )
