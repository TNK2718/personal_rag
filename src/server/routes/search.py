from __future__ import annotations

from flask import Blueprint, jsonify, request

from docdb.search.direct import search as direct_search
from docdb.search.hybrid import hybrid_search

from server.context import get_conn, get_llm

bp = Blueprint("search", __name__, url_prefix="/api")


@bp.post("/search")
def search_endpoint():
    payload = request.get_json(silent=True) or {}
    query = (payload.get("query") or "").strip()
    doc_type = payload.get("doc_type") or None
    date_from = payload.get("date_from") or None
    date_to = payload.get("date_to") or None
    use_hybrid = bool(payload.get("hybrid", False))

    try:
        top_k = max(1, min(int(payload.get("top_k", 10)), 50))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid top_k"}), 400

    conn = get_conn()

    if use_hybrid and query:
        llm = get_llm()
        try:
            [embedding] = llm.embed([query])
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"embedding failed: {exc}"}), 502
        hits = hybrid_search(
            conn,
            query,
            embedding=embedding,
            top_k=top_k,
            doc_type=doc_type,
            date_from=date_from,
            date_to=date_to,
        )
    else:
        hits = direct_search(
            conn,
            query,
            top_k=top_k,
            doc_type=doc_type,
            date_from=date_from,
            date_to=date_to,
        )
    return jsonify([c.model_dump() for c in hits])
