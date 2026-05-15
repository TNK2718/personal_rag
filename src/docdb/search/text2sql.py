"""Level-2 Text2SQL.

The LLM proposes a SELECT for a user question; sql_guard validates it;
we then execute it as a bound query. Errors do not raise — they land
on the returned ``Text2SQLResult`` so a higher layer (the agent) can
report the failure and try again with a different approach.

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
from docdb.search.entity_resolution import ResolvedCandidate, resolve_mentions
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

    @property
    def succeeded(self) -> bool:
        return self.error is None


def generate_sql(
    question: str,
    llm: LLMProtocol,
    *,
    entity_types: list[EntityTypeDef] = (),
    relation_types: list[RelationTypeDef] = (),
    mention_candidates: list[ResolvedCandidate] = (),
    max_prompt_bytes: int = TEXT2SQL_PROMPT_MAX_BYTES,
) -> GeneratedSQL:
    prompt = build_text2sql_user_prompt(
        question,
        entity_types=entity_types,
        relation_types=relation_types,
        mention_candidates=mention_candidates,
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
    resolution_distance_threshold: float = 0.55,
) -> Text2SQLResult:
    """Generate → validate → execute. All errors land in the result.

    The current entity/relation type registry is fetched from ``conn`` and
    injected into the prompt so the LLM sees each type's fields_schema.

    Mention resolution: when ``resolution_enabled`` is true, the question
    is embedded and KNN-matched against ``entities_vec`` so candidate
    entities (with their canonical_name, type_slug, aliases) are passed
    into the SQL-generation prompt — encouraging the LLM to filter by
    ``entities.id`` instead of ``LIKE``.
    """
    try:
        entity_types = list_entity_types(conn)
        relation_types = list_relation_types(conn)
    except sqlite3.Error:
        # Registry fetch is a best-effort enrichment; on failure fall back
        # to an empty catalogue rather than blocking the SQL generation.
        entity_types = []
        relation_types = []

    candidates = resolve_mentions(
        conn, question, llm,
        top_k=resolution_top_k,
        distance_threshold=resolution_distance_threshold,
        enabled=resolution_enabled,
    )

    try:
        gen = generate_sql(
            question,
            llm,
            entity_types=entity_types,
            relation_types=relation_types,
            mention_candidates=candidates,
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
