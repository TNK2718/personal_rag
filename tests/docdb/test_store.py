"""DocumentStore (writer) contract tests."""

from __future__ import annotations

import json

import pytest

from docdb.ingestion.store import DocumentStore, pack_embedding, unpack_embedding
from docdb.models import (
    Document,
    Entity,
    Tag,
    Todo,
    content_hash_for,
    document_id_for,
    entity_id_for,
    tag_id_for,
    todo_id_for,
)


def _make_doc(text: str = "hello world", **overrides) -> Document:
    h = content_hash_for(text)
    base = dict(id=document_id_for(h), source_type="md", content_hash=h, raw_text=text)
    base.update(overrides)
    return Document(**base)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def test_upsert_document_inserts_row(conn) -> None:
    store = DocumentStore(conn)
    doc = _make_doc("hello", title="t1", doc_type="memo")
    store.upsert_document(doc)
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc.id,)).fetchone()
    assert row["title"] == "t1"
    assert row["doc_type"] == "memo"


def test_upsert_document_updates_on_same_content_hash(conn) -> None:
    store = DocumentStore(conn)
    doc = _make_doc("hello", title="old")
    store.upsert_document(doc)

    doc2 = _make_doc("hello", title="new", doc_type="reference")
    store.upsert_document(doc2)

    rows = conn.execute("SELECT title, doc_type FROM documents").fetchall()
    assert len(rows) == 1
    assert rows[0]["title"] == "new"
    assert rows[0]["doc_type"] == "reference"


def test_upsert_document_with_embedding_stores_vector(conn) -> None:
    store = DocumentStore(conn)
    doc = _make_doc("hello")
    embedding = [0.0] * 1024
    embedding[0] = 1.0
    store.upsert_document(doc, embedding=embedding)

    row = conn.execute(
        "SELECT embedding FROM documents_vec WHERE document_id = ?", (doc.id,)
    ).fetchone()
    assert row is not None
    vec = unpack_embedding(row["embedding"])
    assert vec[0] == pytest.approx(1.0)
    assert vec[1] == pytest.approx(0.0)


def test_upsert_document_replaces_existing_embedding(conn) -> None:
    store = DocumentStore(conn)
    doc = _make_doc("hello")
    store.upsert_document(doc, embedding=[1.0] + [0.0] * 1023)
    store.upsert_document(doc, embedding=[0.0, 1.0] + [0.0] * 1022)

    rows = conn.execute(
        "SELECT embedding FROM documents_vec WHERE document_id = ?", (doc.id,)
    ).fetchall()
    assert len(rows) == 1
    vec = unpack_embedding(rows[0]["embedding"])
    assert vec[0] == pytest.approx(0.0)
    assert vec[1] == pytest.approx(1.0)


def test_delete_document_removes_row_and_vector(conn) -> None:
    store = DocumentStore(conn)
    doc = _make_doc("hello")
    store.upsert_document(doc, embedding=[1.0] + [0.0] * 1023)
    store.delete_document(doc.id)
    assert conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM documents_vec").fetchone()["n"] == 0


def test_delete_by_source_removes_matching_documents(conn) -> None:
    store = DocumentStore(conn)
    store.upsert_document(_make_doc("a", source_path="data/x.md"))
    store.upsert_document(_make_doc("b", source_path="data/x.md"))
    store.upsert_document(_make_doc("c", source_path="data/y.md"))

    n = store.delete_by_source("data/x.md")
    assert n == 2
    remaining = conn.execute("SELECT source_path FROM documents").fetchall()
    assert [r["source_path"] for r in remaining] == ["data/y.md"]


# ---------------------------------------------------------------------------
# Entities and tags
# ---------------------------------------------------------------------------
def test_upsert_entity_inserts_and_updates(conn) -> None:
    store = DocumentStore(conn)
    e = Entity(
        id=entity_id_for("Alice", "person"),
        canonical_name="Alice",
        entity_type="person",
        aliases=["A"],
    )
    store.upsert_entity(e)
    e2 = Entity(
        id=e.id,
        canonical_name="Alice",
        entity_type="person",
        aliases=["A", "Ali"],
        description="updated",
    )
    store.upsert_entity(e2)

    row = conn.execute("SELECT * FROM entities WHERE id = ?", (e.id,)).fetchone()
    assert json.loads(row["aliases"]) == ["A", "Ali"]
    assert row["description"] == "updated"


def test_upsert_tag_is_idempotent_on_canonical_name(conn) -> None:
    store = DocumentStore(conn)
    t = Tag(id=tag_id_for("python"), canonical_name="python", category="tech")
    store.upsert_tag(t)
    store.upsert_tag(Tag(id=t.id, canonical_name="python", category="lang"))

    row = conn.execute("SELECT * FROM tags WHERE id = ?", (t.id,)).fetchone()
    assert row["category"] == "lang"


def test_link_document_entity_and_tag_are_idempotent(conn) -> None:
    store = DocumentStore(conn)
    doc = _make_doc("hello")
    store.upsert_document(doc)
    e = Entity(id=entity_id_for("X", "org"), canonical_name="X", entity_type="org")
    t = Tag(id=tag_id_for("tag1"), canonical_name="tag1")
    store.upsert_entity(e)
    store.upsert_tag(t)

    store.link_document_entity(doc.id, e.id, mention_count=2)
    store.link_document_entity(doc.id, e.id, mention_count=3)
    store.link_document_tag(doc.id, t.id, confidence=0.9, source="manual")
    store.link_document_tag(doc.id, t.id, confidence=0.5)

    de = conn.execute(
        "SELECT mention_count FROM document_entities WHERE document_id=? AND entity_id=?",
        (doc.id, e.id),
    ).fetchone()
    dt = conn.execute(
        "SELECT confidence, source FROM document_tags WHERE document_id=? AND tag_id=?",
        (doc.id, t.id),
    ).fetchone()
    assert de["mention_count"] == 3
    assert dt["confidence"] == pytest.approx(0.5)
    assert dt["source"] == "llm"


# ---------------------------------------------------------------------------
# Todos
# ---------------------------------------------------------------------------
def test_upsert_todo_inserts_and_updates_in_place(conn) -> None:
    store = DocumentStore(conn)
    doc = _make_doc("hello")
    store.upsert_document(doc)

    todo = Todo(
        id=todo_id_for(doc.id, "write tests"),
        content="write tests",
        priority="high",
        source_document_id=doc.id,
    )
    store.upsert_todo(todo)
    todo2 = Todo(
        id=todo.id,
        content="write tests",
        status="in_progress",
        priority="medium",
        source_document_id=doc.id,
    )
    store.upsert_todo(todo2)

    row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo.id,)).fetchone()
    assert row["status"] == "in_progress"
    assert row["priority"] == "medium"
    assert conn.execute("SELECT COUNT(*) AS n FROM todos").fetchone()["n"] == 1


# ---------------------------------------------------------------------------
# Pack helpers
# ---------------------------------------------------------------------------
def test_pack_and_unpack_round_trip() -> None:
    vec = [0.1, -0.2, 0.3, 1e-5]
    out = unpack_embedding(pack_embedding(vec))
    assert out == pytest.approx(vec, abs=1e-6)
