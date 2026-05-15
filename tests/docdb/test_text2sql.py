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
from docdb.typing.field_spec import FieldSpecEnum, FieldSpecString
from docdb.typing.registry import (
    EntityTypeDef,
    RelationTypeDef,
    upsert_entity_type,
    upsert_relation_type,
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
# Dynamic type catalogue injection
# ---------------------------------------------------------------------------
# The text2sql prompt must surface the per-type ``fields_schema`` so the LLM
# can produce ``json_extract(fields, '$.<key>')`` filters. Without this, the
# model has to guess JSON key names from the user's natural language and
# tends to emit broken paths like ``fields->'$.'`` which SQLite happily
# evaluates to NULL — making bugs invisible.
def test_prompt_includes_entity_fields_schema(populated_db) -> None:
    # The builtin ``task`` type is seeded with status / priority / due_date.
    fake = FakeLLM(
        extract_responses=[GeneratedSQL(sql="SELECT id FROM entities")]
    )
    run_text2sql(populated_db, "未完了のタスクは?", fake)

    assert fake.calls_extract, "expected the LLM to be called"
    prompt_text, _schema = fake.calls_extract[-1]
    # The field names from task.fields_schema must appear.
    assert "status" in prompt_text
    assert "priority" in prompt_text
    assert "due_date" in prompt_text
    # The enum options must be surfaced so the LLM knows valid filter values.
    assert "pending" in prompt_text


def test_prompt_includes_relation_fields_schema(populated_db) -> None:
    # Register a relation_type with a field so we can verify it shows up.
    upsert_relation_type(
        populated_db,
        RelationTypeDef(
            slug="works_on",
            label="works on",
            source_type_slug="person",
            target_type_slug="org",
            fields=[
                FieldSpecString(
                    name="role", label="Role", type="string"
                ),
            ],
        ),
    )
    fake = FakeLLM(
        extract_responses=[GeneratedSQL(sql="SELECT id FROM relations")]
    )
    run_text2sql(populated_db, "誰がどこに所属?", fake)

    prompt_text, _schema = fake.calls_extract[-1]
    assert "works_on" in prompt_text
    assert "role" in prompt_text


def test_prompt_truncates_when_types_exceed_budget(populated_db) -> None:
    # Inflate the registry with many entity types, then squeeze the budget
    # so truncation has to kick in. The question section must survive.
    for i in range(40):
        upsert_entity_type(
            populated_db,
            EntityTypeDef(
                slug=f"custom_{i}",
                label=f"Custom Type {i}",
                description="x" * 400,  # padding to bloat each entry
                fields=[
                    FieldSpecEnum(
                        name="state",
                        label="State",
                        type="enum",
                        options=["a", "b", "c"],
                    )
                ],
            ),
        )
    fake = FakeLLM(
        extract_responses=[GeneratedSQL(sql="SELECT id FROM entities")]
    )
    question = "極端に小さいバジェットでも質問は落ちないはず"
    run_text2sql(populated_db, question, fake, max_prompt_bytes=4_000)

    prompt_text, _schema = fake.calls_extract[-1]
    assert len(prompt_text.encode("utf-8")) <= 4_000
    # The question and its header must always be present even after
    # truncation; only the type catalogue can be dropped.
    assert "# 質問" in prompt_text
    assert question in prompt_text


# ---------------------------------------------------------------------------
# KNN-fallback retry (run_text2sql)
# ---------------------------------------------------------------------------
# Resolution is lazy: the primary attempt sees the question verbatim with
# no embedding cost. Only when the primary errors out or returns zero rows
# does ``run_text2sql`` invoke ``resolve_mentions`` + canonicalise the
# surface forms and retry once. These tests pin that behaviour.
def _make_keyed_embed_llm():
    """``FakeLLM`` with a text→vector override map, defined inline so the
    tests don't need to import a fixture from the pipeline test file."""
    from dataclasses import dataclass, field

    from docdb.llm.fake import _hash_to_unit_vector

    @dataclass
    class _KeyedEmbedLLM(FakeLLM):
        embed_overrides: dict[str, list[float]] = field(default_factory=dict)

        def embed(self, texts):
            self.calls_embed.append(list(texts))
            return [
                self.embed_overrides[t]
                if t in self.embed_overrides
                else _hash_to_unit_vector(t, self.embed_dim)
                for t in texts
            ]

    return _KeyedEmbedLLM


def _seed_alice(conn):
    from docdb.ingestion.store import DocumentStore
    from docdb.models import Entity, entity_id_for

    vec = [0.0] * 1024
    vec[0] = 1.0
    alice = Entity(
        id=entity_id_for("person", "Alice Smith"),
        type_slug="person",
        canonical_name="Alice Smith",
        aliases=["Alice S."],
    )
    DocumentStore(conn).upsert_entity(alice, embedding=vec)
    return alice, vec


def test_run_text2sql_skips_resolution_on_primary_success(conn) -> None:
    """Primary returned rows → no retry, no embed call. Resolution is lazy."""
    alice, _vec = _seed_alice(conn)
    KeyedEmbed = _make_keyed_embed_llm()
    fake = KeyedEmbed(
        extract_responses=[
            GeneratedSQL(sql=f"SELECT id FROM entities WHERE id='{alice.id}'"),
        ],
    )

    result = run_text2sql(conn, "anything", fake)

    assert result.succeeded
    assert result.rewritten_question is None
    assert fake.calls_embed == []  # no embedding cost on the happy path
    assert len(fake.calls_extract) == 1  # primary only


def test_run_text2sql_retries_on_sql_error(conn) -> None:
    """Primary SQL errors → resolution fires, canonicalises, retry succeeds."""
    alice, vec = _seed_alice(conn)
    question = "Alice S. の件"  # surface form is the alias
    rewritten = "Alice Smith の件"

    KeyedEmbed = _make_keyed_embed_llm()
    fake = KeyedEmbed(
        embed_overrides={question: vec},
        extract_responses=[
            # Primary: SQLite runtime error (bad column).
            GeneratedSQL(sql="SELECT bogus FROM entities"),
            # Retry: clean SELECT against the canonicalised question.
            GeneratedSQL(sql=f"SELECT id FROM entities WHERE id='{alice.id}'"),
        ],
    )

    result = run_text2sql(conn, question, fake)

    assert result.succeeded, result.error
    assert result.rewritten_question == rewritten
    assert result.question == question  # original surfaces on .question
    assert len(fake.calls_extract) == 2  # primary + retry
    # The retry prompt got the canonicalised question.
    retry_prompt = fake.calls_extract[1][0]
    assert "Alice Smith の件" in retry_prompt


def test_run_text2sql_retries_on_zero_rows(conn) -> None:
    """Primary returns no rows → retry with canonicalised question."""
    alice, vec = _seed_alice(conn)
    question = "Alice S. のタスク"

    KeyedEmbed = _make_keyed_embed_llm()
    fake = KeyedEmbed(
        embed_overrides={question: vec},
        extract_responses=[
            # Primary: well-formed SQL but matches nothing.
            GeneratedSQL(sql="SELECT id FROM entities WHERE canonical_name='Alice S.'"),
            # Retry: canonicalised, hits the alice row.
            GeneratedSQL(sql=f"SELECT id FROM entities WHERE id='{alice.id}'"),
        ],
    )

    result = run_text2sql(conn, question, fake)

    assert result.succeeded
    assert result.rewritten_question == "Alice Smith のタスク"
    assert {row["id"] for row in result.rows} == {alice.id}


def test_run_text2sql_no_retry_when_resolution_disabled(conn) -> None:
    """``resolution_enabled=False`` → primary error, no resolve, no retry."""
    _seed_alice(conn)
    fake = FakeLLM(
        extract_responses=[GeneratedSQL(sql="SELECT bogus FROM entities")],
    )

    result = run_text2sql(conn, "Alice S. の件", fake, resolution_enabled=False)

    assert result.error is not None
    assert "sqlite error" in result.error
    assert fake.calls_embed == []
    assert len(fake.calls_extract) == 1


def test_run_text2sql_no_retry_when_no_candidates_found(conn) -> None:
    """``resolve_mentions`` returns empty → no retry, primary error stands."""
    # No entities seeded; KNN against empty entities_vec returns nothing.
    fake = FakeLLM(
        extract_responses=[GeneratedSQL(sql="SELECT bogus FROM entities")],
    )

    result = run_text2sql(conn, "Alice S. の件", fake)

    assert result.error is not None
    # Embed was attempted (resolve_mentions ran) but no extract retry happened.
    assert len(fake.calls_extract) == 1


def test_run_text2sql_keeps_primary_when_retry_is_no_improvement(conn) -> None:
    """If the retry also errors and primary had rows-y partial state, primary
    wins. (Symmetric guard.) Concretely: primary returns 0 rows, retry also
    errors → ``_is_better`` rejects the retry."""
    alice, vec = _seed_alice(conn)
    question = "Alice S. のタスク"

    KeyedEmbed = _make_keyed_embed_llm()
    fake = KeyedEmbed(
        embed_overrides={question: vec},
        extract_responses=[
            # Primary: succeeds, 0 rows (triggers retry).
            GeneratedSQL(sql="SELECT id FROM entities WHERE canonical_name='Alice S.'"),
            # Retry: errors out.
            GeneratedSQL(sql="SELECT bogus FROM entities"),
        ],
    )

    result = run_text2sql(conn, question, fake)

    # Retry failed; primary (succeeded, empty) is what's returned.
    assert result.succeeded
    assert result.rows == []
    assert result.rewritten_question is None
    assert result.question == question


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
