"""Level 1 — Direct search API.

These functions are the lowest-friction way to query DocDB. The agent
toolbox (Level 3) wraps these one-to-one as tools, and Text2SQL
(Level 2) shares the same underlying connection. Everything here is
read-only.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable

from docdb.ingestion.store import pack_embedding
from docdb.models import Citation, Document, Entity, Relation


def _row_to_document(row: sqlite3.Row) -> Document:
    import json as _json

    metadata = {}
    if row["metadata"]:
        try:
            metadata = _json.loads(row["metadata"])
        except (ValueError, TypeError):
            metadata = {}
    return Document(
        id=row["id"],
        source_path=row["source_path"],
        source_uri=row["source_uri"],
        source_type=row["source_type"],
        title=row["title"],
        doc_type=row["doc_type"],
        author=row["author"],
        created_at=row["created_at"],
        summary=row["summary"],
        raw_text=row["raw_text"],
        content_hash=row["content_hash"],
        language=row["language"],
        metadata=metadata,
    )


def _row_to_entity(row: sqlite3.Row) -> Entity:
    import json as _json

    aliases: list[str] = []
    fields: dict = {}
    if row["aliases"]:
        try:
            aliases = _json.loads(row["aliases"])
        except (ValueError, TypeError):
            aliases = []
    if row["fields"]:
        try:
            fields = _json.loads(row["fields"])
        except (ValueError, TypeError):
            fields = {}
    return Entity(
        id=row["id"],
        type_slug=row["type_slug"],
        canonical_name=row["canonical_name"],
        aliases=aliases,
        description=row["description"],
        fields=fields,
    )


def _row_to_relation(row: sqlite3.Row) -> Relation:
    import json as _json

    fields: dict = {}
    if row["fields"]:
        try:
            fields = _json.loads(row["fields"])
        except (ValueError, TypeError):
            fields = {}
    return Relation(
        id=row["id"],
        type_slug=row["type_slug"],
        source_entity_id=row["source_entity_id"],
        target_entity_id=row["target_entity_id"],
        fields=fields,
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def get_document(conn: sqlite3.Connection, document_id: str) -> Document | None:
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    return _row_to_document(row) if row else None


def count_documents(
    conn: sqlite3.Connection, *, doc_type: str | None = None
) -> int:
    if doc_type is None:
        row = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE doc_type = ?", (doc_type,)
        ).fetchone()
    return int(row["n"])


def list_doc_types(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT COALESCE(doc_type, '(unset)') AS doc_type, COUNT(*) AS n "
        "FROM documents GROUP BY doc_type ORDER BY n DESC, doc_type"
    ).fetchall()
    return [(r["doc_type"], int(r["n"])) for r in rows]


def count_entities_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT type_slug, COUNT(*) AS n FROM entities GROUP BY type_slug"
    ).fetchall()
    return {r["type_slug"]: int(r["n"]) for r in rows}


def get_recent_documents(
    conn: sqlite3.Connection, *, days: int = 7, limit: int = 20
) -> list[Document]:
    rows = conn.execute(
        "SELECT * FROM documents "
        "WHERE created_at IS NOT NULL "
        "  AND created_at >= date('now', ?) "
        "ORDER BY created_at DESC LIMIT ?",
        (f"-{int(days)} days", limit),
    ).fetchall()
    return [_row_to_document(r) for r in rows]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search(
    conn: sqlite3.Connection,
    query: str | None = None,
    *,
    top_k: int = 10,
    doc_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[Citation]:
    """Hybrid-ish full-text + structured filter search.

    * If ``query`` is non-empty, this is an FTS5 search ordered by bm25.
    * If ``query`` is empty, the result is a metadata-filtered list
      ordered by most-recent ``created_at``.
    * ``doc_type``/``date_from``/``date_to`` apply in both modes.
    """
    if query and query.strip():
        sql = (
            "SELECT d.id, d.title, d.source_path, d.doc_type, "
            "       snippet(documents_fts, 2, '<b>', '</b>', '...', 32) AS snippet, "
            "       bm25(documents_fts) AS score "
            "FROM documents_fts "
            "JOIN documents AS d ON d.rowid = documents_fts.rowid "
            "WHERE documents_fts MATCH ?"
        )
        params: list = [query]
        if doc_type is not None:
            sql += " AND d.doc_type = ?"
            params.append(doc_type)
        if date_from is not None:
            sql += " AND d.created_at >= ?"
            params.append(date_from)
        if date_to is not None:
            sql += " AND d.created_at <= ?"
            params.append(date_to)
        # bm25() is negative; smaller (more negative) = better.
        sql += " ORDER BY score LIMIT ?"
        params.append(int(top_k))
        rows = conn.execute(sql, params).fetchall()
        return [
            Citation(
                document_id=r["id"],
                title=r["title"],
                snippet=r["snippet"],
                score=float(r["score"]),
                source_path=r["source_path"],
                doc_type=r["doc_type"],
            )
            for r in rows
        ]

    # Structured-only branch.
    sql = "SELECT d.id, d.title, d.source_path, d.doc_type, d.summary FROM documents AS d WHERE 1=1"
    params = []
    if doc_type is not None:
        sql += " AND d.doc_type = ?"
        params.append(doc_type)
    if date_from is not None:
        sql += " AND d.created_at >= ?"
        params.append(date_from)
    if date_to is not None:
        sql += " AND d.created_at <= ?"
        params.append(date_to)
    sql += " ORDER BY COALESCE(d.created_at, '') DESC LIMIT ?"
    params.append(int(top_k))
    rows = conn.execute(sql, params).fetchall()
    return [
        Citation(
            document_id=r["id"],
            title=r["title"],
            snippet=(r["summary"] or "")[:160],
            score=None,
            source_path=r["source_path"],
            doc_type=r["doc_type"],
        )
        for r in rows
    ]


def find_similar(
    conn: sqlite3.Connection,
    document_id: str,
    *,
    top_k: int = 5,
) -> list[Citation]:
    """Vector KNN over ``documents_vec``, excluding the source document."""
    src = conn.execute(
        "SELECT embedding FROM documents_vec WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if src is None:
        return []

    rows = conn.execute(
        "SELECT v.document_id, v.distance, d.title, d.source_path, d.doc_type, d.summary "
        "FROM documents_vec AS v "
        "JOIN documents     AS d ON d.id = v.document_id "
        "WHERE v.embedding MATCH ? AND v.k = ? "
        "ORDER BY v.distance",
        (src["embedding"], top_k + 1),
    ).fetchall()
    return [
        Citation(
            document_id=r["document_id"],
            title=r["title"],
            snippet=(r["summary"] or "")[:160],
            score=float(r["distance"]),
            source_path=r["source_path"],
            doc_type=r["doc_type"],
        )
        for r in rows
        if r["document_id"] != document_id
    ][:top_k]


# ---------------------------------------------------------------------------
# Entities (property-graph nodes)
# ---------------------------------------------------------------------------
def search_entities(
    conn: sqlite3.Connection,
    name_partial: str,
    *,
    type_slug: str | None = None,
    top_k: int = 10,
) -> list[Entity]:
    """Substring search over canonical_name, optionally filtered by type_slug.

    Callers wanting trigram FTS over name + aliases + field values should
    use the dedicated entities_fts virtual table directly.
    """
    sql = "SELECT * FROM entities WHERE canonical_name LIKE ? "
    params: list = [f"%{name_partial}%"]
    if type_slug is not None:
        sql += "AND type_slug = ? "
        params.append(type_slug)
    sql += "ORDER BY canonical_name LIMIT ?"
    params.append(int(top_k))
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_entity(r) for r in rows]


def get_entity(conn: sqlite3.Connection, entity_id: str) -> Entity | None:
    row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return _row_to_entity(row) if row else None


def get_entity_documents(
    conn: sqlite3.Connection, entity_id: str, *, top_k: int = 20
) -> list[Document]:
    rows = conn.execute(
        "SELECT d.* FROM documents AS d "
        "JOIN document_entities AS de ON de.document_id = d.id "
        "WHERE de.entity_id = ? "
        "ORDER BY de.mention_count DESC, d.created_at DESC LIMIT ?",
        (entity_id, top_k),
    ).fetchall()
    return [_row_to_document(r) for r in rows]


# ---------------------------------------------------------------------------
# Relations (property-graph edges)
# ---------------------------------------------------------------------------
def search_relations(
    conn: sqlite3.Connection,
    *,
    source_entity_id: str | None = None,
    target_entity_id: str | None = None,
    type_slug: str | None = None,
    top_k: int = 50,
) -> list[Relation]:
    sql = "SELECT * FROM relations WHERE 1=1"
    params: list = []
    if source_entity_id is not None:
        sql += " AND source_entity_id = ?"
        params.append(source_entity_id)
    if target_entity_id is not None:
        sql += " AND target_entity_id = ?"
        params.append(target_entity_id)
    if type_slug is not None:
        sql += " AND type_slug = ?"
        params.append(type_slug)
    sql += " ORDER BY created_ts DESC LIMIT ?"
    params.append(int(top_k))
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_relation(r) for r in rows]


# ---------------------------------------------------------------------------
# Vector helpers (used by tests / future hybrid scoring)
# ---------------------------------------------------------------------------
def search_by_embedding(
    conn: sqlite3.Connection,
    embedding: Iterable[float],
    *,
    top_k: int = 10,
    doc_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[Citation]:
    """Vector KNN over ``documents_vec`` with optional structured filters.

    vec0 has no native pre-filter (the virtual table only knows the
    embedding column), so when callers add structured predicates we ask
    vec0 for more rows than requested and let the JOIN+WHERE peel them
    down to ``top_k``. The over-fetch factor 2 is empirical — high enough
    to absorb typical doc_type / date selectivity, low enough not to scan
    most of the index.
    """
    has_filter = doc_type is not None or date_from is not None or date_to is not None
    knn_k = top_k * 2 if has_filter else top_k

    sql = (
        "SELECT v.document_id, v.distance, d.title, d.source_path, d.doc_type, d.summary "
        "FROM documents_vec AS v "
        "JOIN documents     AS d ON d.id = v.document_id "
        "WHERE v.embedding MATCH ? AND v.k = ?"
    )
    params: list = [pack_embedding(embedding), knn_k]
    if doc_type is not None:
        sql += " AND d.doc_type = ?"
        params.append(doc_type)
    if date_from is not None:
        sql += " AND d.created_at IS NOT NULL AND d.created_at >= ?"
        params.append(date_from)
    if date_to is not None:
        sql += " AND d.created_at IS NOT NULL AND d.created_at <= ?"
        params.append(date_to)
    sql += " ORDER BY v.distance LIMIT ?"
    params.append(int(top_k))

    rows = conn.execute(sql, params).fetchall()
    return [
        Citation(
            document_id=r["document_id"],
            title=r["title"],
            snippet=(r["summary"] or "")[:160],
            score=float(r["distance"]),
            source_path=r["source_path"],
            doc_type=r["doc_type"],
        )
        for r in rows
    ]
