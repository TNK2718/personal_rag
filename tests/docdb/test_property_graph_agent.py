"""Property-graph aware agent + cross-module consistency tests (Stage 5).

These tests are guard-rails: they ensure that after the type registry
came online, the agent's tools, system prompt, and the text2sql guard
agree on what the schema looks like. They also exercise the canonical
"discover the registry first, then filter entities" flow that the new
AGENT_SYSTEM instructions describe.
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from docdb.agent.loop import SearchAgent
from docdb.agent.toolbox import Toolbox
from docdb.ingestion.store import DocumentStore
from docdb.llm.fake import FakeLLM, StubChatCompletion
from docdb.llm.prompts import (
    AGENT_PROMPT_MAX_BYTES,
    AGENT_SYSTEM,
    AGENT_SYSTEM_BASE,
    DOCDB_SCHEMA_SUMMARY,
    build_agent_system_prompt,
)
from docdb.models import Entity, entity_id_for
from docdb.search.text2sql import ALLOWED_TABLES
from docdb.typing.registry import (
    EntityTypeDef,
    RelationTypeDef,
    list_entity_types,
    list_relation_types,
)


# ---------------------------------------------------------------------------
# Agent flow: registry discovery → filtered entity search
# ---------------------------------------------------------------------------
def _seed_task(conn: sqlite3.Connection) -> str:
    store = DocumentStore(conn)
    task = Entity(
        id=entity_id_for("task", "ship docs"),
        type_slug="task",
        canonical_name="ship docs",
        fields={"status": "pending", "priority": "high"},
    )
    store.upsert_entity(task)
    return task.id


def test_agent_can_discover_types_then_filter_entities(conn) -> None:
    """The canonical flow described in AGENT_SYSTEM:
    list_entity_types → search_entities(type_slug=...)."""
    task_id = _seed_task(conn)

    fake = FakeLLM(
        chat_responses=[
            # Round 1: ask what types exist.
            StubChatCompletion.tool([("c1", "list_entity_types", "{}")]),
            # Round 2: now that we know `task` is registered, search for pending ones.
            StubChatCompletion.tool(
                [
                    (
                        "c2",
                        "search_entities",
                        json.dumps({"name_partial": "ship", "type_slug": "task"}),
                    )
                ]
            ),
            StubChatCompletion.text(
                "未完了タスクは 'ship docs' (priority=high)。"
            ),
        ]
    )
    toolbox = Toolbox(conn, fake)
    agent = SearchAgent(toolbox=toolbox, llm=fake, max_iters=4)

    result = agent.run("未完了のタスクは?")

    assert result.succeeded
    assert "ship docs" in result.answer
    # Two tools were invoked in order.
    tools = [t.tool for t in result.trace]
    assert tools == ["list_entity_types", "search_entities"]
    # The list_entity_types result mentions the task slug.
    assert "task" in result.trace[0].result_preview


def test_agent_can_search_relations(conn) -> None:
    """search_relations is reachable and returns the relation rows."""
    store = DocumentStore(conn)
    task = Entity(
        id=entity_id_for("task", "design"),
        type_slug="task",
        canonical_name="design",
        fields={"status": "pending", "priority": "medium"},
    )
    person = Entity(
        id=entity_id_for("person", "Alice"),
        type_slug="person",
        canonical_name="Alice",
    )
    store.upsert_entity(task)
    store.upsert_entity(person)

    from docdb.models import Relation, relation_id_for

    rel = Relation(
        id=relation_id_for("assigned_to", task.id, person.id),
        type_slug="assigned_to",
        source_entity_id=task.id,
        target_entity_id=person.id,
    )
    store.upsert_relation(rel)

    fake = FakeLLM(
        chat_responses=[
            StubChatCompletion.tool(
                [
                    (
                        "c1",
                        "search_relations",
                        json.dumps({"source_entity_id": task.id}),
                    )
                ]
            ),
            StubChatCompletion.text("design は Alice に割り当てられています。"),
        ]
    )
    agent = SearchAgent(toolbox=Toolbox(conn, fake), llm=fake)
    result = agent.run("design タスクの担当は?")

    assert result.succeeded
    assert "Alice" in result.answer
    assert result.trace[0].tool == "search_relations"


# ---------------------------------------------------------------------------
# AGENT_SYSTEM coherence
# ---------------------------------------------------------------------------
def test_agent_system_lists_property_graph_tools() -> None:
    """A regression in AGENT_SYSTEM that forgot to teach the agent about the
    new tools would silently degrade behaviour on property-graph questions."""
    assert "list_entity_types" in AGENT_SYSTEM
    assert "search_entities" in AGENT_SYSTEM
    assert "search_relations" in AGENT_SYSTEM
    assert "text_to_sql" in AGENT_SYSTEM
    # And it must NOT mention the removed Stage-2 ``list_todos`` tool.
    assert "list_todos" not in AGENT_SYSTEM


def test_toolbox_specs_match_agent_system_advertised_tools(conn) -> None:
    toolbox = Toolbox(conn, FakeLLM())
    declared = {spec.name for spec in toolbox.specs()}
    assert {
        "list_entity_types",
        "search_entities",
        "search_relations",
        "text_to_sql",
    }.issubset(declared)
    assert "list_todos" not in declared


# ---------------------------------------------------------------------------
# build_agent_system_prompt: dynamic type catalogue
# ---------------------------------------------------------------------------
class TestBuildAgentSystemPrompt:
    def test_default_cap_is_20kb(self) -> None:
        assert AGENT_PROMPT_MAX_BYTES == 20_000

    def test_agent_system_alias_is_back_compat(self) -> None:
        # External callers import AGENT_SYSTEM directly. It must stay equal to
        # the base string after the rename.
        assert AGENT_SYSTEM == AGENT_SYSTEM_BASE

    def test_empty_registry_returns_base_only(self) -> None:
        prompt = build_agent_system_prompt([], [])
        # The base instructions are preserved verbatim.
        assert AGENT_SYSTEM_BASE in prompt
        # Catalogue headers only show up when types exist.
        assert "登録済みの entity 型" not in prompt
        assert "登録済みの relation 型" not in prompt

    def test_catalogue_lists_entity_slug_and_label(self, conn: sqlite3.Connection) -> None:
        entity_types = list_entity_types(conn)
        prompt = build_agent_system_prompt(entity_types, [])
        assert "登録済みの entity 型" in prompt
        for t in entity_types:
            assert f"`{t.slug}`" in prompt
            assert t.label in prompt

    def test_catalogue_omits_field_details(self, conn: sqlite3.Connection) -> None:
        # The agent prompt is intentionally lean: no fields_schema dump.
        task = next(t for t in list_entity_types(conn) if t.slug == "task")
        prompt = build_agent_system_prompt([task], [])
        # task has 'status' field on the extraction side, but the agent prompt
        # should not enumerate per-field specs (keeps the prompt small).
        assert "status (enum" not in prompt
        assert "due_date (date" not in prompt

    def test_relation_catalogue_shows_endpoints(self, conn: sqlite3.Connection) -> None:
        entity_types = list_entity_types(conn)
        relation_types = list_relation_types(conn)
        if not relation_types:
            pytest.skip("no relation types seeded in this fixture")
        prompt = build_agent_system_prompt(entity_types, relation_types)
        for t in relation_types:
            assert f"`{t.slug}`" in prompt

    def test_relations_skipped_when_no_entity_types(self) -> None:
        rel = RelationTypeDef.model_validate(
            {"slug": "assigned_to", "label": "担当", "fields_schema": []}
        )
        prompt = build_agent_system_prompt([], [rel])
        # Without any entity types the relation catalogue is irrelevant noise.
        assert "assigned_to" not in prompt

    def test_byte_cap_truncates_rather_than_crashing(self, conn: sqlite3.Connection) -> None:
        entity_types = list_entity_types(conn)
        relation_types = list_relation_types(conn)
        prompt = build_agent_system_prompt(
            entity_types, relation_types, max_bytes=2_500
        )
        assert len(prompt.encode("utf-8")) <= 2_700
        assert "省略" in prompt


# ---------------------------------------------------------------------------
# Cross-module schema coherence
# ---------------------------------------------------------------------------
def test_every_allowed_table_actually_exists_after_init_db(conn) -> None:
    """text2sql.ALLOWED_TABLES must not name a table the schema doesn't ship.

    Otherwise an LLM-emitted SELECT lands on a missing-table error rather than
    being caught by the guard.
    """
    actual: set[str] = set()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    for r in rows:
        actual.add(r["name"])
    # Virtual tables (FTS5, vec0) need to show up here as well.
    missing = ALLOWED_TABLES - actual
    assert not missing, f"ALLOWED_TABLES references absent tables: {missing}"


def test_schema_summary_documents_every_allowed_table() -> None:
    """The text2sql LLM prompt must describe every table the guard allows so
    the model knows the columns it can SELECT from."""
    missing: list[str] = []
    for tbl in ALLOWED_TABLES:
        # The summary is a SQL-comment block; we accept either bare 'tbl(' or
        # a line that mentions the name (e.g. for FTS join hints).
        if not re.search(rf"\b{re.escape(tbl)}\b", DOCDB_SCHEMA_SUMMARY):
            missing.append(tbl)
    assert not missing, f"DOCDB_SCHEMA_SUMMARY omits: {missing}"
