from __future__ import annotations

from flask import Blueprint, jsonify

from docdb.search.direct import count_documents, list_doc_types

from server.context import get_conn

bp = Blueprint("stats", __name__, url_prefix="/api")


@bp.get("/stats")
def stats():
    conn = get_conn()
    docs_total = count_documents(conn)
    doc_types = [{"doc_type": name, "count": n} for name, n in list_doc_types(conn)]

    todos_rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM todos GROUP BY status"
    ).fetchall()
    todos_by_status = {r["status"]: int(r["n"]) for r in todos_rows}
    todos_total = sum(todos_by_status.values())

    entities_n = conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
    tags_n = conn.execute("SELECT COUNT(*) AS n FROM tags").fetchone()["n"]

    return jsonify(
        {
            "documents_total": docs_total,
            "doc_types": doc_types,
            "todos_total": int(todos_total),
            "todos_by_status": todos_by_status,
            "entities_total": int(entities_n),
            "tags_total": int(tags_n),
        }
    )


@bp.get("/doc-types")
def doc_types():
    conn = get_conn()
    return jsonify(
        [{"doc_type": name, "count": n} for name, n in list_doc_types(conn)]
    )
