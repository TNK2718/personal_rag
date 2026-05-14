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
    ExtractedEntity,
    ExtractedTodo,
    ExtractionResult,
    Tag,
    Todo,
    content_hash_for,
    document_id_for,
    entity_id_for,
    tag_id_for,
    todo_id_for,
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


def test_entity_aliases_default_to_empty_list() -> None:
    e = Entity(id="e", canonical_name="Alice", entity_type="person")
    assert e.aliases == []


def test_entity_rejects_unknown_entity_type() -> None:
    with pytest.raises(ValidationError):
        Entity(id="e", canonical_name="x", entity_type="weapon")  # type: ignore[arg-type]


def test_tag_can_carry_optional_category() -> None:
    t = Tag(id="t", canonical_name="python", category="tech")
    assert t.category == "tech"


def test_todo_defaults_to_pending_and_medium() -> None:
    t = Todo(id="todo-1", content="write tests")
    assert t.status == "pending"
    assert t.priority == "medium"


def test_citation_holds_optional_score_and_snippet() -> None:
    c = Citation(document_id="d1", title="hello", snippet="...world...", score=0.42)
    assert c.score == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# Extraction models
# ---------------------------------------------------------------------------
def test_extraction_result_has_safe_defaults() -> None:
    r = ExtractionResult()
    assert r.doc_type == "other"
    assert r.entities == []
    assert r.tags == []
    assert r.todos == []


def test_extracted_entity_requires_non_empty_name() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntity(name="", entity_type="person")


def test_extracted_todo_requires_non_empty_content() -> None:
    with pytest.raises(ValidationError):
        ExtractedTodo(content="")


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


def test_todo_id_changes_when_source_document_changes() -> None:
    assert todo_id_for("doc-A", "write tests") != todo_id_for("doc-B", "write tests")
    assert todo_id_for(None, "write tests") == todo_id_for(None, "write tests")


def test_entity_id_distinguishes_same_name_different_type() -> None:
    assert entity_id_for("Apple", "org") != entity_id_for("Apple", "product")


def test_tag_id_collides_for_same_canonical_name() -> None:
    assert tag_id_for("python") == tag_id_for("python")
    assert tag_id_for("python") != tag_id_for("Python")
