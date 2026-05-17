from __future__ import annotations

import json
from pathlib import Path

import pytest

from docdb.llm.fake import StubChatCompletion, StubToolCall
from collections import Counter

from tests.docdb.fixtures import SAMPLE_DOCS, SAMPLE_ENTITIES, SAMPLE_RELATIONS


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_stats(client):
    res = client.get("/api/stats")
    assert res.status_code == 200
    body = res.get_json()
    assert body["documents_total"] == len(SAMPLE_DOCS)
    assert body["entities_total"] == len(SAMPLE_ENTITIES)
    type_counts = {row["type_slug"]: row["count"] for row in body["entities_by_type"]}
    expected_counts = dict(Counter(e.type_slug for e in SAMPLE_ENTITIES))
    assert type_counts == expected_counts
    assert body["relations_total"] == len(SAMPLE_RELATIONS)
    doc_type_names = {d["doc_type"] for d in body["doc_types"]}
    assert "memo" in doc_type_names and "meeting" in doc_type_names


def test_doc_types(client):
    res = client.get("/api/doc-types")
    assert res.status_code == 200
    body = res.get_json()
    assert any(d["doc_type"] == "memo" and d["count"] >= 2 for d in body)


def test_list_documents_no_query(client):
    res = client.get("/api/documents?limit=10")
    assert res.status_code == 200
    body = res.get_json()
    assert body["total"] == len(SAMPLE_DOCS)
    assert len(body["items"]) == len(SAMPLE_DOCS)
    # Newest-first ordering.
    assert body["items"][0]["created_at"] >= body["items"][-1]["created_at"]


def test_list_documents_with_query(client):
    res = client.get("/api/documents?q=解約条項")
    assert res.status_code == 200
    items = res.get_json()["items"]
    assert any("解約" in (it["title"] or "") or "解約" in (it["snippet"] or "") for it in items)


def test_list_documents_filter_by_doc_type(client):
    res = client.get("/api/documents?doc_type=memo")
    assert res.status_code == 200
    items = res.get_json()["items"]
    assert items, "should return at least one memo"
    for it in items:
        assert it["doc_type"] == "memo"


def test_document_detail(client):
    doc_id = SAMPLE_DOCS[1].id  # project A meeting
    res = client.get(f"/api/documents/{doc_id}")
    assert res.status_code == 200
    body = res.get_json()
    assert body["id"] == doc_id
    assert body["title"] == SAMPLE_DOCS[1].title
    assert isinstance(body["entities"], list)
    # The server conftest links this document to SAMPLE_ENTITIES[1] = プロジェクトA.
    assert any(e["canonical_name"] == "プロジェクトA" for e in body["entities"])
    assert "todos" not in body


def test_document_detail_not_found(client):
    res = client.get("/api/documents/doc-nonexistent")
    assert res.status_code == 404


def test_search_endpoint(client):
    res = client.post("/api/search", json={"query": "解約条項", "top_k": 5})
    assert res.status_code == 200
    body = res.get_json()
    assert isinstance(body, list)
    assert any("解約" in (h["title"] or "") for h in body)


def test_list_entities(client):
    res = client.get("/api/entities")
    assert res.status_code == 200
    items = res.get_json()
    assert len(items) >= 3
    assert all("canonical_name" in it for it in items)


def test_entity_documents(client):
    # The server conftest links プロジェクトA (entities[1]) to docs[1].
    ent_id = SAMPLE_ENTITIES[1].id
    res = client.get(f"/api/entities/{ent_id}/documents")
    assert res.status_code == 200
    docs = res.get_json()
    assert any(d["id"] == SAMPLE_DOCS[1].id for d in docs)


# ---------------------------------------------------------------------------
# Property-graph CRUD (Stage 2)
# ---------------------------------------------------------------------------
def test_create_entity_validates_fields(client):
    # Invalid status value for the seed `task` type must be rejected.
    res = client.post(
        "/api/entities",
        json={
            "type_slug": "task",
            "canonical_name": "design review",
            "fields": {"status": "definitely_not_a_status", "priority": "medium"},
        },
    )
    assert res.status_code == 400


def test_create_entity_then_patch_field(client):
    res = client.post(
        "/api/entities",
        json={
            "type_slug": "task",
            "canonical_name": "ship docs",
            "fields": {"status": "pending", "priority": "high"},
        },
    )
    assert res.status_code == 201
    created = res.get_json()
    eid = created["id"]

    res = client.patch(
        f"/api/entities/{eid}", json={"fields": {"status": "in_progress", "priority": "high"}}
    )
    assert res.status_code == 200
    assert res.get_json()["fields"]["status"] == "in_progress"


def test_delete_user_entity(client):
    res = client.post(
        "/api/entities",
        json={"type_slug": "person", "canonical_name": "新人"},
    )
    eid = res.get_json()["id"]
    assert client.delete(f"/api/entities/{eid}").status_code == 204
    assert client.get(f"/api/entities/{eid}").status_code == 404


def test_create_relation_and_list(client):
    src = client.post(
        "/api/entities",
        json={"type_slug": "task", "canonical_name": "code review",
              "fields": {"status": "pending", "priority": "medium"}},
    ).get_json()
    tgt = client.post(
        "/api/entities",
        json={"type_slug": "person", "canonical_name": "Alice"},
    ).get_json()

    res = client.post(
        "/api/relations",
        json={
            "type_slug": "assigned_to",
            "source_entity_id": src["id"],
            "target_entity_id": tgt["id"],
        },
    )
    assert res.status_code == 201

    listed = client.get(f"/api/relations?source_entity_id={src['id']}").get_json()
    assert len(listed) == 1
    assert listed[0]["type_slug"] == "assigned_to"


def test_list_edges_returns_denormalised_rows(client):
    """/api/edges expands relations into rows with src/tgt canonical names so
    the frontend can render them without N+1 entity lookups."""
    res = client.get("/api/edges")
    assert res.status_code == 200
    rows = res.get_json()
    assert len(rows) == len(SAMPLE_RELATIONS)
    sample = rows[0]
    # Every row carries both endpoint names and the edge metadata.
    for key in (
        "edge_id", "edge_type", "edge_label",
        "src_id", "src_type", "src_name",
        "tgt_id", "tgt_type", "tgt_name",
        "edge_fields", "edge_created_ts",
    ):
        assert key in sample, f"missing {key} in /api/edges row"
    # Names are populated (the whole point of the view).
    assert all(r["src_name"] and r["tgt_name"] for r in rows)


def test_list_edges_filters_by_type_and_endpoint(client):
    # The seed contains exactly one belongs_to edge: 山田花子 → 株式会社サンプル.
    res = client.get("/api/edges?type_slug=belongs_to").get_json()
    assert len(res) == 1
    assert res[0]["edge_type"] == "belongs_to"
    assert res[0]["src_name"] == "山田花子"
    assert res[0]["tgt_name"] == "株式会社サンプル"

    # Same edge retrievable by src_id filter.
    src_id = res[0]["src_id"]
    by_src = client.get(f"/api/edges?src_id={src_id}").get_json()
    assert len(by_src) >= 1
    assert all(r["src_id"] == src_id for r in by_src)


def test_list_edges_substring_search(client):
    """q matches against src_name OR tgt_name."""
    res = client.get("/api/edges?q=山田").get_json()
    assert len(res) >= 1
    assert all(
        "山田" in (r["src_name"] or "") or "山田" in (r["tgt_name"] or "")
        for r in res
    )


def test_ask_endpoint(client, fake_llm):
    # The agent issues a single search_documents tool call, then returns text.
    fake_llm.chat_responses.extend(
        [
            StubChatCompletion.tool(
                calls=[
                    (
                        "call-1",
                        "search_documents",
                        json.dumps({"query": "解約条項", "top_k": 3}),
                    )
                ]
            ),
            StubChatCompletion.text("解約は30日前の通知が必要です。"),
        ]
    )

    res = client.post("/api/ask", json={"question": "解約条項は?"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["answer"].startswith("解約")
    assert isinstance(body["citations"], list)
    assert isinstance(body["trace"], list) and len(body["trace"]) == 1
    assert body["iterations"] >= 1
    assert body["error"] is None


def test_ask_empty_question(client):
    res = client.post("/api/ask", json={"question": "  "})
    assert res.status_code == 400


def test_ask_response_propagates_rewritten_question_in_trace(
    client, seeded_db, fake_llm
):
    """The retry path's canonicalised question must reach the JSON
    response so the Ask UI can render the rewrite callout independently
    of the (truncated) ``result_preview``."""
    from docdb.ingestion import DocumentStore
    from docdb.models import Entity, entity_id_for
    from docdb.schema.connection import connection
    from docdb.search.text2sql import GeneratedSQL

    vec = [0.0] * 1024
    vec[0] = 1.0
    alice = Entity(
        id=entity_id_for("person", "Alice Smith"),
        type_slug="person",
        canonical_name="Alice Smith",
        aliases=["Alice S."],
    )
    with connection(seeded_db.db_path) as conn:
        DocumentStore(conn).upsert_entity(alice, embedding=vec)

    question = "Alice S. の件"
    rewritten = "Alice Smith の件"

    # Override embed so the question maps to alice's vector; alias
    # candidate then canonicalises the surface form.
    fake_llm.embed = lambda texts: [
        vec if t == question else [0.0] * 1024 for t in texts
    ]
    fake_llm.extract_responses.extend(
        [
            GeneratedSQL(sql="SELECT bogus FROM entities"),  # primary errors
            GeneratedSQL(sql=f"SELECT id FROM entities WHERE id='{alice.id}'"),
        ]
    )
    fake_llm.chat_responses.extend(
        [
            StubChatCompletion.tool(
                calls=[("c1", "text_to_sql", json.dumps({"question": question}))]
            ),
            StubChatCompletion.text("Alice Smith のレコードを返しました"),
        ]
    )

    res = client.post("/api/ask", json={"question": question})
    assert res.status_code == 200
    body = res.get_json()
    assert len(body["trace"]) == 1
    step = body["trace"][0]
    assert step["tool"] == "text_to_sql"
    assert step["rewritten_question"] == rewritten


def test_ingest_file(client, tmp_path: Path, fake_llm):
    # Pre-script extraction returns the header only; entity / relation writes
    # are intentionally disabled in Stage 2.
    from docdb.models import ExtractionResult

    fake_llm.extract_responses.append(
        ExtractionResult(doc_type="memo", title="新規メモ", summary="テスト", language="ja")
    )

    src = tmp_path / "note.md"
    src.write_text("# 新規メモ\n本文です。", encoding="utf-8")
    res = client.post("/api/ingest", json={"path": str(src)})
    assert res.status_code == 200
    body = res.get_json()
    assert body["summary"]["created"] == 1
    assert body["reports"][0]["status"] == "created"
