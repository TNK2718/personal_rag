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

    entity_rows = conn.execute(
        "SELECT e.type_slug, et.label, COUNT(*) AS n "
        "FROM entities AS e "
        "LEFT JOIN entity_types AS et ON et.slug = e.type_slug "
        "GROUP BY e.type_slug "
        "ORDER BY n DESC, e.type_slug"
    ).fetchall()
    entities_by_type = [
        {"type_slug": r["type_slug"], "label": r["label"], "count": int(r["n"])}
        for r in entity_rows
    ]
    entities_n = sum(item["count"] for item in entities_by_type)
    relations_n = conn.execute("SELECT COUNT(*) AS n FROM relations").fetchone()["n"]
    tags_n = conn.execute("SELECT COUNT(*) AS n FROM tags").fetchone()["n"]

    return jsonify(
        {
            "documents_total": docs_total,
            "doc_types": doc_types,
            "entities_total": int(entities_n),
            "entities_by_type": entities_by_type,
            "relations_total": int(relations_n),
            "tags_total": int(tags_n),
        }
    )


@bp.get("/doc-types")
def doc_types():
    conn = get_conn()
    return jsonify(
        [{"doc_type": name, "count": n} for name, n in list_doc_types(conn)]
    )
