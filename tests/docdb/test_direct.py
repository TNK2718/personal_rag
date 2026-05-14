"""Level-1 Direct API tests.

These exercise the read-only search functions against a populated DB
fixture (5 mixed documents, 3 entities, 2 tags, 1 todo, FakeLLM-derived
embeddings). The goals:

* FTS5 returns the docs whose body contains the query (3-char minimum).
* doc_type / date filters apply in both FTS and structured-only modes.
* find_similar excludes the source document and orders by distance.
* search_entities respects entity_type filter and partial name.
"""

from __future__ import annotations

import pytest

from docdb.search.direct import (
    count_documents,
    find_similar,
    get_document,
    get_entity_documents,
    get_recent_documents,
    list_doc_types,
    search,
    search_by_embedding,
    search_entities,
)

from tests.docdb.fixtures import SAMPLE_DOCS, SAMPLE_ENTITIES, SAMPLE_TAGS


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def test_count_documents_total(populated_db) -> None:
    assert count_documents(populated_db) == len(SAMPLE_DOCS)


def test_count_documents_filtered_by_doc_type(populated_db) -> None:
    assert count_documents(populated_db, doc_type="memo") == 2
    assert count_documents(populated_db, doc_type="meeting") == 1
    assert count_documents(populated_db, doc_type="nope") == 0


def test_list_doc_types_returns_counts_ordered_by_size(populated_db) -> None:
    out = list_doc_types(populated_db)
    counts = dict(out)
    assert counts["memo"] == 2
    assert counts["spec"] == 1
    # The largest bucket appears first.
    assert out[0][1] >= out[-1][1]


def test_get_document_returns_full_model(populated_db) -> None:
    doc = SAMPLE_DOCS[0]
    fetched = get_document(populated_db, doc.id)
    assert fetched is not None
    assert fetched.title == doc.title
    assert fetched.raw_text == doc.raw_text


def test_get_document_returns_none_for_missing_id(populated_db) -> None:
    assert get_document(populated_db, "doc-doesnotexist") is None


# ---------------------------------------------------------------------------
# Full-text search
# ---------------------------------------------------------------------------
def test_search_finds_documents_by_japanese_phrase(populated_db) -> None:
    results = search(populated_db, "解約条項")
    ids = {c.document_id for c in results}
    assert SAMPLE_DOCS[0].id in ids
    # The match snippet wraps hits in <b> tags.
    hit = next(c for c in results if c.document_id == SAMPLE_DOCS[0].id)
    assert hit.snippet is not None
    assert "<b>" in hit.snippet


def test_search_respects_doc_type_filter(populated_db) -> None:
    # 議事録 contains 'プロジェクト'; the memo about cancellation does not.
    results = search(populated_db, "プロジェクト", doc_type="meeting")
    assert {c.document_id for c in results} == {SAMPLE_DOCS[1].id}

    other = search(populated_db, "プロジェクト", doc_type="memo")
    assert other == []


def test_search_respects_date_range(populated_db) -> None:
    # Only docs from 2026 should remain.
    results = search(populated_db, "メモ OR 日記 OR 仕様 OR 議事録 OR 解約",
                     date_from="2026-01-01")
    ids = {c.document_id for c in results}
    assert SAMPLE_DOCS[4].id not in ids  # 2025 doc excluded
    assert any(d.id in ids for d in SAMPLE_DOCS[:4])


def test_search_with_empty_query_returns_filtered_recents(populated_db) -> None:
    results = search(populated_db, "", doc_type="memo", top_k=5)
    ids = [c.document_id for c in results]
    # Two memo docs ordered by created_at DESC (2026 before 2025).
    assert ids == [SAMPLE_DOCS[0].id, SAMPLE_DOCS[4].id]


def test_search_with_no_query_and_no_filter_returns_recent_documents(populated_db) -> None:
    results = search(populated_db, None, top_k=3)
    assert len(results) == 3
    # First result should be the most recent (2026-05-10 spec doc).
    assert results[0].document_id == SAMPLE_DOCS[3].id


# ---------------------------------------------------------------------------
# Vector similarity
# ---------------------------------------------------------------------------
def test_find_similar_excludes_source_document(populated_db) -> None:
    results = find_similar(populated_db, SAMPLE_DOCS[0].id, top_k=3)
    assert all(c.document_id != SAMPLE_DOCS[0].id for c in results)


def test_find_similar_returns_empty_when_document_missing(populated_db) -> None:
    assert find_similar(populated_db, "doc-missing", top_k=3) == []


def test_find_similar_ordering_is_by_ascending_distance(populated_db) -> None:
    results = find_similar(populated_db, SAMPLE_DOCS[0].id, top_k=4)
    scores = [c.score for c in results]
    assert scores == sorted(scores)


def test_search_by_embedding_zero_distance_for_existing_doc(populated_db, fake_llm) -> None:
    # Re-embed the title of doc[0] — should match itself exactly.
    title = SAMPLE_DOCS[0].title or SAMPLE_DOCS[0].id
    [emb] = fake_llm.embed([title])
    results = search_by_embedding(populated_db, emb, top_k=1)
    assert results[0].document_id == SAMPLE_DOCS[0].id
    assert results[0].score == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Recent / entity queries
# ---------------------------------------------------------------------------
def test_get_recent_documents_excludes_older_than_window(populated_db, monkeypatch) -> None:
    # 90 days back from 2026-05-14 (today per the project clock) includes
    # the 2026 docs but not the 2025-01 doc.
    results = get_recent_documents(populated_db, days=90)
    # We may or may not have all 2026 docs depending on the actual now()
    # but the 2025 doc must never appear.
    assert SAMPLE_DOCS[4].id not in {c.id for c in results}


def test_search_entities_partial_name(populated_db) -> None:
    results = search_entities(populated_db, "プロジェクト")
    assert {e.canonical_name for e in results} == {"プロジェクトA"}


def test_search_entities_with_type_filter(populated_db) -> None:
    results = search_entities(populated_db, "", type_slug="task")
    assert {e.canonical_name for e in results} == {"設計レビュー実施"}


def test_get_entity_documents_returns_linked(populated_db) -> None:
    tanaka = SAMPLE_ENTITIES[0]
    results = get_entity_documents(populated_db, tanaka.id)
    assert {d.id for d in results} == {SAMPLE_DOCS[1].id}
