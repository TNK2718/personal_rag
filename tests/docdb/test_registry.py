"""Type registry tests: round-tripping rows, hashing for cache invalidation."""

from __future__ import annotations

import json
import sqlite3

import pytest

from docdb.typing.registry import (
    EntityTypeDef,
    RelationTypeDef,
    delete_entity_type,
    delete_relation_type,
    get_entity_type,
    get_relation_type,
    list_entity_types,
    list_relation_types,
    registry_hash,
    upsert_entity_type,
    upsert_relation_type,
)


def test_seed_entity_types_loaded_after_init_db(conn: sqlite3.Connection) -> None:
    slugs = {t.slug for t in list_entity_types(conn)}
    assert {"person", "org", "place", "task"}.issubset(slugs)


def test_seed_task_has_three_fields(conn: sqlite3.Connection) -> None:
    task = get_entity_type(conn, "task")
    assert task is not None
    assert [f.name for f in task.fields] == ["status", "priority", "due_date"]
    statuses = next(f for f in task.fields if f.name == "status")
    assert getattr(statuses, "options", None) == ["pending", "in_progress", "completed", "cancelled"]


def test_seed_relation_types_loaded(conn: sqlite3.Connection) -> None:
    slugs = {t.slug for t in list_relation_types(conn)}
    assert {"assigned_to", "mentions"}.issubset(slugs)


class TestUpsertEntityType:
    def test_creates_and_reads_back(self, conn: sqlite3.Connection) -> None:
        upsert_entity_type(
            conn,
            EntityTypeDef.model_validate(
                {
                    "slug": "meeting_topic",
                    "label": "議題",
                    "description": "会議で議論されたトピック",
                    "fields_schema": [
                        {"name": "decision", "label": "決定事項", "type": "text", "required": False}
                    ],
                    "extraction_hint": "会議メモから議題を抽出",
                }
            ),
        )
        got = get_entity_type(conn, "meeting_topic")
        assert got is not None
        assert got.label == "議題"
        assert [f.name for f in got.fields] == ["decision"]

    def test_rejects_invalid_fields_schema(self, conn: sqlite3.Connection) -> None:
        # Duplicate field names: should raise during parse, not silently corrupt DB.
        with pytest.raises(ValueError):
            EntityTypeDef.model_validate(
                {
                    "slug": "bogus",
                    "label": "bogus",
                    "fields_schema": [
                        {"name": "x", "label": "X", "type": "string"},
                        {"name": "x", "label": "X2", "type": "int"},
                    ],
                }
            )

    def test_updates_existing_row(self, conn: sqlite3.Connection) -> None:
        upsert_entity_type(
            conn,
            EntityTypeDef.model_validate(
                {"slug": "decision", "label": "決定", "fields_schema": []}
            ),
        )
        upsert_entity_type(
            conn,
            EntityTypeDef.model_validate(
                {"slug": "decision", "label": "Decisions", "fields_schema": []}
            ),
        )
        got = get_entity_type(conn, "decision")
        assert got is not None
        assert got.label == "Decisions"

    def test_delete_removes_row(self, conn: sqlite3.Connection) -> None:
        upsert_entity_type(
            conn,
            EntityTypeDef.model_validate(
                {"slug": "temp", "label": "tmp", "fields_schema": []}
            ),
        )
        deleted = delete_entity_type(conn, "temp")
        assert deleted is True
        assert get_entity_type(conn, "temp") is None


class TestRelationTypes:
    def test_upsert_and_get(self, conn: sqlite3.Connection) -> None:
        upsert_relation_type(
            conn,
            RelationTypeDef.model_validate(
                {
                    "slug": "blocks",
                    "label": "ブロックする",
                    "source_type_slug": "task",
                    "target_type_slug": "task",
                    "fields_schema": [],
                }
            ),
        )
        got = get_relation_type(conn, "blocks")
        assert got is not None
        assert got.source_type_slug == "task"
        assert got.target_type_slug == "task"

    def test_delete(self, conn: sqlite3.Connection) -> None:
        upsert_relation_type(
            conn,
            RelationTypeDef.model_validate(
                {"slug": "tmp_rel", "label": "tmp", "fields_schema": []}
            ),
        )
        assert delete_relation_type(conn, "tmp_rel") is True
        assert get_relation_type(conn, "tmp_rel") is None


class TestRegistryHash:
    def test_changes_when_an_entity_type_is_updated(self, conn: sqlite3.Connection) -> None:
        before = registry_hash(conn)
        upsert_entity_type(
            conn,
            EntityTypeDef.model_validate(
                {"slug": "person", "label": "Person (renamed)", "fields_schema": []}
            ),
        )
        after = registry_hash(conn)
        assert before != after

    def test_stable_when_nothing_changes(self, conn: sqlite3.Connection) -> None:
        assert registry_hash(conn) == registry_hash(conn)
