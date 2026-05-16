"""SearchAgent (tool-calling loop) tests.

These exercise the full loop with a scripted FakeLLM. The toolbox is
real and runs against ``populated_db`` so we observe the end-to-end
trip: tool dispatch, citation harvesting, message-history shape, and
the three terminating conditions (final answer, max_iters, llm error).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from docdb.agent.loop import SearchAgent
from docdb.agent.toolbox import Toolbox
from docdb.ingestion.store import DocumentStore
from docdb.llm.fake import FakeLLM, StubChatCompletion, _hash_to_unit_vector
from docdb.models import Entity, entity_id_for
from docdb.search.text2sql import GeneratedSQL

from tests.docdb.fixtures import SAMPLE_DOCS


@dataclass
class _KeyedEmbedLLM(FakeLLM):
    """FakeLLM with text→vector overrides for deterministic KNN tests."""

    embed_overrides: dict[str, list[float]] = field(default_factory=dict)

    def embed(self, texts):
        self.calls_embed.append(list(texts))
        return [
            self.embed_overrides[t]
            if t in self.embed_overrides
            else _hash_to_unit_vector(t, self.embed_dim)
            for t in texts
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _agent(populated_db, fake: FakeLLM, *, max_iters: int = 6) -> SearchAgent:
    return SearchAgent(
        toolbox=Toolbox(populated_db, fake),
        llm=fake,
        max_iters=max_iters,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_agent_runs_tools_then_returns_final_answer(populated_db) -> None:
    cancel_id = SAMPLE_DOCS[0].id
    fake = FakeLLM(
        chat_responses=[
            StubChatCompletion.tool(
                [("c1", "search_documents", json.dumps({"query": "解約条項"}))]
            ),
            StubChatCompletion.tool(
                [
                    (
                        "c2",
                        "get_document",
                        json.dumps({"document_id": cancel_id}),
                    )
                ]
            ),
            StubChatCompletion.text(
                f"解約条項は 30 日前の通知が必要です [doc:{cancel_id}]"
            ),
        ]
    )
    agent = _agent(populated_db, fake)

    result = agent.run("解約条項について教えて")

    assert result.succeeded
    assert result.answer.startswith("解約条項は")
    assert result.iterations == 3
    assert not result.exhausted

    # Two tool invocations recorded.
    assert [t.tool for t in result.trace] == ["search_documents", "get_document"]

    # Citation auto-harvested from the tool results. search_documents now
    # defaults to hybrid, so the vec arm can introduce additional candidates;
    # we only assert the focal document is among them.
    assert cancel_id in {c.document_id for c in result.citations}


def test_agent_handles_multiple_tool_calls_in_one_turn(populated_db) -> None:
    spec_id = SAMPLE_DOCS[3].id
    meeting_id = SAMPLE_DOCS[1].id
    fake = FakeLLM(
        chat_responses=[
            StubChatCompletion.tool(
                [
                    ("c1", "get_document", json.dumps({"document_id": spec_id})),
                    ("c2", "get_document", json.dumps({"document_id": meeting_id})),
                ]
            ),
            StubChatCompletion.text("両方読みました"),
        ]
    )
    agent = _agent(populated_db, fake)
    result = agent.run("仕様と議事録両方見せて")

    assert result.succeeded
    assert {c.document_id for c in result.citations} == {spec_id, meeting_id}
    # Both calls reside on iteration 1.
    assert {t.iteration for t in result.trace} == {1}


# ---------------------------------------------------------------------------
# Citation harvesting from nested shapes
# ---------------------------------------------------------------------------
def test_citations_collected_from_search_documents_results(populated_db) -> None:
    fake = FakeLLM(
        chat_responses=[
            StubChatCompletion.tool(
                [("c1", "search_documents", json.dumps({"query": "プロジェクト"}))]
            ),
            StubChatCompletion.text("見つかった件あり"),
        ]
    )
    agent = _agent(populated_db, fake)
    result = agent.run("プロジェクトAは?")
    assert SAMPLE_DOCS[1].id in {c.document_id for c in result.citations}


def test_citations_dedup_across_iterations(populated_db) -> None:
    cancel_id = SAMPLE_DOCS[0].id
    fake = FakeLLM(
        chat_responses=[
            StubChatCompletion.tool(
                [("c1", "search_documents", json.dumps({"query": "解約条項"}))]
            ),
            StubChatCompletion.tool(
                [("c2", "search_documents", json.dumps({"query": "解約条項"}))]
            ),
            StubChatCompletion.text("done"),
        ]
    )
    agent = _agent(populated_db, fake)
    result = agent.run("?")
    # Same document_id was returned twice but appears once in citations.
    assert [c.document_id for c in result.citations].count(cancel_id) == 1


# ---------------------------------------------------------------------------
# Termination conditions
# ---------------------------------------------------------------------------
def test_max_iters_marks_result_exhausted(populated_db) -> None:
    tool_responses = [
        StubChatCompletion.tool(
            [(f"c{i}", "search_documents", json.dumps({"query": "メモ書き"}))]
        )
        for i in range(10)
    ]
    fake = FakeLLM(chat_responses=tool_responses)
    agent = _agent(populated_db, fake, max_iters=3)

    result = agent.run("無限ループ?")
    assert result.exhausted
    assert result.iterations == 3
    assert result.answer == ""


def test_llm_error_aborts_with_error(populated_db) -> None:
    class _ExplodingLLM(FakeLLM):
        def chat_with_tools(self, *args, **kwargs):
            raise RuntimeError("ollama unreachable")

    fake = _ExplodingLLM()
    agent = SearchAgent(toolbox=Toolbox(populated_db, fake), llm=fake)

    result = agent.run("?")
    assert not result.succeeded
    assert "ollama unreachable" in result.error


def test_agent_trace_carries_rewritten_question_from_text_to_sql(
    populated_db,
) -> None:
    """When ``text_to_sql`` retries via canonicalisation, the rewrite must
    propagate to the trace entry so the UI can surface it independently
    of the truncated ``result_preview``."""
    vec = [0.0] * 1024
    vec[0] = 1.0
    alice = Entity(
        id=entity_id_for("person", "Alice Smith"),
        type_slug="person",
        canonical_name="Alice Smith",
        aliases=["Alice S."],
    )
    DocumentStore(populated_db).upsert_entity(alice, embedding=vec)

    question = "Alice S. の件"
    rewritten = "Alice Smith の件"

    fake = _KeyedEmbedLLM(
        embed_overrides={question: vec},
        extract_responses=[
            # Primary attempt: SQLite errors on bogus column → triggers retry.
            GeneratedSQL(sql="SELECT bogus FROM entities"),
            # Retry on the canonicalised question succeeds.
            GeneratedSQL(sql=f"SELECT id FROM entities WHERE id='{alice.id}'"),
        ],
        chat_responses=[
            StubChatCompletion.tool(
                [("c1", "text_to_sql", json.dumps({"question": question}))]
            ),
            StubChatCompletion.text("Alice Smith に関するレコードを見つけました"),
        ],
    )
    agent = _agent(populated_db, fake)

    result = agent.run(question)

    assert result.succeeded
    assert [t.tool for t in result.trace] == ["text_to_sql"]
    assert result.trace[0].rewritten_question == rewritten


def test_agent_trace_rewritten_question_is_none_on_happy_path(populated_db) -> None:
    """Tools that never set ``rewritten_question`` produce ``None`` traces."""
    fake = FakeLLM(
        chat_responses=[
            StubChatCompletion.tool(
                [("c1", "search_documents", json.dumps({"query": "解約条項"}))]
            ),
            StubChatCompletion.text("done"),
        ]
    )
    agent = _agent(populated_db, fake)
    result = agent.run("?")
    assert result.trace[0].rewritten_question is None


def test_tool_error_is_recorded_but_loop_continues(populated_db) -> None:
    fake = FakeLLM(
        chat_responses=[
            StubChatCompletion.tool(
                [("c1", "nonexistent_tool", "{}")]
            ),
            StubChatCompletion.text("諦めて答えます"),
        ]
    )
    agent = _agent(populated_db, fake)

    result = agent.run("?")
    assert result.succeeded
    # The error was recorded but the loop pressed on.
    assert result.trace[0].error is not None
    assert "unknown tool" in result.trace[0].error


# ---------------------------------------------------------------------------
# Message-history shape
# ---------------------------------------------------------------------------
def test_assistant_and_tool_messages_are_appended_in_order(populated_db) -> None:
    fake = FakeLLM(
        chat_responses=[
            StubChatCompletion.tool(
                [("c1", "describe_schema", json.dumps({"kind": "doc_types"}))]
            ),
            StubChatCompletion.text("ok"),
        ]
    )
    agent = _agent(populated_db, fake)
    agent.run("doc_type 集計を出して")

    # The LLM was called twice; on the second call it must have seen
    # the assistant + tool messages from round 1 in the history.
    second_call_messages = fake.calls_chat[1]["messages"]
    roles = [m["role"] for m in second_call_messages]
    # system, user, assistant, tool, ... (the second LLM call sees four).
    assert roles[0] == "system"
    assert roles[1] == "user"
    assert roles[2] == "assistant"
    assert roles[3] == "tool"

    # The tool message carries the JSON output from describe_schema.
    tool_payload = json.loads(second_call_messages[3]["content"])
    assert isinstance(tool_payload, dict)
    assert all("doc_type" in entry for entry in tool_payload["doc_types"])
