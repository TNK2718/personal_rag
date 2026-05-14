"""FieldSpec parsing, validation, and dynamic-model generation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docdb.typing.field_spec import (
    FieldSpec,
    build_dynamic_model,
    parse_fields_schema,
    validate_fields,
)


# ---------------------------------------------------------------------------
# parse_fields_schema
# ---------------------------------------------------------------------------
class TestParseFieldsSchema:
    def test_parses_empty_array(self) -> None:
        assert parse_fields_schema("[]") == []

    def test_parses_known_types(self) -> None:
        raw = """[
          {"name":"title","label":"Title","type":"string"},
          {"name":"status","label":"Status","type":"enum","required":true,
           "options":["a","b"],"default":"a"},
          {"name":"due","label":"Due","type":"date"}
        ]"""
        specs = parse_fields_schema(raw)
        assert [s.name for s in specs] == ["title", "status", "due"]
        assert [s.type for s in specs] == ["string", "enum", "date"]
        # The enum spec carries options
        enum_spec = specs[1]
        assert getattr(enum_spec, "options", None) == ["a", "b"]

    def test_rejects_missing_options_for_enum(self) -> None:
        raw = '[{"name":"s","label":"S","type":"enum"}]'
        with pytest.raises(ValidationError):
            parse_fields_schema(raw)

    def test_rejects_duplicate_field_names(self) -> None:
        raw = """[
          {"name":"x","label":"X","type":"string"},
          {"name":"x","label":"X2","type":"int"}
        ]"""
        with pytest.raises(ValueError):
            parse_fields_schema(raw)

    def test_rejects_non_snake_case_name(self) -> None:
        # Field names must be JSON-key safe and stable. We reject anything
        # that isn't a python identifier-style slug.
        raw = '[{"name":"With Space","label":"x","type":"string"}]'
        with pytest.raises(ValidationError):
            parse_fields_schema(raw)


# ---------------------------------------------------------------------------
# validate_fields (semantic)
# ---------------------------------------------------------------------------
class TestValidateFields:
    @pytest.fixture
    def task_specs(self) -> list[FieldSpec]:
        return parse_fields_schema(
            """[
              {"name":"status","label":"Status","type":"enum","required":true,
               "options":["pending","done"],"default":"pending"},
              {"name":"priority","label":"P","type":"enum","required":false,
               "options":["high","low"]},
              {"name":"due","label":"Due","type":"date","required":false}
            ]"""
        )

    def test_accepts_valid_payload(self, task_specs: list[FieldSpec]) -> None:
        out = validate_fields(task_specs, {"status": "done", "priority": "high", "due": "2026-05-20"})
        assert out == {"status": "done", "priority": "high", "due": "2026-05-20"}

    def test_fills_default_for_missing_required_enum(self, task_specs: list[FieldSpec]) -> None:
        out = validate_fields(task_specs, {})
        assert out["status"] == "pending"

    def test_rejects_unknown_enum_value(self, task_specs: list[FieldSpec]) -> None:
        with pytest.raises(ValueError):
            validate_fields(task_specs, {"status": "bogus"})

    def test_drops_unknown_field(self, task_specs: list[FieldSpec]) -> None:
        out = validate_fields(task_specs, {"status": "pending", "extraneous": "x"})
        assert "extraneous" not in out

    def test_coerces_empty_string_to_none_for_optional(self, task_specs: list[FieldSpec]) -> None:
        out = validate_fields(task_specs, {"due": ""})
        assert out.get("due") is None

    def test_rejects_malformed_date(self, task_specs: list[FieldSpec]) -> None:
        with pytest.raises(ValueError):
            validate_fields(task_specs, {"due": "not-a-date"})


# ---------------------------------------------------------------------------
# build_dynamic_model
# ---------------------------------------------------------------------------
class TestBuildDynamicModel:
    def test_round_trips_minimal_payload(self) -> None:
        specs = parse_fields_schema('[{"name":"x","label":"X","type":"string"}]')
        Model = build_dynamic_model("EntityFieldsTest1", specs)
        obj = Model(x="hello")
        assert obj.x == "hello"  # type: ignore[attr-defined]

    def test_enum_field_rejects_invalid_option(self) -> None:
        specs = parse_fields_schema(
            '[{"name":"s","label":"S","type":"enum","required":true,"options":["a","b"]}]'
        )
        Model = build_dynamic_model("EntityFieldsTest2", specs)
        with pytest.raises(ValidationError):
            Model(s="c")

    def test_optional_field_defaults_to_none(self) -> None:
        specs = parse_fields_schema('[{"name":"y","label":"Y","type":"int","required":false}]')
        Model = build_dynamic_model("EntityFieldsTest3", specs)
        obj = Model()
        assert obj.y is None  # type: ignore[attr-defined]

    def test_each_primitive_type_round_trips(self) -> None:
        # Exhaustive matrix across the seven non-enum primitives.
        cases = [
            ("string", "abc"),
            ("text", "long\nstring"),
            ("int", 7),
            ("float", 1.5),
            ("bool", True),
            ("date", "2026-05-20"),
            ("datetime", "2026-05-20T12:00:00Z"),
            ("url", "https://example.com"),
        ]
        for kind, value in cases:
            specs = parse_fields_schema(
                f'[{{"name":"f","label":"F","type":"{kind}","required":true}}]'
            )
            Model = build_dynamic_model(f"EntityFieldsPrim_{kind}", specs)
            obj = Model(f=value)
            assert obj.f == value  # type: ignore[attr-defined]

    def test_ref_field_accepts_entity_id(self) -> None:
        specs = parse_fields_schema(
            '[{"name":"owner","label":"Owner","type":"ref","ref_type_slug":"person"}]'
        )
        Model = build_dynamic_model("EntityFieldsRef", specs)
        obj = Model(owner="ent-abcdef012345")
        assert obj.owner == "ent-abcdef012345"  # type: ignore[attr-defined]
