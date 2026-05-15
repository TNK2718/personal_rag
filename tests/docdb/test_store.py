"""DocumentStore (writer) contract tests for the property-graph schema."""

from __future__ import annotations

import json
import sqlite3

import pytest

from docdb.ingestion.store import DocumentStore, pack_embedding, unpack_embedding
from docdb.models import (
    Document,
    Entity,
    Relation,
    Tag,
    content_hash_for,
    document_id_for,
    entity_id_for,
    relation_id_for,
    tag_id_for,
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
# Entities (property-graph nodes)
# ---------------------------------------------------------------------------
def test_upsert_entity_inserts_and_updates(conn) -> None:
    store = DocumentStore(conn)
    e = Entity(
        id=entity_id_for("person", "Alice"),
        type_slug="person",
        canonical_name="Alice",
        aliases=["A"],
    )
    store.upsert_entity(e)
    e2 = Entity(
        id=e.id,
        type_slug="person",
        canonical_name="Alice",
        aliases=["A", "Ali"],
        description="updated",
    )
    store.upsert_entity(e2)

    row = conn.execute("SELECT * FROM entities WHERE id = ?", (e.id,)).fetchone()
    assert json.loads(row["aliases"]) == ["A", "Ali"]
    assert row["description"] == "updated"


def test_upsert_entity_validates_fields_against_registry(conn) -> None:
    """Task entity has a required `status` enum — bad values must be rejected."""
    store = DocumentStore(conn)
    good = Entity(
        id=entity_id_for("task", "write tests"),
        type_slug="task",
        canonical_name="write tests",
        fields={"status": "pending", "priority": "high"},
    )
    store.upsert_entity(good)

    bad = Entity(
        id=entity_id_for("task", "bogus"),
        type_slug="task",
        canonical_name="bogus",
        fields={"status": "definitely_not_a_status", "priority": "medium"},
    )
    with pytest.raises(ValueError):
        store.upsert_entity(bad)


def test_upsert_entity_rejects_unknown_type_slug(conn) -> None:
    store = DocumentStore(conn)
    e = Entity(
        id=entity_id_for("alien", "x"),
        type_slug="alien",  # not in entity_types
        canonical_name="x",
    )
    with pytest.raises(ValueError):
        store.upsert_entity(e)


def test_upsert_entity_refreshes_search_shadow(conn) -> None:
    store = DocumentStore(conn)
    e = Entity(
        id=entity_id_for("person", "田中"),
        type_slug="person",
        canonical_name="田中",
        aliases=["Tanaka"],
        description="社内のデザイナー",
    )
    store.upsert_entity(e)
    row = conn.execute(
        "SELECT searchable_text FROM entities_search WHERE entity_id = ?", (e.id,)
    ).fetchone()
    assert row is not None
    assert "田中" in row["searchable_text"]
    assert "Tanaka" in row["searchable_text"]
    assert "デザイナー" in row["searchable_text"]


def test_merge_aliases_into_entity_unions_and_refreshes_shadow(conn) -> None:
    """The dedup pipeline calls this when folding a new surface form
    into an existing entity. Existing canonical_name / fields stay put,
    new alias appears in both the aliases JSON and the FTS shadow."""
    store = DocumentStore(conn)
    e = Entity(
        id=entity_id_for("person", "Alice"),
        type_slug="person",
        canonical_name="Alice",
        aliases=["A"],
    )
    store.upsert_entity(e)

    store.merge_aliases_into_entity(e.id, ["Alice S.", "a", "ALICE S."])

    row = conn.execute(
        "SELECT canonical_name, aliases FROM entities WHERE id = ?", (e.id,)
    ).fetchone()
    assert row["canonical_name"] == "Alice"  # canonical unchanged
    aliases = json.loads(row["aliases"])
    assert "A" in aliases  # original preserved
    assert "Alice S." in aliases  # new surface form folded in
    # Case-insensitive dedup keeps only one of "a"/"A" and "Alice S."/"ALICE S.".
    lowered = [a.casefold() for a in aliases]
    assert len(lowered) == len(set(lowered))

    searchable = conn.execute(
        "SELECT searchable_text FROM entities_search WHERE entity_id = ?", (e.id,)
    ).fetchone()["searchable_text"]
    assert "Alice S." in searchable


def test_merge_aliases_into_entity_noop_when_id_missing(conn) -> None:
    """Calling on a non-existent id is silent — the pipeline should not
    have to pre-check existence."""
    store = DocumentStore(conn)
    store.merge_aliases_into_entity("nonexistent", ["foo"])  # no raise


def test_delete_entity_removes_row_and_search_shadow(conn) -> None:
    store = DocumentStore(conn)
    e = Entity(
        id=entity_id_for("person", "X"),
        type_slug="person",
        canonical_name="X",
    )
    store.upsert_entity(e)
    assert store.delete_entity(e.id) is True
    assert (
        conn.execute("SELECT COUNT(*) AS n FROM entities WHERE id = ?", (e.id,)).fetchone()["n"]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM entities_search WHERE entity_id = ?", (e.id,)
        ).fetchone()["n"]
        == 0
    )


# ---------------------------------------------------------------------------
# Relations (property-graph edges)
# ---------------------------------------------------------------------------
def test_upsert_relation_inserts_and_updates(conn) -> None:
    store = DocumentStore(conn)
    person = Entity(
        id=entity_id_for("person", "Alice"),
        type_slug="person",
        canonical_name="Alice",
    )
    task = Entity(
        id=entity_id_for("task", "design"),
        type_slug="task",
        canonical_name="design",
        fields={"status": "pending", "priority": "medium"},
    )
    store.upsert_entity(person)
    store.upsert_entity(task)

    rel = Relation(
        id=relation_id_for("assigned_to", task.id, person.id),
        type_slug="assigned_to",
        source_entity_id=task.id,
        target_entity_id=person.id,
    )
    store.upsert_relation(rel)

    row = conn.execute("SELECT * FROM relations WHERE id = ?", (rel.id,)).fetchone()
    assert row["type_slug"] == "assigned_to"


def test_upsert_relation_rejects_unknown_type_slug(conn) -> None:
    store = DocumentStore(conn)
    rel = Relation(
        id="rel-bogus",
        type_slug="not_a_real_relation",
        source_entity_id="x",
        target_entity_id="y",
    )
    with pytest.raises(ValueError):
        store.upsert_relation(rel)


def test_upsert_relation_fk_to_entities_enforced(conn) -> None:
    store = DocumentStore(conn)
    # Source/target entities don't exist → FK violation surfaces as IntegrityError.
    rel = Relation(
        id="rel-1",
        type_slug="mentions",
        source_entity_id="ent-missing-a",
        target_entity_id="ent-missing-b",
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_relation(rel)


# ---------------------------------------------------------------------------
# Tags + junctions
# ---------------------------------------------------------------------------
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
    e = Entity(
        id=entity_id_for("org", "X"),
        type_slug="org",
        canonical_name="X",
    )
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
# Pack helpers
# ---------------------------------------------------------------------------
def test_pack_and_unpack_round_trip() -> None:
    vec = [0.1, -0.2, 0.3, 1e-5]
    out = unpack_embedding(pack_embedding(vec))
    assert out == pytest.approx(vec, abs=1e-6)
