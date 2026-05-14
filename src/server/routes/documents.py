from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from docdb.search.direct import find_similar, get_document, search as direct_search

from server.context import get_conn

bp = Blueprint("documents", __name__, url_prefix="/api/documents")


@bp.get("")
def list_documents():
    """List documents with optional filters and FTS query.

    Query params: q, doc_type, date_from, date_to, limit (default 50), offset.
    """
    conn = get_conn()
    q = (request.args.get("q") or "").strip() or None
    doc_type = request.args.get("doc_type") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None

    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return jsonify({"error": "invalid limit/offset"}), 400

    if q:
        # FTS path: reuse direct.search and take top_k = limit + offset, then slice.
        # offset rarely used in search; this keeps the SQL simple.
        hits = direct_search(
            conn,
            q,
            top_k=limit + offset,
            doc_type=doc_type,
            date_from=date_from,
            date_to=date_to,
        )
        sliced = hits[offset : offset + limit]
        created_at_by_id = _created_at_lookup(conn, [c.document_id for c in sliced])
        items = [
            {
                "document_id": c.document_id,
                "title": c.title,
                "source_path": c.source_path,
                "doc_type": c.doc_type,
                "created_at": created_at_by_id.get(c.document_id),
                "snippet": c.snippet,
                "score": c.score,
            }
            for c in sliced
        ]
        return jsonify(
            {
                "items": items,
                "total": _count_documents_filtered(conn, doc_type, date_from, date_to),
                "limit": limit,
                "offset": offset,
            }
        )

    # Structured listing (no FTS query).
    sql = (
        "SELECT id, title, source_path, doc_type, created_at, summary "
        "FROM documents WHERE 1=1"
    )
    params: list = []
    if doc_type is not None:
        sql += " AND doc_type = ?"
        params.append(doc_type)
    if date_from is not None:
        sql += " AND created_at >= ?"
        params.append(date_from)
    if date_to is not None:
        sql += " AND created_at <= ?"
        params.append(date_to)
    sql += " ORDER BY COALESCE(created_at, '') DESC, id LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    items = [
        {
            "document_id": r["id"],
            "title": r["title"],
            "source_path": r["source_path"],
            "doc_type": r["doc_type"],
            "created_at": r["created_at"],
            "snippet": (r["summary"] or "")[:160] or None,
            "score": None,
        }
        for r in rows
    ]
    return jsonify(
        {
            "items": items,
            "total": _count_documents_filtered(conn, doc_type, date_from, date_to),
            "limit": limit,
            "offset": offset,
        }
    )


@bp.get("/<document_id>")
def document_detail(document_id: str):
    conn = get_conn()
    doc = get_document(conn, document_id)
    if doc is None:
        return jsonify({"error": "document not found"}), 404

    entities = [
        {
            "id": r["id"],
            "type_slug": r["type_slug"],
            "canonical_name": r["canonical_name"],
            "aliases": _json_or_empty_list(r["aliases"]),
            "fields": _json_or_empty_dict(r["fields"]),
            "mention_count": int(r["mention_count"]),
        }
        for r in conn.execute(
            "SELECT e.id, e.type_slug, e.canonical_name, e.aliases, e.fields, de.mention_count "
            "FROM entities AS e "
            "JOIN document_entities AS de ON de.entity_id = e.id "
            "WHERE de.document_id = ? "
            "ORDER BY de.mention_count DESC",
            (document_id,),
        ).fetchall()
    ]

    tags = [
        {
            "id": r["id"],
            "canonical_name": r["canonical_name"],
            "category": r["category"],
            "confidence": float(r["confidence"]),
        }
        for r in conn.execute(
            "SELECT t.id, t.canonical_name, t.category, dt.confidence "
            "FROM tags AS t "
            "JOIN document_tags AS dt ON dt.tag_id = t.id "
            "WHERE dt.document_id = ? "
            "ORDER BY dt.confidence DESC",
            (document_id,),
        ).fetchall()
    ]

    payload = doc.model_dump()
    payload["entities"] = entities
    payload["tags"] = tags
    return jsonify(payload)


@bp.get("/<document_id>/similar")
def document_similar(document_id: str):
    conn = get_conn()
    try:
        top_k = max(1, min(int(request.args.get("top_k", 5)), 20))
    except ValueError:
        return jsonify({"error": "invalid top_k"}), 400
    hits = find_similar(conn, document_id, top_k=top_k)
    return jsonify([c.model_dump() for c in hits])


def _count_documents_filtered(
    conn, doc_type: str | None, date_from: str | None, date_to: str | None
) -> int:
    sql = "SELECT COUNT(*) AS n FROM documents WHERE 1=1"
    params: list = []
    if doc_type is not None:
        sql += " AND doc_type = ?"
        params.append(doc_type)
    if date_from is not None:
        sql += " AND created_at >= ?"
        params.append(date_from)
    if date_to is not None:
        sql += " AND created_at <= ?"
        params.append(date_to)
    return int(conn.execute(sql, params).fetchone()["n"])


def _created_at_lookup(conn, ids: list[str]) -> dict[str, str | None]:
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, created_at FROM documents WHERE id IN ({placeholders})", ids
    ).fetchall()
    return {r["id"]: r["created_at"] for r in rows}


def _json_or_empty_list(value):
    if not value:
        return []
    try:
        out = json.loads(value)
    except (ValueError, TypeError):
        return []
    return out if isinstance(out, list) else []


def _json_or_empty_dict(value):
    if not value:
        return {}
    try:
        out = json.loads(value)
    except (ValueError, TypeError):
        return {}
    return out if isinstance(out, dict) else {}
