"""validate_readonly_sql contract tests.

This module is the safety boundary between LLM-generated SQL and the
SQLite file. Tests are organised around the four contract clauses:

1. SELECT-only statements get through.
2. Forbidden statement types are rejected by name.
3. Only allow-listed base tables can be referenced; CTE aliases are not
   treated as base tables.
4. The outermost SELECT always ends up with a LIMIT.
"""

from __future__ import annotations

import re

import pytest

from docdb.search.sql_guard import UnsafeQueryError, validate_readonly_sql


ALLOWED = {
    "documents",
    "documents_fts",
    "entities",
    "tags",
    "document_entities",
    "document_tags",
    "document_relations",
    "todos",
}


def _normalise(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_simple_select_passes_through() -> None:
    out = validate_readonly_sql(
        "SELECT id FROM documents WHERE doc_type = 'memo' LIMIT 10",
        allowed_tables=ALLOWED,
    )
    assert "LIMIT 10" in _normalise(out)


def test_existing_limit_is_preserved() -> None:
    out = validate_readonly_sql(
        "SELECT id FROM documents LIMIT 5",
        allowed_tables=ALLOWED,
    )
    assert "LIMIT 5" in _normalise(out)
    assert "LIMIT 100" not in _normalise(out)


def test_limit_is_injected_when_missing() -> None:
    out = validate_readonly_sql(
        "SELECT id FROM documents",
        allowed_tables=ALLOWED,
        max_limit=50,
    )
    assert "LIMIT 50" in _normalise(out)


def test_join_against_allowed_tables_passes() -> None:
    sql = (
        "SELECT d.id FROM documents AS d "
        "JOIN document_tags AS dt ON dt.document_id = d.id "
        "JOIN tags AS t ON t.id = dt.tag_id "
        "WHERE t.canonical_name = 'python'"
    )
    out = validate_readonly_sql(sql, allowed_tables=ALLOWED)
    assert "LIMIT 100" in _normalise(out)


def test_cte_referencing_allowed_table_passes() -> None:
    sql = (
        "WITH recent AS (SELECT id FROM documents WHERE created_at > '2026-01-01') "
        "SELECT * FROM recent"
    )
    out = validate_readonly_sql(sql, allowed_tables=ALLOWED)
    # The injected LIMIT lives on the inner SELECT inside the WITH.
    assert "LIMIT" in _normalise(out).upper()


def test_union_of_two_allowed_selects_passes() -> None:
    sql = (
        "SELECT id FROM documents WHERE doc_type='memo' "
        "UNION "
        "SELECT id FROM documents WHERE doc_type='meeting'"
    )
    validate_readonly_sql(sql, allowed_tables=ALLOWED)


def test_fts_match_against_documents_fts_passes() -> None:
    sql = (
        "SELECT d.id, snippet(documents_fts, 2, '<b>', '</b>', '...', 32) "
        "FROM documents_fts JOIN documents d ON d.rowid = documents_fts.rowid "
        "WHERE documents_fts MATCH '解約条項'"
    )
    validate_readonly_sql(sql, allowed_tables=ALLOWED)


# ---------------------------------------------------------------------------
# Forbidden statements
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO documents(id, source_type, content_hash) VALUES ('x','md','h')",
        "UPDATE documents SET title='oops' WHERE id='x'",
        "DELETE FROM documents WHERE id='x'",
        "DROP TABLE documents",
        "ALTER TABLE documents ADD COLUMN evil TEXT",
        "CREATE TABLE x(a INTEGER)",
        "PRAGMA foreign_keys = OFF",
        "ATTACH DATABASE 'other.db' AS o",
        "DETACH DATABASE o",
    ],
)
def test_destructive_or_meta_statements_are_rejected(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql(sql, allowed_tables=ALLOWED)


def test_multi_statement_string_is_rejected() -> None:
    with pytest.raises(UnsafeQueryError, match="multiple"):
        validate_readonly_sql(
            "SELECT id FROM documents; DROP TABLE documents;",
            allowed_tables=ALLOWED,
        )


def test_empty_string_is_rejected() -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql("", allowed_tables=ALLOWED)
    with pytest.raises(UnsafeQueryError):
        validate_readonly_sql("   \n   ", allowed_tables=ALLOWED)


# ---------------------------------------------------------------------------
# Table allowlist
# ---------------------------------------------------------------------------
def test_disallowed_table_in_simple_select_is_rejected() -> None:
    with pytest.raises(UnsafeQueryError, match="disallowed table"):
        validate_readonly_sql(
            "SELECT * FROM sqlite_master",
            allowed_tables=ALLOWED,
        )


def test_disallowed_table_in_subquery_is_rejected() -> None:
    with pytest.raises(UnsafeQueryError, match="disallowed table"):
        validate_readonly_sql(
            "SELECT id FROM documents WHERE id IN (SELECT name FROM sqlite_master)",
            allowed_tables=ALLOWED,
        )


def test_disallowed_table_inside_union_is_rejected() -> None:
    with pytest.raises(UnsafeQueryError, match="disallowed table"):
        validate_readonly_sql(
            "SELECT id FROM documents UNION SELECT name FROM sqlite_master",
            allowed_tables=ALLOWED,
        )


def test_cte_name_is_not_mistaken_for_a_base_table() -> None:
    # `recent` is a CTE alias, not a base table — the validator must
    # not reject the outer SELECT just because `recent` isn't in the
    # allowlist.
    sql = (
        "WITH recent AS (SELECT id FROM documents) "
        "SELECT * FROM recent"
    )
    validate_readonly_sql(sql, allowed_tables=ALLOWED)


def test_allowlist_is_case_insensitive() -> None:
    validate_readonly_sql(
        "SELECT id FROM Documents",
        allowed_tables=ALLOWED,
    )
