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
from docdb.llm.prompts import build_text2sql_user_prompt
from docdb.search.sql_guard import UnsafeQueryError, validate_readonly_sql


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


def generate_sql(question: str, llm: LLMProtocol) -> GeneratedSQL:
    prompt = build_text2sql_user_prompt(question)
    return llm.extract(prompt, GeneratedSQL)


def run_text2sql(
    conn: sqlite3.Connection,
    question: str,
    llm: LLMProtocol,
    *,
    max_limit: int = 50,
    allowed_tables: set[str] = ALLOWED_TABLES,
    max_rows: int = 100,
) -> Text2SQLResult:
    """Generate → validate → execute. All errors land in the result."""
    try:
        gen = generate_sql(question, llm)
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
