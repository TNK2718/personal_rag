"""Hybrid (RRF) search contract tests.

The fixture ``populated_db`` already gives us 5 documents with
title-derived FakeLLM embeddings, so the fused ranking is fully
deterministic. We assert behaviour the agent toolbox will rely on:

* FTS-only when no embedding is supplied;
* vec-only when query is empty;
* both arms contribute, with documents appearing in both arms ranked
  higher than documents in only one;
* doc_type and date filters survive the fusion;
* the returned Citation.score is the RRF fused score, not the raw FTS
  bm25 (so callers can rank-merge again at a higher layer if needed).
"""

from __future__ import annotations

import pytest

from docdb.llm.fake import FakeLLM
from docdb.search.hybrid import hybrid_search

from tests.docdb.fixtures import SAMPLE_DOCS


@pytest.fixture
def embedder() -> FakeLLM:
    return FakeLLM()


# ---------------------------------------------------------------------------
# Degenerate arms
# ---------------------------------------------------------------------------
def test_fts_only_when_embedding_is_none(populated_db) -> None:
    out = hybrid_search(populated_db, "プロジェクト", embedding=None, top_k=5)
    assert {c.document_id for c in out} == {SAMPLE_DOCS[1].id}
    # FTS path keeps its bm25 score (negative, sorted ascending).
    assert out[0].score is not None and out[0].score < 0


def test_vec_only_when_query_is_blank(populated_db, embedder: FakeLLM) -> None:
    title = SAMPLE_DOCS[3].title or SAMPLE_DOCS[3].id
    [emb] = embedder.embed([title])
    out = hybrid_search(populated_db, query="", embedding=emb, top_k=2)
    # Self-match should be first (score = 0.0 distance).
    assert out[0].document_id == SAMPLE_DOCS[3].id


def test_empty_inputs_return_empty_list(populated_db) -> None:
    assert hybrid_search(populated_db, query=None, embedding=None) == []
    assert hybrid_search(populated_db, query="   ", embedding=None) == []


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------
def test_rrf_boosts_documents_present_in_both_arms(populated_db, embedder: FakeLLM) -> None:
    # Embed the meeting doc's title; FTS will also hit the meeting doc
    # via the "プロジェクト" keyword. Both arms agree → it should win.
    meeting_title = SAMPLE_DOCS[1].title or SAMPLE_DOCS[1].id
    [emb] = embedder.embed([meeting_title])

    out = hybrid_search(populated_db, "プロジェクト", embedding=emb, top_k=3)
    assert out[0].document_id == SAMPLE_DOCS[1].id
    # The fused score must be positive (sum of two 1/(60+rank) terms).
    assert out[0].score is not None and out[0].score > 0


def test_rrf_returns_documents_unique_to_either_arm(populated_db, embedder: FakeLLM) -> None:
    # FTS finds the spec doc; vec finds the spec doc; nothing else
    # should appear since the corpus does not contain "DocDB" outside
    # SAMPLE_DOCS[3].raw_text.
    spec_title = SAMPLE_DOCS[3].title or SAMPLE_DOCS[3].id
    [emb] = embedder.embed([spec_title])

    out = hybrid_search(populated_db, "docdb", embedding=emb, top_k=5)
    ids = [c.document_id for c in out]
    assert SAMPLE_DOCS[3].id in ids  # appears in at least one arm


def test_fused_score_is_descending(populated_db, embedder: FakeLLM) -> None:
    title = SAMPLE_DOCS[2].title or SAMPLE_DOCS[2].id
    [emb] = embedder.embed([title])
    out = hybrid_search(populated_db, "技術書 OR 日記 OR 仕様", embedding=emb, top_k=5)
    scores = [c.score for c in out]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def test_doc_type_filter_applies_in_both_arms(populated_db, embedder: FakeLLM) -> None:
    [emb] = embedder.embed(["プロジェクト"])
    out = hybrid_search(
        populated_db, "プロジェクト", embedding=emb, top_k=10, doc_type="meeting"
    )
    assert {c.doc_type for c in out} == {"meeting"}


def test_date_filter_excludes_old_documents(populated_db, embedder: FakeLLM) -> None:
    [emb] = embedder.embed(["古いメモ"])
    out = hybrid_search(
        populated_db,
        "メモ OR 仕様 OR プロジェクト",
        embedding=emb,
        top_k=10,
        date_from="2026-01-01",
    )
    # The 2025-01-05 memo must not survive the filter.
    assert SAMPLE_DOCS[4].id not in {c.document_id for c in out}


def test_top_k_is_respected(populated_db, embedder: FakeLLM) -> None:
    [emb] = embedder.embed(["foo"])
    out = hybrid_search(populated_db, "メモ OR 仕様 OR 日記 OR プロジェクト OR 解約", embedding=emb, top_k=2)
    assert len(out) <= 2
