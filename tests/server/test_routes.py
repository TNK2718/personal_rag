from __future__ import annotations

import json
from pathlib import Path

import pytest

from docdb.llm.fake import StubChatCompletion, StubToolCall
from tests.docdb.fixtures import SAMPLE_DOCS, SAMPLE_ENTITIES, SAMPLE_TODOS


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
    assert body["todos_total"] == len(SAMPLE_TODOS)
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
    assert isinstance(body["todos"], list)
    assert isinstance(body["entities"], list)
    assert any(e["canonical_name"] == "プロジェクトA" for e in body["entities"])


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
    ent_id = SAMPLE_ENTITIES[1].id  # プロジェクトA
    res = client.get(f"/api/entities/{ent_id}/documents")
    assert res.status_code == 200
    docs = res.get_json()
    assert any(d["id"] == SAMPLE_DOCS[1].id for d in docs)


def test_list_todos(client):
    res = client.get("/api/todos")
    assert res.status_code == 200
    items = res.get_json()
    assert len(items) == len(SAMPLE_TODOS)
    assert items[0]["status"] in {"pending", "in_progress", "completed", "cancelled"}


def test_patch_todo_status(client):
    todo_id = SAMPLE_TODOS[0].id
    res = client.patch(f"/api/todos/{todo_id}", json={"status": "in_progress"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "in_progress"

    after = client.get("/api/todos").get_json()
    assert any(t["id"] == todo_id and t["status"] == "in_progress" for t in after)


def test_patch_todo_invalid_status(client):
    res = client.patch(f"/api/todos/{SAMPLE_TODOS[0].id}", json={"status": "bogus"})
    assert res.status_code == 400


def test_patch_todo_not_found(client):
    res = client.patch("/api/todos/todo-doesnotexist", json={"status": "completed"})
    assert res.status_code == 404


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


def test_ingest_file(client, tmp_path: Path, fake_llm):
    # Pre-script extraction returns: no entities/tags/todos so the path is simple.
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
