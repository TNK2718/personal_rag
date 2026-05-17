"""Level-2 Text2SQL.

The LLM proposes a SELECT for a user question; sql_guard validates it;
we then execute it as a bound query. Errors do not raise — they land
on the returned ``Text2SQLResult`` so a higher layer (the agent) can
report the failure and try again with a different approach.

Resolution shape: the primary attempt sees the question verbatim, with
no mention-resolution overhead. Only if that first SELECT errors out
or returns zero rows do we invoke ``resolve_mentions`` + canonicalise
the surface forms (``Alice S.`` → ``Alice Smith``, ``アリス`` →
``アリス (関連: Alice Smith)``) and retry once. The common case pays
zero embedding cost; alias / fuzzy mentions are recovered on the
retry without dragging the LLM into a non-standard SQL pattern.

Two seams worth noting:

* ``ALLOWED_TABLES`` is the same set passed to ``validate_readonly_sql``.
  Keep it here so callers can extend it deliberately when new tables are
  added in a migration.
* ``generate_sql`` uses ``LLMProtocol.extract`` with the
  ``GeneratedSQL`` schema, which means instructor handles JSON
  validation. The fake LLM honours the same contract in tests.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from docdb.llm.base import LLMProtocol
from docdb.llm.prompts import TEXT2SQL_PROMPT_MAX_BYTES, build_text2sql_user_prompt
from docdb.search.entity_resolution import (
    canonicalize_mentions_in_question,
    resolve_mentions,
)
from docdb.search.sql_guard import UnsafeQueryError, validate_readonly_sql
from docdb.typing.registry import (
    EntityTypeDef,
    RelationTypeDef,
    list_entity_types,
    list_relation_types,
)


ALLOWED_TABLES: set[str] = {
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
    "v_edges",
}


class GeneratedSQL(BaseModel):
    sql: str = Field(min_length=1)
    reasoning: str = ""


@dataclass
class Text2SQLResult:
    question: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    sql: str | None = None
    validated_sql: str | None = None
    reasoning: str | None = None
    error: str | None = None
    # Populated only when the retry path rewrote the question and the
    # retry returned the result we ended up using. Lets callers (agent
    # trace, UI, tests) tell whether resolution kicked in.
    rewritten_question: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


def generate_sql(
    question: str,
    llm: LLMProtocol,
    *,
    entity_types: list[EntityTypeDef] = (),
    relation_types: list[RelationTypeDef] = (),
    max_prompt_bytes: int = TEXT2SQL_PROMPT_MAX_BYTES,
) -> GeneratedSQL:
    prompt = build_text2sql_user_prompt(
        question,
        entity_types=entity_types,
        relation_types=relation_types,
        max_bytes=max_prompt_bytes,
    )
    return llm.extract(prompt, GeneratedSQL)


def run_text2sql(
    conn: sqlite3.Connection,
    question: str,
    llm: LLMProtocol,
    *,
    max_limit: int = 50,
    allowed_tables: set[str] = ALLOWED_TABLES,
    max_rows: int = 100,
    max_prompt_bytes: int = TEXT2SQL_PROMPT_MAX_BYTES,
    resolution_enabled: bool = True,
    resolution_top_k: int = 15,
    # Default mirrors ``Settings.query_resolution_distance`` so direct
    # callers and the Toolbox path see the same threshold.
    resolution_distance_threshold: float = 0.85,
) -> Text2SQLResult:
    """Generate → validate → execute, with KNN-fallback retry.

    The current entity/relation type registry is fetched from ``conn``
    and injected into the SQL-generation prompt so the LLM sees each
    type's ``fields_schema``.

    Retry: if the primary attempt errors or returns zero rows AND
    ``resolution_enabled`` is true, ``resolve_mentions`` is invoked on
    the original question; the surface mentions are rewritten to their
    canonical form via ``canonicalize_mentions_in_question``, and a
    second SQL-generation pass runs on the rewritten question. The
    better of the two results is returned.
    """
    try:
        entity_types = list_entity_types(conn)
        relation_types = list_relation_types(conn)
    except sqlite3.Error:
        # Registry fetch is a best-effort enrichment; on failure fall back
        # to an empty catalogue rather than blocking the SQL generation.
        entity_types = []
        relation_types = []

    primary = _execute_text2sql(
        conn, question, llm,
        entity_types=entity_types,
        relation_types=relation_types,
        max_limit=max_limit,
        allowed_tables=allowed_tables,
        max_rows=max_rows,
        max_prompt_bytes=max_prompt_bytes,
    )

    if not resolution_enabled or not _should_retry_with_resolution(primary):
        return primary

    candidates = resolve_mentions(
        conn, question, llm,
        top_k=resolution_top_k,
        distance_threshold=resolution_distance_threshold,
        enabled=True,
    )
    if not candidates:
        return primary

    rewritten = canonicalize_mentions_in_question(question, candidates)
    if rewritten == question:
        return primary  # nothing to canonicalize → retry would be identical

    retry = _execute_text2sql(
        conn, rewritten, llm,
        entity_types=entity_types,
        relation_types=relation_types,
        max_limit=max_limit,
        allowed_tables=allowed_tables,
        max_rows=max_rows,
        max_prompt_bytes=max_prompt_bytes,
    )
    if not _is_better(retry, primary):
        return primary

    retry.rewritten_question = rewritten
    retry.question = question  # surface original to callers; rewritten lives on its own field
    return retry


def _execute_text2sql(
    conn: sqlite3.Connection,
    question: str,
    llm: LLMProtocol,
    *,
    entity_types: list[EntityTypeDef],
    relation_types: list[RelationTypeDef],
    max_limit: int,
    allowed_tables: set[str],
    max_rows: int,
    max_prompt_bytes: int,
) -> Text2SQLResult:
    """Single text2sql attempt: generate → validate → execute. No retry."""
    try:
        gen = generate_sql(
            question,
            llm,
            entity_types=entity_types,
            relation_types=relation_types,
            max_prompt_bytes=max_prompt_bytes,
        )
    except Exception as exc:  # noqa: BLE001
        return Text2SQLResult(
            question=question,
            error=f"llm error: {type(exc).__name__}: {exc}",
        )

    try:
        safe_sql = validate_readonly_sql(
            gen.sql, allowed_tables=allowed_tables, max_limit=max_limit
        )
    except UnsafeQueryError as exc:
        return Text2SQLResult(
            question=question,
            sql=gen.sql,
            reasoning=gen.reasoning or None,
            error=f"unsafe sql: {exc}",
        )

    try:
        cursor = conn.execute(safe_sql)
        rows = cursor.fetchmany(max_rows)
    except sqlite3.Error as exc:
        return Text2SQLResult(
            question=question,
            sql=gen.sql,
            validated_sql=safe_sql,
            reasoning=gen.reasoning or None,
            error=f"sqlite error: {exc}",
        )

    return Text2SQLResult(
        question=question,
        sql=gen.sql,
        validated_sql=safe_sql,
        reasoning=gen.reasoning or None,
        rows=[dict(r) for r in rows],
    )


def _should_retry_with_resolution(result: Text2SQLResult) -> bool:
    """Trigger: SQL failure (any error) OR no rows.

    The empty-rows trigger over-fires on legitimately-empty answers
    (``未完了タスクは?`` against a corpus with no pending tasks), but
    in those cases ``resolve_mentions`` returns no candidates and the
    retry short-circuits before another LLM call — wasted embedding,
    no wasted extract.
    """
    return result.error is not None or not result.rows


def _is_better(retry: Text2SQLResult, primary: Text2SQLResult) -> bool:
    """Pick the retry only when it's strictly an improvement."""
    if retry.error and not primary.error:
        return False
    if not retry.error and primary.error:
        return True
    # Both errored, or both succeeded — prefer more rows.
    return len(retry.rows) > len(primary.rows)
