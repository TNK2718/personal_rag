"""Schema/DDL contract tests.

These tests verify the invariants that downstream code (Direct API,
Text2SQL, ingestion) relies on:
    - all expected tables exist after init_db
    - documents.content_hash is UNIQUE
    - FK ON DELETE CASCADE actually fires
    - the FTS5 trigger keeps documents_fts in sync
    - sqlite-vec virtual tables accept and return 1024-d vectors
"""

from __future__ import annotations

import sqlite3

import pytest


EXPECTED_TABLES = {
    "schema_version",
    "documents",
    "entities",
    "tags",
    "document_entities",
    "document_tags",
    "document_relations",
    "todos",
    "extraction_runs",
}

EXPECTED_VIRTUAL_TABLES = {"documents_fts", "documents_vec", "entities_vec", "tags_vec"}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def test_init_db_creates_every_expected_table(conn: sqlite3.Connection) -> None:
    names = _table_names(conn)
    assert EXPECTED_TABLES.issubset(names)
    assert EXPECTED_VIRTUAL_TABLES.issubset(names)


def test_schema_version_row_is_recorded(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["version"] == 1


def test_init_db_is_idempotent(db_path) -> None:
    from docdb.schema.connection import init_db

    init_db(db_path)
    init_db(db_path)

    with sqlite3.connect(db_path) as c:
        c.row_factory = sqlite3.Row
        count = c.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"]
    assert count == 1


def test_documents_content_hash_is_unique(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO documents(id, source_type, content_hash) VALUES (?, ?, ?)",
        ("d1", "md", "h-abc"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO documents(id, source_type, content_hash) VALUES (?, ?, ?)",
            ("d2", "md", "h-abc"),
        )


def test_document_entities_cascade_on_document_delete(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO documents(id, source_type, content_hash) VALUES (?, ?, ?)",
        ("d1", "md", "h1"),
    )
    conn.execute(
        "INSERT INTO entities(id, canonical_name, entity_type) VALUES (?, ?, ?)",
        ("e1", "Alice", "person"),
    )
    conn.execute(
        "INSERT INTO document_entities(document_id, entity_id) VALUES (?, ?)",
        ("d1", "e1"),
    )
    conn.execute("DELETE FROM documents WHERE id = ?", ("d1",))

    remaining = conn.execute(
        "SELECT COUNT(*) AS n FROM document_entities WHERE document_id = ?",
        ("d1",),
    ).fetchone()["n"]
    assert remaining == 0


def test_fts_trigger_indexes_inserted_documents(conn: sqlite3.Connection) -> None:
    # FTS5 trigram tokenizer requires the match term to be at least
    # three characters wide. Real Japanese queries are usually longer
    # than that, so 「解約条項」 is a fair sample.
    conn.execute(
        "INSERT INTO documents(id, source_type, content_hash, title, summary, raw_text) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("d1", "md", "h-fts", "解約条項について", "契約解除の規定", "本契約の解約条項 ..."),
    )
    rows = conn.execute(
        "SELECT d.id FROM documents_fts JOIN documents d ON d.rowid = documents_fts.rowid "
        "WHERE documents_fts MATCH '解約条項'"
    ).fetchall()
    assert [r["id"] for r in rows] == ["d1"]


def test_fts_trigger_removes_deleted_documents(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO documents(id, source_type, content_hash, raw_text) VALUES (?, ?, ?, ?)",
        ("d1", "md", "h-del", "alpha bravo charlie"),
    )
    conn.execute("DELETE FROM documents WHERE id = ?", ("d1",))
    rows = conn.execute("SELECT * FROM documents_fts WHERE documents_fts MATCH 'bravo'").fetchall()
    assert rows == []


def test_vec0_accepts_1024_dim_vector_and_returns_distance(conn: sqlite3.Connection) -> None:
    import struct

    def _pack(vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    vec_a = [0.0] * 1024
    vec_a[0] = 1.0
    vec_b = [0.0] * 1024
    vec_b[1] = 1.0

    conn.execute(
        "INSERT INTO documents(id, source_type, content_hash) VALUES (?, ?, ?)",
        ("d1", "md", "v-a"),
    )
    conn.execute(
        "INSERT INTO documents(id, source_type, content_hash) VALUES (?, ?, ?)",
        ("d2", "md", "v-b"),
    )
    conn.execute(
        "INSERT INTO documents_vec(document_id, embedding) VALUES (?, ?)",
        ("d1", _pack(vec_a)),
    )
    conn.execute(
        "INSERT INTO documents_vec(document_id, embedding) VALUES (?, ?)",
        ("d2", _pack(vec_b)),
    )

    rows = conn.execute(
        "SELECT document_id, distance FROM documents_vec "
        "WHERE embedding MATCH ? AND k = 2 ORDER BY distance",
        (_pack(vec_a),),
    ).fetchall()
    assert [r["document_id"] for r in rows] == ["d1", "d2"]
    assert rows[0]["distance"] == pytest.approx(0.0, abs=1e-5)
