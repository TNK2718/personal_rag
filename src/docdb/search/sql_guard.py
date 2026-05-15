"""Pure-function SQL safety validator for Text2SQL and the agent's
``execute_readonly_sql`` escape hatch.

The contract is intentionally narrow:

* Only a single ``SELECT`` (or ``WITH ... SELECT``) statement is allowed.
* Any DML/DDL/PRAGMA/ATTACH/transaction-control node makes the query fail.
* Every base table referenced — including those inside CTEs, subqueries,
  and UNION arms — must appear in ``allowed_tables``. CTE names defined
  in the same query are not treated as base tables.
* If the outermost SELECT has no LIMIT, one is injected
  (``max_limit``). Existing LIMITs are left alone.

The function is pure: no I/O, no LLM, no global state. That's the
point — it can be tested exhaustively without fixtures and reused
identically by Text2SQL and the agent.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp


class UnsafeQueryError(ValueError):
    """Raised when a SQL string fails the read-only safety check."""


_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)


def _collect_cte_names(tree: exp.Expression) -> set[str]:
    names: set[str] = set()
    for cte in tree.find_all(exp.CTE):
        alias = cte.alias_or_name
        if alias:
            names.add(alias.lower())
    return names


def _normalise_table_name(table: exp.Table) -> str:
    return table.name.lower()


def validate_readonly_sql(
    sql: str,
    *,
    allowed_tables: set[str],
    max_limit: int = 100,
) -> str:
    """Validate ``sql`` against the safety contract.

    Returns the (possibly rewritten with an injected LIMIT) SQL on
    success. Raises ``UnsafeQueryError`` on any violation.
    """
    if not sql or not sql.strip():
        raise UnsafeQueryError("empty SQL")

    # Reject multi-statement strings outright. parse_one tolerates them
    # by returning only the first statement, so we look at parse() too.
    statements = [s for s in sqlglot.parse(sql, dialect="sqlite") if s is not None]
    if len(statements) > 1:
        raise UnsafeQueryError("multiple statements are not allowed")

    try:
        tree = sqlglot.parse_one(sql, dialect="sqlite")
    except Exception as exc:  # pragma: no cover - sqlglot raises a few types
        raise UnsafeQueryError(f"could not parse SQL: {exc}") from exc

    if tree is None:
        raise UnsafeQueryError("empty parse tree")

    # The outermost node must be a SELECT-shaped expression.
    if not isinstance(tree, (exp.Select, exp.Union, exp.With, exp.Subquery)):
        raise UnsafeQueryError(
            f"only SELECT/WITH/UNION is allowed; got {type(tree).__name__}"
        )

    # Forbidden node check.
    for node_type in _FORBIDDEN_NODES:
        bad = next(tree.find_all(node_type), None)
        if bad is not None:
            raise UnsafeQueryError(
                f"forbidden statement type: {node_type.__name__}"
            )

    # Table-allowlist check (skip CTE names defined in this same query).
    cte_names = _collect_cte_names(tree)
    allowed_lower = {t.lower() for t in allowed_tables}
    for table in tree.find_all(exp.Table):
        name = _normalise_table_name(table)
        if name in cte_names:
            continue
        if name not in allowed_lower:
            raise UnsafeQueryError(f"disallowed table: {table.name}")

    # LIMIT injection: only at the outermost SELECT, only when missing.
    if not _outermost_has_limit(tree):
        tree = tree.limit(max_limit)

    # Render in sqlglot's default (generic-ish) dialect rather than
    # ``sqlite``: the sqlite dialect transpiles
    # ``json_extract(col, '$.path')`` to the ``col -> '$.path'`` shorthand
    # (SQLite 3.38+). Python's stdlib ``sqlite3`` on Windows still bundles
    # 3.37.2, so executing the rewritten form yields ``near ">": syntax
    # error``. The default render keeps ``JSON_EXTRACT(...)`` as a
    # function call, which every supported SQLite version understands;
    # all the other SQLite-specific constructs we generate (MATCH, AS
    # aliases, …) round-trip identically through this render.
    return tree.sql()


def _outermost_has_limit(tree: exp.Expression) -> bool:
    """Return True iff the outermost SELECT/UNION already has a LIMIT.

    We deliberately ignore LIMITs inside subqueries or CTEs - those are
    the user's business; we only force a cap on the rows leaving the
    statement.
    """
    if isinstance(tree, exp.With):
        # WITH wraps a Select; the limit lives on the inner Select.
        inner = tree.this
        return inner.args.get("limit") is not None
    return tree.args.get("limit") is not None
