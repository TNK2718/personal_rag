"""Read / write access to the runtime type registry.

Two simple Pydantic record types wrap the rows in ``entity_types`` and
``relation_types``. The ``fields_schema`` JSON column is parsed eagerly into
``FieldSpec`` objects on the way out, and re-serialised on upsert.

``registry_hash`` is a stable hash over ``(slug, updated_ts)`` tuples used
by Stage 3 to invalidate dynamic-Pydantic / instructor caches.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from docdb.typing.field_spec import (
    FieldSpec,
    dump_fields_schema,
    parse_fields_schema,
)


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class _TypeBase(BaseModel):
    """Shared columns between entity_types and relation_types."""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=128)
    description: str | None = None
    fields: list[FieldSpec] = Field(default_factory=list)
    extraction_hint: str | None = None
    is_builtin: bool = False
    created_ts: str | None = None
    updated_ts: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_fields_schema_alias(cls, data: Any) -> Any:
        # The DB column is named `fields_schema`; in-memory the attribute is
        # `fields`. Accept either form for ergonomics in tests/API payloads.
        if isinstance(data, dict) and "fields_schema" in data and "fields" not in data:
            raw = data.pop("fields_schema")
            data["fields"] = parse_fields_schema(raw)
        elif isinstance(data, dict) and "fields" in data:
            field_value = data["fields"]
            if isinstance(field_value, (str, list)) and (
                isinstance(field_value, str)
                or (isinstance(field_value, list) and field_value and isinstance(field_value[0], dict))
                or field_value == []
            ):
                data["fields"] = parse_fields_schema(field_value)
        return data


class EntityTypeDef(_TypeBase):
    icon: str | None = None
    color: str | None = None


class RelationTypeDef(_TypeBase):
    inverse_label: str | None = None
    source_type_slug: str | None = None
    target_type_slug: str | None = None


# ---------------------------------------------------------------------------
# Row → object decoders
# ---------------------------------------------------------------------------
def _row_to_entity_type(row: sqlite3.Row) -> EntityTypeDef:
    return EntityTypeDef.model_validate(
        {
            "slug": row["slug"],
            "label": row["label"],
            "description": row["description"],
            "icon": row["icon"],
            "color": row["color"],
            "fields_schema": row["fields_schema"] or "[]",
            "extraction_hint": row["extraction_hint"],
            "is_builtin": bool(row["is_builtin"]),
            "created_ts": row["created_ts"],
            "updated_ts": row["updated_ts"],
        }
    )


def _row_to_relation_type(row: sqlite3.Row) -> RelationTypeDef:
    return RelationTypeDef.model_validate(
        {
            "slug": row["slug"],
            "label": row["label"],
            "description": row["description"],
            "inverse_label": row["inverse_label"],
            "source_type_slug": row["source_type_slug"],
            "target_type_slug": row["target_type_slug"],
            "fields_schema": row["fields_schema"] or "[]",
            "extraction_hint": row["extraction_hint"],
            "is_builtin": bool(row["is_builtin"]),
            "created_ts": row["created_ts"],
            "updated_ts": row["updated_ts"],
        }
    )


# ---------------------------------------------------------------------------
# Entity type CRUD
# ---------------------------------------------------------------------------
def list_entity_types(conn: sqlite3.Connection) -> list[EntityTypeDef]:
    rows = conn.execute(
        "SELECT slug, label, description, icon, color, fields_schema, extraction_hint, "
        "       is_builtin, created_ts, updated_ts FROM entity_types ORDER BY slug"
    ).fetchall()
    return [_row_to_entity_type(r) for r in rows]


def get_entity_type(conn: sqlite3.Connection, slug: str) -> EntityTypeDef | None:
    row = conn.execute(
        "SELECT slug, label, description, icon, color, fields_schema, extraction_hint, "
        "       is_builtin, created_ts, updated_ts FROM entity_types WHERE slug = ?",
        (slug,),
    ).fetchone()
    return _row_to_entity_type(row) if row else None


def upsert_entity_type(conn: sqlite3.Connection, type_def: EntityTypeDef) -> EntityTypeDef:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO entity_types (slug, label, description, icon, color, fields_schema,
                                  extraction_hint, is_builtin, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_ts FROM entity_types WHERE slug = ?), ?), ?)
        ON CONFLICT(slug) DO UPDATE SET
            label = excluded.label,
            description = excluded.description,
            icon = excluded.icon,
            color = excluded.color,
            fields_schema = excluded.fields_schema,
            extraction_hint = excluded.extraction_hint,
            is_builtin = excluded.is_builtin,
            updated_ts = excluded.updated_ts
        """,
        (
            type_def.slug,
            type_def.label,
            type_def.description,
            type_def.icon,
            type_def.color,
            dump_fields_schema(type_def.fields),
            type_def.extraction_hint,
            1 if type_def.is_builtin else 0,
            type_def.slug,
            now,
            now,
        ),
    )
    conn.commit()
    result = get_entity_type(conn, type_def.slug)
    assert result is not None
    return result


def delete_entity_type(conn: sqlite3.Connection, slug: str) -> bool:
    cur = conn.execute("DELETE FROM entity_types WHERE slug = ?", (slug,))
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Relation type CRUD
# ---------------------------------------------------------------------------
def list_relation_types(conn: sqlite3.Connection) -> list[RelationTypeDef]:
    rows = conn.execute(
        "SELECT slug, label, description, inverse_label, source_type_slug, target_type_slug, "
        "       fields_schema, extraction_hint, is_builtin, created_ts, updated_ts "
        "FROM relation_types ORDER BY slug"
    ).fetchall()
    return [_row_to_relation_type(r) for r in rows]


def get_relation_type(conn: sqlite3.Connection, slug: str) -> RelationTypeDef | None:
    row = conn.execute(
        "SELECT slug, label, description, inverse_label, source_type_slug, target_type_slug, "
        "       fields_schema, extraction_hint, is_builtin, created_ts, updated_ts "
        "FROM relation_types WHERE slug = ?",
        (slug,),
    ).fetchone()
    return _row_to_relation_type(row) if row else None


def upsert_relation_type(conn: sqlite3.Connection, type_def: RelationTypeDef) -> RelationTypeDef:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO relation_types (slug, label, description, inverse_label, source_type_slug,
                                    target_type_slug, fields_schema, extraction_hint, is_builtin,
                                    created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                COALESCE((SELECT created_ts FROM relation_types WHERE slug = ?), ?), ?)
        ON CONFLICT(slug) DO UPDATE SET
            label = excluded.label,
            description = excluded.description,
            inverse_label = excluded.inverse_label,
            source_type_slug = excluded.source_type_slug,
            target_type_slug = excluded.target_type_slug,
            fields_schema = excluded.fields_schema,
            extraction_hint = excluded.extraction_hint,
            is_builtin = excluded.is_builtin,
            updated_ts = excluded.updated_ts
        """,
        (
            type_def.slug,
            type_def.label,
            type_def.description,
            type_def.inverse_label,
            type_def.source_type_slug,
            type_def.target_type_slug,
            dump_fields_schema(type_def.fields),
            type_def.extraction_hint,
            1 if type_def.is_builtin else 0,
            type_def.slug,
            now,
            now,
        ),
    )
    conn.commit()
    result = get_relation_type(conn, type_def.slug)
    assert result is not None
    return result


def delete_relation_type(conn: sqlite3.Connection, slug: str) -> bool:
    cur = conn.execute("DELETE FROM relation_types WHERE slug = ?", (slug,))
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Hash for cache invalidation
# ---------------------------------------------------------------------------
def registry_hash(conn: sqlite3.Connection) -> str:
    """Stable hash over (slug, updated_ts) tuples for both type tables.

    Stage 3 uses this to key the dynamic-Pydantic / instructor schema cache.
    """
    rows = conn.execute(
        "SELECT 'e' AS kind, slug, updated_ts FROM entity_types "
        "UNION ALL "
        "SELECT 'r' AS kind, slug, updated_ts FROM relation_types "
        "ORDER BY kind, slug"
    ).fetchall()
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r['kind']}|{r['slug']}|{r['updated_ts']}\n".encode("utf-8"))
    return h.hexdigest()
