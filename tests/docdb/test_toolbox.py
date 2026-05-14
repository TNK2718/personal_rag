"""Toolbox dispatch / handler tests.

The toolbox is the agent's seam to the DB. Tests cover:

* every public tool's happy path produces JSON-encodable dicts;
* invalid JSON arguments, unknown tool names, bad keyword sets, and
  runtime exceptions surface on ToolInvocation.error rather than
  raising;
* execute_readonly_sql goes through the same sql_guard as Text2SQL,
  so unsafe SQL stays out;
* openai_tools() returns the OpenAI-shaped tool schema dict for each
  spec.
"""

from __future__ import annotations

import json

import pytest

from docdb.agent.toolbox import Toolbox
from docdb.llm.fake import FakeLLM

from tests.docdb.fixtures import SAMPLE_DOCS, SAMPLE_ENTITIES


@pytest.fixture
def toolbox(populated_db):
    return Toolbox(populated_db, FakeLLM(), embedder=FakeLLM())


# ---------------------------------------------------------------------------
# search_documents
# ---------------------------------------------------------------------------
def test_search_documents_fts_branch(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("search_documents", {"query": "解約条項"})
    assert inv.succeeded
    ids = [r["document_id"] for r in inv.result]
    assert SAMPLE_DOCS[0].id in ids


def test_search_documents_hybrid_branch(toolbox: Toolbox) -> None:
    inv = toolbox.invoke(
        "search_documents",
        {"query": "プロジェクト", "hybrid": True, "top_k": 3},
    )
    assert inv.succeeded
    # The meeting doc should rank first (both arms agree).
    assert inv.result[0]["document_id"] == SAMPLE_DOCS[1].id


def test_search_documents_respects_doc_type_filter(toolbox: Toolbox) -> None:
    # Use 3-char queries to satisfy FTS5 trigram tokenizer.
    inv = toolbox.invoke(
        "search_documents", {"query": "仕様書 OR メモ書き OR docdb", "doc_type": "spec"}
    )
    assert inv.succeeded
    assert {r["doc_type"] for r in inv.result} == {"spec"}


def test_search_documents_top_k_capped_by_max_results(populated_db) -> None:
    tb = Toolbox(populated_db, FakeLLM(), max_results=2)
    inv = tb.invoke(
        "search_documents", {"query": "メモ OR 仕様 OR 日記 OR プロジェクト", "top_k": 100}
    )
    assert len(inv.result) <= 2


# ---------------------------------------------------------------------------
# find_similar / get_document / list_doc_types
# ---------------------------------------------------------------------------
def test_find_similar(toolbox: Toolbox) -> None:
    inv = toolbox.invoke(
        "find_similar", {"document_id": SAMPLE_DOCS[0].id, "top_k": 3}
    )
    assert inv.succeeded
    assert all(r["document_id"] != SAMPLE_DOCS[0].id for r in inv.result)


def test_get_document_returns_truncated_raw_text(populated_db) -> None:
    # Hand-craft a long-body doc so we can see truncation kick in.
    from docdb.ingestion.store import DocumentStore
    from docdb.models import Document, content_hash_for, document_id_for

    long_body = "a" * 3000
    h = content_hash_for(long_body)
    doc = Document(
        id=document_id_for(h),
        source_type="md",
        content_hash=h,
        title="big",
        raw_text=long_body,
    )
    DocumentStore(populated_db).upsert_document(doc, embedding=[0.0] * 1024)

    tb = Toolbox(populated_db, FakeLLM())
    inv = tb.invoke("get_document", {"document_id": doc.id})
    assert inv.succeeded
    assert inv.result["title"] == "big"
    assert "truncated" in inv.result["raw_text"]
    assert len(inv.result["raw_text"]) < 3000


def test_get_document_missing_returns_none(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("get_document", {"document_id": "doc-missing"})
    assert inv.succeeded
    assert inv.result is None


def test_list_doc_types(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("list_doc_types", {})
    assert inv.succeeded
    counts = {row["doc_type"]: row["count"] for row in inv.result}
    assert counts["memo"] == 2
    assert counts["spec"] == 1


# ---------------------------------------------------------------------------
# search_entities / get_entity_documents
# ---------------------------------------------------------------------------
def test_search_entities_partial_match(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("search_entities", {"name_partial": "プロジェクト"})
    assert inv.succeeded
    assert {e["canonical_name"] for e in inv.result} == {"プロジェクトA"}


def test_get_entity_documents(toolbox: Toolbox) -> None:
    tanaka = SAMPLE_ENTITIES[0]
    inv = toolbox.invoke("get_entity_documents", {"entity_id": tanaka.id})
    assert inv.succeeded
    assert {d["id"] for d in inv.result} == {SAMPLE_DOCS[1].id}


# ---------------------------------------------------------------------------
# list_entity_types / search_relations (Stage 2)
# ---------------------------------------------------------------------------
def test_list_entity_types_returns_seed_slugs(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("list_entity_types", {})
    assert inv.succeeded
    slugs = {t["slug"] for t in inv.result}
    assert {"person", "org", "place", "task"}.issubset(slugs)


def test_search_relations_empty_by_default(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("search_relations", {})
    assert inv.succeeded
    assert inv.result == []


def test_search_entities_filters_by_type_slug(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("search_entities", {"name_partial": "", "type_slug": "task"})
    assert inv.succeeded
    assert {e["canonical_name"] for e in inv.result} == {"設計レビュー実施"}


# ---------------------------------------------------------------------------
# execute_readonly_sql
# ---------------------------------------------------------------------------
def test_execute_readonly_sql_runs_safe_select(toolbox: Toolbox) -> None:
    inv = toolbox.invoke(
        "execute_readonly_sql",
        {"sql": "SELECT id FROM documents WHERE doc_type='memo'"},
    )
    assert inv.succeeded
    assert "error" not in inv.result
    ids = {row["id"] for row in inv.result["rows"]}
    assert ids == {SAMPLE_DOCS[0].id, SAMPLE_DOCS[4].id}


def test_execute_readonly_sql_rejects_unsafe(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("execute_readonly_sql", {"sql": "DROP TABLE documents"})
    assert inv.succeeded  # no exception
    assert "error" in inv.result
    assert "unsafe sql" in inv.result["error"]


# ---------------------------------------------------------------------------
# Dispatch failure modes
# ---------------------------------------------------------------------------
def test_unknown_tool_surfaces_as_error(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("nope", {})
    assert not inv.succeeded
    assert "unknown tool" in inv.error


def test_invalid_json_arguments_surfaces_as_error(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("search_documents", "{not-json")
    assert not inv.succeeded
    assert "invalid JSON" in inv.error


def test_missing_required_argument_surfaces_as_bad_arguments(
    toolbox: Toolbox,
) -> None:
    # search_documents requires `query`.
    inv = toolbox.invoke("search_documents", {})
    assert not inv.succeeded
    assert "bad arguments" in inv.error


def test_runtime_exception_in_handler_surfaces_on_invocation(populated_db) -> None:
    class _ExplodingEmbedder(FakeLLM):
        def embed(self, texts):
            raise RuntimeError("embed offline")

    tb = Toolbox(populated_db, FakeLLM(), embedder=_ExplodingEmbedder())
    inv = tb.invoke("search_documents", {"query": "x", "hybrid": True})
    assert not inv.succeeded
    assert "embed offline" in inv.error


# ---------------------------------------------------------------------------
# OpenAI shape
# ---------------------------------------------------------------------------
def test_openai_tools_have_canonical_shape(toolbox: Toolbox) -> None:
    tools = toolbox.openai_tools()
    assert tools, "toolbox should expose at least one tool"
    for entry in tools:
        assert entry["type"] == "function"
        fn = entry["function"]
        assert fn["name"]
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"


def test_invocation_result_is_serialisable_as_json(toolbox: Toolbox) -> None:
    inv = toolbox.invoke("list_doc_types", {})
    # result_json must round-trip through json.loads.
    parsed = json.loads(inv.result_json)
    assert isinstance(parsed, list)
