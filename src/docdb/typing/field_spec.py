"""FieldSpec: the schema-of-schema for user-definable entity / relation fields.

Each ``entity_types.fields_schema`` row is a JSON array of FieldSpec entries.
Ten primitive types are supported (``string`` ... ``ref``); the renderer on
the frontend dispatches on ``type`` and produces the right widget.

Two services live here:

- ``parse_fields_schema`` / ``validate_fields`` — used by the server
  (Stage 1 type CRUD and Stage 2 entity CRUD) to ensure that a user-supplied
  ``fields_schema`` (or a payload conforming to one) is well-formed.

- ``build_dynamic_model`` — used by the LLM extraction layer (Stage 3) to
  produce a concrete ``pydantic.BaseModel`` per type, since ``instructor``
  requires a class at call time. The class is keyed by ``model_name`` so the
  caller can avoid Pydantic / instructor schema cache collisions.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    create_model,
    field_validator,
)


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class _BaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    required: bool = False
    default: Any | None = None
    ui_widget: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(
                f"field name must be snake_case (lowercase letters, digits, underscores; "
                f"start with letter): got {v!r}"
            )
        return v


class FieldSpecString(_BaseSpec):
    type: Literal["string"]


class FieldSpecText(_BaseSpec):
    type: Literal["text"]


class FieldSpecInt(_BaseSpec):
    type: Literal["int"]


class FieldSpecFloat(_BaseSpec):
    type: Literal["float"]


class FieldSpecBool(_BaseSpec):
    type: Literal["bool"]


class FieldSpecDate(_BaseSpec):
    type: Literal["date"]


class FieldSpecDateTime(_BaseSpec):
    type: Literal["datetime"]


class FieldSpecEnum(_BaseSpec):
    type: Literal["enum"]
    options: list[str] = Field(min_length=1)


class FieldSpecUrl(_BaseSpec):
    type: Literal["url"]


class FieldSpecRef(_BaseSpec):
    type: Literal["ref"]
    ref_type_slug: str | None = None


FieldSpec = Annotated[
    Union[
        FieldSpecString,
        FieldSpecText,
        FieldSpecInt,
        FieldSpecFloat,
        FieldSpecBool,
        FieldSpecDate,
        FieldSpecDateTime,
        FieldSpecEnum,
        FieldSpecUrl,
        FieldSpecRef,
    ],
    Field(discriminator="type"),
]


_SpecListAdapter: TypeAdapter[list[FieldSpec]] = TypeAdapter(list[FieldSpec])


def parse_fields_schema(raw: str | list[dict]) -> list[FieldSpec]:
    """Validate a raw fields_schema (JSON string or python list) into FieldSpec objects.

    Raises ``pydantic.ValidationError`` for type errors and ``ValueError`` for
    cross-field issues (e.g., duplicate names).
    """
    payload = json.loads(raw) if isinstance(raw, str) else raw
    specs = _SpecListAdapter.validate_python(payload)
    seen: set[str] = set()
    for spec in specs:
        if spec.name in seen:
            raise ValueError(f"duplicate field name in fields_schema: {spec.name!r}")
        seen.add(spec.name)
    return specs


def dump_fields_schema(specs: list[FieldSpec]) -> str:
    """Serialize a FieldSpec list back to a JSON string for persistence."""
    return json.dumps([s.model_dump(exclude_none=True) for s in specs], ensure_ascii=False)


# ---------------------------------------------------------------------------
# Semantic validation of a payload against a fields_schema.
# ---------------------------------------------------------------------------
def validate_fields(specs: list[FieldSpec], payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a JSON payload against a fields_schema.

    Behaviour:
    - Unknown keys in ``payload`` are dropped (forward-compatible).
    - Missing optional fields default to ``None``.
    - Missing required fields fall back to the spec ``default`` if present;
      otherwise ``ValueError`` is raised.
    - Empty strings on optional fields coerce to ``None``.
    - Type-specific coercion is delegated to ``_coerce_value``.

    Returns a fresh dict containing only the validated values.
    """
    out: dict[str, Any] = {}
    for spec in specs:
        raw_value = payload.get(spec.name)

        if isinstance(raw_value, str) and raw_value == "" and not spec.required:
            raw_value = None

        if raw_value is None and spec.default is not None:
            raw_value = spec.default

        if raw_value is None:
            if spec.required:
                raise ValueError(f"missing required field: {spec.name!r}")
            out[spec.name] = None
            continue

        out[spec.name] = _coerce_value(spec, raw_value)
    return out


def _coerce_value(spec: Any, value: Any) -> Any:
    t = spec.type
    if t in ("string", "text"):
        if not isinstance(value, str):
            raise ValueError(f"{spec.name}: expected string, got {type(value).__name__}")
        return value
    if t == "int":
        if isinstance(value, bool):  # bool is a subclass of int — reject explicitly
            raise ValueError(f"{spec.name}: expected int, got bool")
        try:
            return int(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{spec.name}: expected int ({exc})")
    if t == "float":
        if isinstance(value, bool):
            raise ValueError(f"{spec.name}: expected float, got bool")
        try:
            return float(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{spec.name}: expected float ({exc})")
    if t == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{spec.name}: expected bool")
        return value
    if t == "date":
        if not isinstance(value, str):
            raise ValueError(f"{spec.name}: expected date string")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{spec.name}: invalid ISO date ({exc})")
        return value
    if t == "datetime":
        if not isinstance(value, str):
            raise ValueError(f"{spec.name}: expected datetime string")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{spec.name}: invalid ISO datetime ({exc})")
        return value
    if t == "enum":
        if value not in spec.options:
            raise ValueError(f"{spec.name}: value {value!r} not in options {spec.options!r}")
        return value
    if t == "url":
        if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
            return value
        raise ValueError(f"{spec.name}: expected http(s) URL")
    if t == "ref":
        if not isinstance(value, str) or not value:
            raise ValueError(f"{spec.name}: expected entity id string")
        return value
    raise ValueError(f"{spec.name}: unknown field type {t!r}")


# ---------------------------------------------------------------------------
# Dynamic Pydantic model construction (for LLM extraction).
# ---------------------------------------------------------------------------
def build_dynamic_model(model_name: str, specs: list[FieldSpec]) -> type[BaseModel]:
    """Construct a Pydantic model class whose fields mirror the spec list."""
    field_defs: dict[str, tuple[Any, Any]] = {}
    for spec in specs:
        py_type, default = _python_field(spec)
        field_defs[spec.name] = (py_type, default)
    return create_model(model_name, **field_defs)  # type: ignore[call-overload]


def _python_field(spec: Any) -> tuple[Any, Any]:
    t = spec.type
    if t in ("string", "text", "url", "date", "datetime", "ref"):
        py: Any = str
    elif t == "int":
        py = int
    elif t == "float":
        py = float
    elif t == "bool":
        py = bool
    elif t == "enum":
        py = Literal[tuple(spec.options)]  # type: ignore[valid-type]
    else:
        raise ValueError(f"unknown field type: {t!r}")

    optional = not spec.required
    if optional:
        py = py | None  # type: ignore[operator]
        default = spec.default
    else:
        default = spec.default if spec.default is not None else ...

    return py, default
