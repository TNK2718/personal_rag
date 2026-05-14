"""Property-graph relation CRUD."""

from __future__ import annotations

import sqlite3

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from docdb.ingestion.store import DocumentStore
from docdb.models import Relation, relation_id_for
from docdb.search.direct import search_relations
from docdb.typing.registry import get_relation_type

from server.context import get_conn


bp = Blueprint("relations", __name__, url_prefix="/api/relations")


def _client_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _row_to_payload(rel: Relation) -> dict:
    return rel.model_dump()


# ---------------------------------------------------------------------------
# GET /api/relations
# ---------------------------------------------------------------------------
@bp.get("")
def list_relations():
    conn = get_conn()
    type_slug = request.args.get("type_slug") or request.args.get("type") or None
    source_entity_id = request.args.get("source_entity_id") or None
    target_entity_id = request.args.get("target_entity_id") or None
    try:
        top_k = max(1, min(int(request.args.get("top_k", 100)), 500))
    except ValueError:
        return _client_error("invalid top_k")

    rels = search_relations(
        conn,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        type_slug=type_slug,
        top_k=top_k,
    )
    return jsonify([_row_to_payload(r) for r in rels])


# ---------------------------------------------------------------------------
# POST /api/relations
# ---------------------------------------------------------------------------
@bp.post("")
def create_relation():
    conn = get_conn()
    payload = request.get_json(silent=True) or {}

    type_slug = payload.get("type_slug")
    source = payload.get("source_entity_id")
    target = payload.get("target_entity_id")
    if not (type_slug and source and target):
        return _client_error("type_slug, source_entity_id, target_entity_id are required")

    if get_relation_type(conn, type_slug) is None:
        return _client_error(f"unknown relation type_slug: {type_slug!r}", status=400)

    relation = Relation(
        id=relation_id_for(type_slug, source, target),
        type_slug=type_slug,
        source_entity_id=source,
        target_entity_id=target,
        fields=dict(payload.get("fields") or {}),
    )

    store = DocumentStore(conn)
    try:
        store.upsert_relation(relation)
    except ValueError as exc:
        return _client_error(str(exc))
    except (ValidationError, sqlite3.IntegrityError) as exc:
        return _client_error(str(exc))

    return jsonify(relation.model_dump()), 201


# ---------------------------------------------------------------------------
# PATCH / DELETE /api/relations/<id>
# ---------------------------------------------------------------------------
@bp.patch("/<relation_id>")
def update_relation_route(relation_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM relations WHERE id = ?", (relation_id,)).fetchone()
    if row is None:
        return _client_error("not found", status=404)
    payload = request.get_json(silent=True) or {}
    if "fields" not in payload:
        return _client_error("only `fields` may be patched on a relation")

    import json as _json
    existing_fields: dict = {}
    if row["fields"]:
        try:
            existing_fields = _json.loads(row["fields"]) or {}
        except (ValueError, TypeError):
            existing_fields = {}

    merged_fields = {**existing_fields, **dict(payload["fields"] or {})}

    relation = Relation(
        id=relation_id,
        type_slug=row["type_slug"],
        source_entity_id=row["source_entity_id"],
        target_entity_id=row["target_entity_id"],
        fields=merged_fields,
    )
    store = DocumentStore(conn)
    try:
        store.upsert_relation(relation)
    except ValueError as exc:
        return _client_error(str(exc))
    return jsonify(relation.model_dump())


@bp.delete("/<relation_id>")
def delete_relation_route(relation_id: str):
    conn = get_conn()
    store = DocumentStore(conn)
    if not store.delete_relation(relation_id):
        return _client_error("not found", status=404)
    return ("", 204)
