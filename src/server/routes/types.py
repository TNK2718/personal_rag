"""CRUD endpoints for the runtime type registry.

Two URL prefixes share this blueprint:
    /api/types/entities    — entity_types CRUD
    /api/types/relations   — relation_types CRUD

The endpoints are deliberately thin: all schema validation lives in
``docdb.typing.field_spec`` and ``docdb.typing.registry``. ValueError /
ValidationError raised there is rendered as a 400.
"""

from __future__ import annotations

import sqlite3

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from docdb.typing.registry import (
    EntityTypeDef,
    RelationTypeDef,
    delete_entity_type,
    delete_relation_type,
    get_entity_type,
    get_relation_type,
    list_entity_types,
    list_relation_types,
    upsert_entity_type,
    upsert_relation_type,
)

from server.context import get_conn


bp = Blueprint("types", __name__, url_prefix="/api/types")


def _type_to_payload(td) -> dict:
    """Render an EntityTypeDef / RelationTypeDef to the API JSON shape."""
    base = {
        "slug": td.slug,
        "label": td.label,
        "description": td.description,
        "fields_schema": [f.model_dump(exclude_none=True) for f in td.fields],
        "extraction_hint": td.extraction_hint,
        "is_builtin": td.is_builtin,
        "created_ts": td.created_ts,
        "updated_ts": td.updated_ts,
    }
    if isinstance(td, EntityTypeDef):
        base["icon"] = td.icon
        base["color"] = td.color
    elif isinstance(td, RelationTypeDef):
        base["inverse_label"] = td.inverse_label
        base["source_type_slug"] = td.source_type_slug
        base["target_type_slug"] = td.target_type_slug
    return base


def _client_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


# ---------------------------------------------------------------------------
# Entity types
# ---------------------------------------------------------------------------
@bp.get("/entities")
def list_entity_types_route():
    conn = get_conn()
    return jsonify([_type_to_payload(t) for t in list_entity_types(conn)])


@bp.post("/entities")
def create_entity_type():
    conn = get_conn()
    payload = request.get_json(silent=True) or {}
    try:
        td = EntityTypeDef.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        return _client_error(str(exc))

    if get_entity_type(conn, td.slug) is not None:
        return _client_error(f"entity_type {td.slug!r} already exists", status=409)
    try:
        saved = upsert_entity_type(conn, td)
    except sqlite3.IntegrityError as exc:
        return _client_error(str(exc), status=409)
    return jsonify(_type_to_payload(saved)), 201


@bp.get("/entities/<slug>")
def get_entity_type_route(slug: str):
    conn = get_conn()
    td = get_entity_type(conn, slug)
    if td is None:
        return _client_error("not found", status=404)
    return jsonify(_type_to_payload(td))


@bp.put("/entities/<slug>")
def replace_entity_type(slug: str):
    conn = get_conn()
    if get_entity_type(conn, slug) is None:
        return _client_error("not found", status=404)
    payload = request.get_json(silent=True) or {}
    payload["slug"] = slug
    try:
        td = EntityTypeDef.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        return _client_error(str(exc))
    saved = upsert_entity_type(conn, td)
    return jsonify(_type_to_payload(saved))


@bp.delete("/entities/<slug>")
def delete_entity_type_route(slug: str):
    conn = get_conn()
    existing = get_entity_type(conn, slug)
    if existing is None:
        return _client_error("not found", status=404)
    if existing.is_builtin:
        return _client_error("built-in types cannot be deleted", status=409)
    try:
        delete_entity_type(conn, slug)
    except sqlite3.IntegrityError as exc:
        # FK RESTRICT from `entities.type_slug` once Stage 2 lands.
        return _client_error(f"type still has instances: {exc}", status=409)
    return ("", 204)


# ---------------------------------------------------------------------------
# Relation types
# ---------------------------------------------------------------------------
@bp.get("/relations")
def list_relation_types_route():
    conn = get_conn()
    return jsonify([_type_to_payload(t) for t in list_relation_types(conn)])


@bp.post("/relations")
def create_relation_type():
    conn = get_conn()
    payload = request.get_json(silent=True) or {}
    try:
        td = RelationTypeDef.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        return _client_error(str(exc))

    if get_relation_type(conn, td.slug) is not None:
        return _client_error(f"relation_type {td.slug!r} already exists", status=409)
    try:
        saved = upsert_relation_type(conn, td)
    except sqlite3.IntegrityError as exc:
        return _client_error(str(exc), status=409)
    return jsonify(_type_to_payload(saved)), 201


@bp.get("/relations/<slug>")
def get_relation_type_route(slug: str):
    conn = get_conn()
    td = get_relation_type(conn, slug)
    if td is None:
        return _client_error("not found", status=404)
    return jsonify(_type_to_payload(td))


@bp.put("/relations/<slug>")
def replace_relation_type(slug: str):
    conn = get_conn()
    if get_relation_type(conn, slug) is None:
        return _client_error("not found", status=404)
    payload = request.get_json(silent=True) or {}
    payload["slug"] = slug
    try:
        td = RelationTypeDef.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        return _client_error(str(exc))
    saved = upsert_relation_type(conn, td)
    return jsonify(_type_to_payload(saved))


@bp.delete("/relations/<slug>")
def delete_relation_type_route(slug: str):
    conn = get_conn()
    existing = get_relation_type(conn, slug)
    if existing is None:
        return _client_error("not found", status=404)
    if existing.is_builtin:
        return _client_error("built-in types cannot be deleted", status=409)
    try:
        delete_relation_type(conn, slug)
    except sqlite3.IntegrityError as exc:
        return _client_error(f"type still has instances: {exc}", status=409)
    return ("", 204)
