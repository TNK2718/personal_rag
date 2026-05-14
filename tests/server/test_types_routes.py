"""HTTP-level tests for the type registry CRUD endpoints."""

from __future__ import annotations


def test_list_entity_types_includes_seeds(client) -> None:
    res = client.get("/api/types/entities")
    assert res.status_code == 200
    body = res.get_json()
    slugs = {t["slug"] for t in body}
    assert {"person", "org", "place", "task"}.issubset(slugs)


def test_task_seed_carries_field_schema(client) -> None:
    res = client.get("/api/types/entities/task")
    assert res.status_code == 200
    body = res.get_json()
    field_names = [f["name"] for f in body["fields_schema"]]
    assert field_names == ["status", "priority", "due_date"]
    assert body["is_builtin"] is True


def test_get_unknown_returns_404(client) -> None:
    res = client.get("/api/types/entities/no-such-type")
    assert res.status_code == 404


def test_create_then_get(client) -> None:
    payload = {
        "slug": "decision",
        "label": "決定",
        "description": "会議で下された決定事項",
        "fields_schema": [
            {"name": "owner", "label": "Owner", "type": "ref", "ref_type_slug": "person"},
        ],
        "extraction_hint": "「決まった」「決定」などの文末を手掛かりに抽出",
    }
    res = client.post("/api/types/entities", json=payload)
    assert res.status_code == 201
    created = res.get_json()
    assert created["slug"] == "decision"
    assert created["is_builtin"] is False

    res = client.get("/api/types/entities/decision")
    assert res.status_code == 200


def test_create_with_invalid_field_spec_is_400(client) -> None:
    res = client.post(
        "/api/types/entities",
        json={
            "slug": "broken",
            "label": "broken",
            "fields_schema": [
                {"name": "needs options", "label": "x", "type": "enum"},
            ],
        },
    )
    assert res.status_code == 400


def test_create_duplicate_slug_is_409(client) -> None:
    res = client.post(
        "/api/types/entities",
        json={"slug": "person", "label": "duplicate", "fields_schema": []},
    )
    assert res.status_code == 409


def test_put_updates_existing(client) -> None:
    res = client.post(
        "/api/types/entities",
        json={"slug": "ticket", "label": "チケット", "fields_schema": []},
    )
    assert res.status_code == 201

    res = client.put(
        "/api/types/entities/ticket",
        json={"label": "Ticket (renamed)", "fields_schema": []},
    )
    assert res.status_code == 200
    assert res.get_json()["label"] == "Ticket (renamed)"


def test_put_unknown_returns_404(client) -> None:
    res = client.put(
        "/api/types/entities/ghost",
        json={"label": "ghost", "fields_schema": []},
    )
    assert res.status_code == 404


def test_delete_user_type(client) -> None:
    client.post(
        "/api/types/entities",
        json={"slug": "tmp_type", "label": "tmp", "fields_schema": []},
    )
    res = client.delete("/api/types/entities/tmp_type")
    assert res.status_code == 204
    assert client.get("/api/types/entities/tmp_type").status_code == 404


def test_delete_builtin_is_409(client) -> None:
    res = client.delete("/api/types/entities/person")
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# Relation types
# ---------------------------------------------------------------------------
def test_list_relation_types_includes_seeds(client) -> None:
    res = client.get("/api/types/relations")
    assert res.status_code == 200
    slugs = {t["slug"] for t in res.get_json()}
    assert {"assigned_to", "mentions"}.issubset(slugs)


def test_create_relation_type(client) -> None:
    res = client.post(
        "/api/types/relations",
        json={
            "slug": "blocks",
            "label": "ブロックする",
            "source_type_slug": "task",
            "target_type_slug": "task",
            "fields_schema": [],
        },
    )
    assert res.status_code == 201
    body = res.get_json()
    assert body["source_type_slug"] == "task"
    assert body["target_type_slug"] == "task"


def test_delete_builtin_relation_is_409(client) -> None:
    res = client.delete("/api/types/relations/mentions")
    assert res.status_code == 409
