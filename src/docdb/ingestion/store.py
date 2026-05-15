"""SQLite-backed upsert helpers used by the ingestion pipeline.

DocumentStore is the only writer in the system. Everything else reads.
Each public method runs inside a transaction so partial state (e.g. a
document row without its embedding) cannot be observed.

Property-graph note: ``upsert_entity`` validates the entity's ``fields``
payload against the registered ``entity_types.fields_schema`` before
writing and also rewrites the ``entities_search`` shadow row so the
trigram FTS over name + aliases + description + string-typed field
values stays in sync. Direct SQL writers MUST go through this helper.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from typing import Iterable

from docdb.models import (
    Document,
    Entity,
    Relation,
    Tag,
    now_iso,
)
from docdb.typing.field_spec import validate_fields
from docdb.typing.registry import get_entity_type, get_relation_type


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
    # Entities (property-graph nodes)
    # ------------------------------------------------------------------
    def upsert_entity(
        self, entity: Entity, *, embedding: list[float] | None = None
    ) -> None:
        """Insert or update a typed entity.

        Validates ``entity.fields`` against the registered type's
        ``fields_schema`` and refreshes the FTS-fed shadow row.
        """
        type_def = get_entity_type(self.conn, entity.type_slug)
        if type_def is None:
            raise ValueError(
                f"unknown entity type_slug: {entity.type_slug!r}. "
                f"Define it via POST /api/types/entities first."
            )
        validated_fields = validate_fields(type_def.fields, dict(entity.fields or {}))

        now = now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO entities (id, type_slug, canonical_name, aliases, description,
                                      fields, created_ts, updated_ts)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(type_slug, canonical_name) DO UPDATE SET
                    aliases     = excluded.aliases,
                    description = excluded.description,
                    fields      = excluded.fields,
                    updated_ts  = excluded.updated_ts
                """,
                (
                    entity.id,
                    entity.type_slug,
                    entity.canonical_name,
                    json.dumps(entity.aliases, ensure_ascii=False),
                    entity.description,
                    json.dumps(validated_fields, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self._refresh_entity_searchable_text(
                entity.id, entity.canonical_name, entity.aliases, entity.description,
                validated_fields,
            )
            if embedding is not None:
                self._upsert_vec("entities_vec", "entity_id", entity.id, embedding)

    def merge_aliases_into_entity(
        self, entity_id: str, new_aliases: Iterable[str]
    ) -> None:
        """Push ``new_aliases`` onto an existing entity's aliases list.

        Used by the ingest pipeline when fuzzy-match dedup folds a
        freshly-extracted entity into a pre-existing one: the existing
        canonical_name + fields stay put, but the new surface form is
        recorded as an alias and the FTS shadow is refreshed so future
        ``entities_fts`` lookups find both spellings.
        """
        row = self.conn.execute(
            "SELECT canonical_name, aliases, description, fields "
            "FROM entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            return
        existing = json.loads(row["aliases"] or "[]")
        seen = {a.casefold() for a in existing}
        for alias in new_aliases:
            if not alias:
                continue
            key = alias.casefold()
            if key in seen:
                continue
            seen.add(key)
            existing.append(alias)
        with self.conn:
            self.conn.execute(
                "UPDATE entities SET aliases = ?, updated_ts = ? WHERE id = ?",
                (json.dumps(existing, ensure_ascii=False), now_iso(), entity_id),
            )
            self._refresh_entity_searchable_text(
                entity_id,
                row["canonical_name"],
                existing,
                row["description"],
                json.loads(row["fields"] or "{}"),
            )

    def delete_entity(self, entity_id: str) -> bool:
        with self.conn:
            cur = self.conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
            self.conn.execute(
                "DELETE FROM entities_vec WHERE entity_id = ?", (entity_id,)
            )
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Relations (property-graph edges)
    # ------------------------------------------------------------------
    def upsert_relation(self, relation: Relation) -> None:
        type_def = get_relation_type(self.conn, relation.type_slug)
        if type_def is None:
            raise ValueError(
                f"unknown relation type_slug: {relation.type_slug!r}. "
                f"Define it via POST /api/types/relations first."
            )
        validated_fields = validate_fields(type_def.fields, dict(relation.fields or {}))
        now = now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO relations (id, type_slug, source_entity_id, target_entity_id,
                                       fields, created_ts, updated_ts)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(type_slug, source_entity_id, target_entity_id) DO UPDATE SET
                    fields     = excluded.fields,
                    updated_ts = excluded.updated_ts
                """,
                (
                    relation.id,
                    relation.type_slug,
                    relation.source_entity_id,
                    relation.target_entity_id,
                    json.dumps(validated_fields, ensure_ascii=False),
                    now,
                    now,
                ),
            )

    def delete_relation(self, relation_id: str) -> bool:
        with self.conn:
            cur = self.conn.execute("DELETE FROM relations WHERE id = ?", (relation_id,))
        return cur.rowcount > 0

    def link_document_relation(
        self,
        document_id: str,
        relation_id: str,
        *,
        contexts: list[str] | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO document_relation_mentions (document_id, relation_id, contexts)
                VALUES (?,?,?)
                ON CONFLICT(document_id, relation_id) DO UPDATE SET
                    contexts = excluded.contexts
                """,
                (document_id, relation_id, json.dumps(contexts or [], ensure_ascii=False)),
            )

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------
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
    # Internal: searchable_text shadow + vector upsert
    # ------------------------------------------------------------------
    def _refresh_entity_searchable_text(
        self,
        entity_id: str,
        canonical_name: str,
        aliases: list[str],
        description: str | None,
        fields: dict,
    ) -> None:
        # Concatenate every string-valued field so FTS catches mentions
        # of, e.g., `task.status = pending`.
        parts: list[str] = [canonical_name]
        parts.extend(aliases or [])
        if description:
            parts.append(description)
        for value in (fields or {}).values():
            if isinstance(value, str) and value:
                parts.append(value)
        searchable = " ".join(parts)
        self.conn.execute(
            """
            INSERT INTO entities_search (entity_id, searchable_text)
            VALUES (?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                searchable_text = excluded.searchable_text
            """,
            (entity_id, searchable),
        )

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
