"""Text2SQL contract tests.

The point of this layer is to be safe and well-behaved when the LLM
isn't perfect. Tests cover:
    * happy path — LLM returns a safe SELECT, sql_guard accepts it,
      rows come back as plain dicts;
    * sql_guard rejection becomes Text2SQLResult.error (not a raise);
    * SQLite runtime errors become Text2SQLResult.error;
    * LLM exceptions become Text2SQLResult.error;
    * generated SQL without a LIMIT gains one (via sql_guard) before
      execution.
"""

from __future__ import annotations

import pytest

from docdb.llm.fake import FakeLLM
from docdb.search.text2sql import (
    ALLOWED_TABLES,
    GeneratedSQL,
    Text2SQLResult,
    run_text2sql,
)

from tests.docdb.fixtures import SAMPLE_DOCS


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_run_text2sql_returns_rows_for_a_safe_select(populated_db) -> None:
    fake = FakeLLM(
        extract_responses=[
            GeneratedSQL(
                sql="SELECT id, title FROM documents WHERE doc_type='memo'",
                reasoning="memo フィルタ",
            )
        ]
    )

    result = run_text2sql(populated_db, "メモを全部見せて", fake)

    assert result.succeeded, result.error
    ids = {row["id"] for row in result.rows}
    assert ids == {SAMPLE_DOCS[0].id, SAMPLE_DOCS[4].id}
    assert result.sql.startswith("SELECT")
    assert result.reasoning == "memo フィルタ"


def test_run_text2sql_injects_limit_when_missing(populated_db) -> None:
    fake = FakeLLM(
        extract_responses=[GeneratedSQL(sql="SELECT id FROM documents")]
    )
    result = run_text2sql(populated_db, "全件", fake, max_limit=2)

    assert result.succeeded
    assert "LIMIT 2" in result.validated_sql
    assert len(result.rows) <= 2


def test_run_text2sql_preserves_existing_limit(populated_db) -> None:
    fake = FakeLLM(
        extract_responses=[GeneratedSQL(sql="SELECT id FROM documents LIMIT 1")]
    )
    result = run_text2sql(populated_db, "1 件だけ", fake, max_limit=50)
    assert "LIMIT 1" in result.validated_sql


def test_fts_query_against_documents_fts_works(populated_db) -> None:
    fake = FakeLLM(
        extract_responses=[
            GeneratedSQL(
                sql=(
                    "SELECT d.id, d.title FROM documents_fts "
                    "JOIN documents d ON d.rowid = documents_fts.rowid "
                    "WHERE documents_fts MATCH '解約条項'"
                )
            )
        ]
    )
    result = run_text2sql(populated_db, "解約条項に触れている文書を出して", fake)
    assert result.succeeded
    assert any(row["id"] == SAMPLE_DOCS[0].id for row in result.rows)


# ---------------------------------------------------------------------------
# Safety: sql_guard rejections become errors
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_sql, expected_substr",
    [
        ("DROP TABLE documents", "only SELECT"),
        ("DELETE FROM documents WHERE id='x'", "only SELECT"),
        ("SELECT * FROM sqlite_master", "disallowed table"),
        (
            "SELECT id FROM documents; DROP TABLE documents;",
            "multiple statements",
        ),
        ("", "empty SQL"),
    ],
)
def test_unsafe_sql_is_caught_and_reported(populated_db, bad_sql, expected_substr) -> None:
    fake = FakeLLM(extract_responses=[GeneratedSQL(sql=bad_sql or "INVALID")])
    # The Pydantic min_length=1 means we can't ship "" through the LLM
    # path; switch to a bypass when the test wants empty SQL.
    if not bad_sql:
        fake.extract_responses[0] = GeneratedSQL.model_construct(sql="")
    result = run_text2sql(populated_db, "?", fake)
    assert not result.succeeded
    assert "unsafe sql" in result.error
    assert expected_substr in result.error


# ---------------------------------------------------------------------------
# Runtime errors
# ---------------------------------------------------------------------------
def test_sqlite_runtime_error_becomes_result_error(populated_db) -> None:
    # Column does not exist; sql_guard cannot catch this because it
    # only checks structure, not semantics. The runtime error must
    # surface on the result instead of raising.
    fake = FakeLLM(
        extract_responses=[GeneratedSQL(sql="SELECT nonexistent FROM documents")]
    )
    result = run_text2sql(populated_db, "?", fake)
    assert not result.succeeded
    assert "sqlite error" in result.error


def test_llm_failure_becomes_result_error(populated_db) -> None:
    class _ExplodingLLM(FakeLLM):
        def extract(self, text, schema):
            raise RuntimeError("ollama down")

    result = run_text2sql(populated_db, "?", _ExplodingLLM())
    assert not result.succeeded
    assert "llm error" in result.error
    assert "ollama down" in result.error


# ---------------------------------------------------------------------------
# Configurability
# ---------------------------------------------------------------------------
def test_max_rows_caps_returned_rows(populated_db) -> None:
    fake = FakeLLM(
        extract_responses=[GeneratedSQL(sql="SELECT id FROM documents")]
    )
    result = run_text2sql(populated_db, "全件", fake, max_limit=100, max_rows=1)
    assert len(result.rows) == 1


def test_allowed_tables_can_be_narrowed(populated_db) -> None:
    fake = FakeLLM(
        extract_responses=[GeneratedSQL(sql="SELECT id FROM entities")]
    )
    result = run_text2sql(
        populated_db, "?", fake, allowed_tables={"documents"}
    )
    assert not result.succeeded
    assert "disallowed table: entities" in result.error


# ---------------------------------------------------------------------------
# Sanity: the default allowlist covers every table the schema defines
# ---------------------------------------------------------------------------
def test_allowed_tables_default_matches_schema() -> None:
    expected = {
        "documents",
        "documents_fts",
        "entities",
        "entity_types",
        "entities_search",
        "entities_fts",
        "relations",
        "relation_types",
        "tags",
        "document_entities",
        "document_tags",
        "document_relations",
        "document_relation_mentions",
    }
    assert ALLOWED_TABLES == expected
