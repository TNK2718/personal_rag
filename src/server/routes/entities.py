from __future__ import annotations

from flask import Blueprint, jsonify, request

from docdb.search.direct import get_entity_documents, search_entities

from server.context import get_conn

bp = Blueprint("entities", __name__, url_prefix="/api/entities")


@bp.get("")
def list_entities():
    conn = get_conn()
    q = (request.args.get("q") or "").strip()
    entity_type = request.args.get("entity_type") or None
    try:
        top_k = max(1, min(int(request.args.get("top_k", 50)), 200))
    except ValueError:
        return jsonify({"error": "invalid top_k"}), 400

    if q:
        rows = search_entities(conn, q, entity_type=entity_type, top_k=top_k)
        return jsonify([e.model_dump() for e in rows])

    # Empty query: return the most-mentioned entities first.
    sql = (
        "SELECT e.id, e.canonical_name, e.entity_type, e.aliases, e.description, "
        "       COUNT(de.document_id) AS mention_total "
        "FROM entities AS e "
        "LEFT JOIN document_entities AS de ON de.entity_id = e.id "
    )
    params: list = []
    if entity_type is not None:
        sql += "WHERE e.entity_type = ? "
        params.append(entity_type)
    sql += "GROUP BY e.id ORDER BY mention_total DESC, e.canonical_name LIMIT ?"
    params.append(top_k)
    rows = conn.execute(sql, params).fetchall()

    import json as _json

    items = []
    for r in rows:
        aliases = []
        if r["aliases"]:
            try:
                aliases = _json.loads(r["aliases"]) or []
            except (ValueError, TypeError):
                aliases = []
        items.append(
            {
                "id": r["id"],
                "canonical_name": r["canonical_name"],
                "entity_type": r["entity_type"],
                "aliases": aliases,
                "description": r["description"],
                "mention_total": int(r["mention_total"] or 0),
            }
        )
    return jsonify(items)


@bp.get("/<entity_id>/documents")
def entity_documents(entity_id: str):
    conn = get_conn()
    try:
        top_k = max(1, min(int(request.args.get("top_k", 50)), 200))
    except ValueError:
        return jsonify({"error": "invalid top_k"}), 400
    docs = get_entity_documents(conn, entity_id, top_k=top_k)
    return jsonify([d.model_dump() for d in docs])
