"""Property-graph entity CRUD.

Replaces the read-only Stage 1 endpoint with full CRUD: instances are
written through ``DocumentStore.upsert_entity`` so the ``entities_search``
shadow row and the ``entities_vec`` virtual table stay coherent.
``type_slug`` is now a free string — the set of valid slugs is fetched
from ``entity_types`` at request time, not baked into the route.
"""

from __future__ import annotations

import json
import sqlite3

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from docdb.ingestion.store import DocumentStore
from docdb.models import Entity, entity_id_for
from docdb.search.direct import get_entity, get_entity_documents, search_entities
from docdb.typing.registry import get_entity_type

from server.context import get_conn


bp = Blueprint("entities", __name__, url_prefix="/api/entities")


def _row_to_payload(row: sqlite3.Row, *, mention_total: int | None = None) -> dict:
    aliases: list[str] = []
    fields: dict = {}
    if row["aliases"]:
        try:
            aliases = json.loads(row["aliases"]) or []
        except (ValueError, TypeError):
            aliases = []
    if row["fields"]:
        try:
            fields = json.loads(row["fields"]) or {}
        except (ValueError, TypeError):
            fields = {}
    payload = {
        "id": row["id"],
        "type_slug": row["type_slug"],
        "canonical_name": row["canonical_name"],
        "aliases": aliases,
        "description": row["description"],
        "fields": fields,
        "created_ts": row["created_ts"] if "created_ts" in row.keys() else None,
        "updated_ts": row["updated_ts"] if "updated_ts" in row.keys() else None,
    }
    if mention_total is not None:
        payload["mention_total"] = mention_total
    return payload


def _client_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


# ---------------------------------------------------------------------------
# GET /api/entities  — list / search
# ---------------------------------------------------------------------------
@bp.get("")
def list_entities():
    conn = get_conn()
    q = (request.args.get("q") or "").strip()
    type_slug = request.args.get("type_slug") or request.args.get("type") or None
    try:
        top_k = max(1, min(int(request.args.get("top_k", 50)), 200))
    except ValueError:
        return _client_error("invalid top_k")

    if q:
        rows = search_entities(conn, q, type_slug=type_slug, top_k=top_k)
        return jsonify([e.model_dump() for e in rows])

    # Empty query: return the most-mentioned entities first.
    sql = (
        "SELECT e.id, e.type_slug, e.canonical_name, e.aliases, e.description, e.fields, "
        "       e.created_ts, e.updated_ts, COUNT(de.document_id) AS mention_total "
        "FROM entities AS e "
        "LEFT JOIN document_entities AS de ON de.entity_id = e.id "
    )
    params: list = []
    if type_slug is not None:
        sql += "WHERE e.type_slug = ? "
        params.append(type_slug)
    sql += "GROUP BY e.id ORDER BY mention_total DESC, e.canonical_name LIMIT ?"
    params.append(top_k)
    rows = conn.execute(sql, params).fetchall()
    return jsonify(
        [_row_to_payload(r, mention_total=int(r["mention_total"] or 0)) for r in rows]
    )


# ---------------------------------------------------------------------------
# POST /api/entities  — create
# ---------------------------------------------------------------------------
@bp.post("")
def create_entity():
    conn = get_conn()
    payload = request.get_json(silent=True) or {}

    type_slug = payload.get("type_slug")
    canonical_name = (payload.get("canonical_name") or "").strip()
    if not type_slug:
        return _client_error("type_slug is required")
    if not canonical_name:
        return _client_error("canonical_name is required")

    if get_entity_type(conn, type_slug) is None:
        return _client_error(f"unknown type_slug: {type_slug!r}", status=400)

    entity = Entity(
        id=entity_id_for(type_slug, canonical_name),
        type_slug=type_slug,
        canonical_name=canonical_name,
        aliases=list(payload.get("aliases") or []),
        description=payload.get("description"),
        fields=dict(payload.get("fields") or {}),
    )

    store = DocumentStore(conn)
    try:
        store.upsert_entity(entity)
    except ValueError as exc:
        return _client_error(str(exc))
    except (ValidationError, sqlite3.IntegrityError) as exc:
        return _client_error(str(exc))

    saved = get_entity(conn, entity.id)
    assert saved is not None
    return jsonify(saved.model_dump()), 201


# ---------------------------------------------------------------------------
# GET / PATCH / DELETE /api/entities/<id>
# ---------------------------------------------------------------------------
@bp.get("/<entity_id>")
def get_entity_route(entity_id: str):
    conn = get_conn()
    ent = get_entity(conn, entity_id)
    if ent is None:
        return _client_error("not found", status=404)
    return jsonify(ent.model_dump())


@bp.patch("/<entity_id>")
def update_entity_route(entity_id: str):
    conn = get_conn()
    existing = get_entity(conn, entity_id)
    if existing is None:
        return _client_error("not found", status=404)
    payload = request.get_json(silent=True) or {}

    merged = existing.model_dump()
    if "canonical_name" in payload:
        new_name = (payload["canonical_name"] or "").strip()
        if not new_name:
            return _client_error("canonical_name cannot be empty")
        merged["canonical_name"] = new_name
    if "aliases" in payload:
        merged["aliases"] = list(payload["aliases"] or [])
    if "description" in payload:
        merged["description"] = payload["description"]
    if "fields" in payload:
        merged["fields"] = dict(payload["fields"] or {})

    # type_slug change requires a fresh row (different id). Reject for now.
    if payload.get("type_slug") and payload["type_slug"] != existing.type_slug:
        return _client_error("type_slug cannot be changed; recreate the entity")

    entity = Entity(**merged)
    store = DocumentStore(conn)
    try:
        store.upsert_entity(entity)
    except ValueError as exc:
        return _client_error(str(exc))

    saved = get_entity(conn, entity.id)
    assert saved is not None
    return jsonify(saved.model_dump())


@bp.delete("/<entity_id>")
def delete_entity_route(entity_id: str):
    conn = get_conn()
    store = DocumentStore(conn)
    if not store.delete_entity(entity_id):
        return _client_error("not found", status=404)
    return ("", 204)


@bp.get("/<entity_id>/documents")
def entity_documents(entity_id: str):
    conn = get_conn()
    try:
        top_k = max(1, min(int(request.args.get("top_k", 50)), 200))
    except ValueError:
        return _client_error("invalid top_k")
    docs = get_entity_documents(conn, entity_id, top_k=top_k)
    return jsonify([d.model_dump() for d in docs])
