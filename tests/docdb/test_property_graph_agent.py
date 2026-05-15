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
from docdb.search.text2sql import ALLOWED_TABLES, GeneratedSQL
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
    """The canonical SQL-first flow under AGENT_SYSTEM:
    describe_schema → text_to_sql(WHERE type_slug='task' ...)."""
    task_id = _seed_task(conn)

    fake = FakeLLM(
        chat_responses=[
            # Round 1: ask what entity types exist (so the agent knows the
            # right type_slug for its WHERE clause).
            StubChatCompletion.tool(
                [("c1", "describe_schema", json.dumps({"kind": "entities"}))]
            ),
            # Round 2: SQL the entities table directly.
            StubChatCompletion.tool(
                [
                    (
                        "c2",
                        "text_to_sql",
                        json.dumps({"question": "未完了の task entity を出して"}),
                    )
                ]
            ),
            StubChatCompletion.text(
                "未完了タスクは 'ship docs' (priority=high)。"
            ),
        ],
        extract_responses=[
            GeneratedSQL(
                sql=(
                    "SELECT canonical_name FROM entities "
                    "WHERE type_slug='task'"
                ),
                reasoning="list every entity of type task",
            ),
        ],
    )
    toolbox = Toolbox(conn, fake)
    agent = SearchAgent(toolbox=toolbox, llm=fake, max_iters=4)

    result = agent.run("未完了のタスクは?")

    assert result.succeeded
    assert "ship docs" in result.answer
    # Two tools were invoked in order, SQL-first.
    tools = [t.tool for t in result.trace]
    assert tools == ["describe_schema", "text_to_sql"]
    # The describe_schema result mentions the task slug.
    assert "task" in result.trace[0].result_preview
    # The SQL ran and returned the seeded entity.
    assert "ship docs" in result.trace[1].result_preview


def test_agent_can_traverse_relations_via_text_to_sql(conn) -> None:
    """Relation traversal is now expressed as a SQL JOIN through text_to_sql,
    not a dedicated search_relations tool."""
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
                        "text_to_sql",
                        json.dumps({"question": "design タスクの担当者は?"}),
                    )
                ]
            ),
            StubChatCompletion.text("design は Alice に割り当てられています。"),
        ],
        extract_responses=[
            GeneratedSQL(
                sql=(
                    "SELECT e.canonical_name AS assignee "
                    "FROM relations AS r "
                    "JOIN entities AS e ON e.id = r.target_entity_id "
                    f"WHERE r.source_entity_id = '{task.id}' "
                    "AND r.type_slug = 'assigned_to'"
                ),
                reasoning="join relations to entities to resolve assignee name",
            ),
        ],
    )
    agent = SearchAgent(toolbox=Toolbox(conn, fake), llm=fake)
    result = agent.run("design タスクの担当は?")

    assert result.succeeded
    assert "Alice" in result.answer
    assert result.trace[0].tool == "text_to_sql"
    assert "Alice" in result.trace[0].result_preview


# ---------------------------------------------------------------------------
# AGENT_SYSTEM coherence
# ---------------------------------------------------------------------------
def test_agent_system_promotes_text_to_sql_as_default() -> None:
    """Under the SQL-first policy, AGENT_SYSTEM must teach the agent that
    `text_to_sql` is the primary path for structured queries. The Stage-2
    removal of the entity/relation shortcut tools is also enforced here:
    the prompt must NOT advertise `search_entities` / `search_relations` /
    `get_entity_documents` since they no longer exist on the toolbox."""
    assert "text_to_sql" in AGENT_SYSTEM
    # text_to_sql is named in step 1 — i.e. before search_documents.
    assert AGENT_SYSTEM.index("text_to_sql") < AGENT_SYSTEM.index("search_documents")
    assert "describe_schema" in AGENT_SYSTEM
    # Stage 2 removed these tools from the toolbox; they must also be absent
    # from the prompt so the agent does not hallucinate calls to them.
    assert "search_entities" not in AGENT_SYSTEM
    assert "search_relations" not in AGENT_SYSTEM
    assert "get_entity_documents" not in AGENT_SYSTEM
    # And the prompt must NOT mention older removed aliases either.
    assert "list_todos" not in AGENT_SYSTEM
    assert "list_entity_types" not in AGENT_SYSTEM
    assert "list_relation_types" not in AGENT_SYSTEM
    assert "list_doc_types" not in AGENT_SYSTEM


def test_toolbox_specs_match_agent_system_advertised_tools(conn) -> None:
    toolbox = Toolbox(conn, FakeLLM())
    declared = {spec.name for spec in toolbox.specs()}
    assert {
        "describe_schema",
        "text_to_sql",
        "search_documents",
        "get_document",
        "find_similar",
        "execute_readonly_sql",
    }.issubset(declared)
    # Stage 2: removed entity/relation shortcut tools — text_to_sql covers
    # those query patterns now.
    assert "search_entities" not in declared
    assert "search_relations" not in declared
    assert "get_entity_documents" not in declared
    # Older removed Stage-2 / Phase-1 aliases stay gone.
    assert "list_todos" not in declared
    assert "list_entity_types" not in declared
    assert "list_relation_types" not in declared
    assert "list_doc_types" not in declared


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
