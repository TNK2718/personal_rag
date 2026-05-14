"""Pydantic model contract tests.

These are intentionally small. The point is to lock down the public
shape (default values, validation rules, deterministic ID derivation)
that the rest of the system relies on.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docdb.models import (
    Citation,
    Document,
    Entity,
    ExtractionResult,
    Relation,
    Tag,
    content_hash_for,
    document_id_for,
    entity_id_for,
    relation_id_for,
    tag_id_for,
)


# ---------------------------------------------------------------------------
# Storage models
# ---------------------------------------------------------------------------
def test_document_only_requires_id_source_type_and_hash() -> None:
    d = Document(id="doc-1", source_type="md", content_hash="h")
    assert d.metadata == {}
    assert d.title is None
    assert d.language is None


def test_document_rejects_unknown_source_type() -> None:
    with pytest.raises(ValidationError):
        Document(id="d", source_type="xml", content_hash="h")  # type: ignore[arg-type]


def test_entity_holds_type_slug_and_fields_dict() -> None:
    e = Entity(id="ent-1", type_slug="person", canonical_name="Alice")
    assert e.aliases == []
    assert e.fields == {}
    assert e.type_slug == "person"


def test_entity_accepts_arbitrary_field_payload() -> None:
    # Type slug validation against the registry is performed at the store
    # layer, not on the in-memory model.
    e = Entity(
        id="ent-2",
        type_slug="meeting_topic",  # user-defined; the model does not constrain
        canonical_name="Q2 OKR",
        fields={"decision": "do it"},
    )
    assert e.fields["decision"] == "do it"


def test_relation_requires_source_target_and_type() -> None:
    r = Relation(id="rel-1", type_slug="assigned_to", source_entity_id="a", target_entity_id="b")
    assert r.fields == {}


def test_tag_can_carry_optional_category() -> None:
    t = Tag(id="t", canonical_name="python", category="tech")
    assert t.category == "tech"


def test_citation_holds_optional_score_and_snippet() -> None:
    c = Citation(document_id="d1", title="hello", snippet="...world...", score=0.42)
    assert c.score == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# Extraction header (Stage 2: entities/relations are filled dynamically in Stage 3)
# ---------------------------------------------------------------------------
def test_extraction_result_has_safe_defaults() -> None:
    r = ExtractionResult()
    assert r.doc_type == "other"
    assert r.tags == []


def test_summary_is_capped_at_600_chars() -> None:
    with pytest.raises(ValidationError):
        ExtractionResult(summary="a" * 601)


# ---------------------------------------------------------------------------
# Deterministic ID helpers
# ---------------------------------------------------------------------------
def test_document_id_is_deterministic_and_prefixed() -> None:
    h = content_hash_for("hello world\n")
    assert document_id_for(h) == document_id_for(h)
    assert document_id_for(h).startswith("doc-")
    assert len(document_id_for(h)) == len("doc-") + 12


def test_entity_id_distinguishes_same_name_different_type() -> None:
    assert entity_id_for("org", "Apple") != entity_id_for("product", "Apple")


def test_relation_id_depends_on_all_three_components() -> None:
    a = relation_id_for("assigned_to", "ent-a", "ent-b")
    b = relation_id_for("assigned_to", "ent-b", "ent-a")
    c = relation_id_for("mentions", "ent-a", "ent-b")
    assert a != b
    assert a != c
    assert relation_id_for("assigned_to", "ent-a", "ent-b") == a
    assert a.startswith("rel-")


def test_tag_id_collides_for_same_canonical_name() -> None:
    assert tag_id_for("python") == tag_id_for("python")
    assert tag_id_for("python") != tag_id_for("Python")
