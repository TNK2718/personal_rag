"""Per-call dynamic ``ExtractionResult`` Pydantic model.

The LLM extraction layer needs a concrete ``pydantic.BaseModel`` at call time
(``instructor`` requires a class). Stage 3 keeps that contract but generates
the class from the runtime type registry so that user-defined entity types
and relation types appear in the LLM-facing JSON schema.

Output envelope:

    {
        "doc_type": "memo",
        "title": "...",
        "summary": "...",
        "language": "ja",
        "tags": [...],
        "entities": [
            {"type": "task", "name": "...", "aliases": [], "fields": {...}}
        ],
        "relations": [                            // only when ≥1 relation type
            {"type": "assigned_to",
             "source": {"type": "task", "name": "..."},
             "target": {"type": "person", "name": "..."},  // or null when unknown
             "fields": {}}
        ]
    }

The ``type`` slugs are constrained to a ``Literal`` of the registered slugs so
the LLM cannot hallucinate a brand new type. Field-value validation happens
later, in ``DocumentStore.upsert_entity`` (which knows the type's full schema).
"""

from __future__ import annotations

from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from docdb.models import ExtractionResult


# ---------------------------------------------------------------------------
# LLM-facing item shapes
# ---------------------------------------------------------------------------
class ExtractedEntityBase(BaseModel):
    """Common fields for every extracted entity (the ``type`` field is filled in
    dynamically with a ``Literal`` of registered slugs)."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    fields: dict[str, Any] = Field(default_factory=dict)


class ExtractedEntityRef(BaseModel):
    """Reference used as ``source`` / ``target`` inside an ExtractedRelation."""

    model_config = ConfigDict(extra="ignore")

    type: str
    name: str


class ExtractedRelationBase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: ExtractedEntityRef
    # target is intentionally nullable: small LLMs honestly emit
    # `{"target": null}` when the source text does not name a counterpart
    # (e.g. an unassigned task). Forcing it would push models to either
    # fabricate a target or drop the whole extraction; both are worse than
    # letting the normaliser discard the dangling relation downstream.
    target: ExtractedEntityRef | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_CACHE: dict[str, type[BaseModel]] = {}
_LOCK = Lock()


def build_extraction_model(
    *,
    entity_type_slugs: list[str],
    relation_type_slugs: list[str],
    registry_hash: str,
) -> type[BaseModel]:
    """Return a dynamically-constructed Pydantic model for LLM extraction.

    ``registry_hash`` keys the cache; pass the value returned by
    ``docdb.typing.registry.registry_hash`` so callers don't have to think
    about invalidation.

    When no entity types are registered the bare ``ExtractionResult`` is
    returned, so the LLM is asked only to extract doc-level metadata + tags.
    """
    if not entity_type_slugs:
        return ExtractionResult

    cached = _CACHE.get(registry_hash)
    if cached is not None:
        return cached

    with _LOCK:
        cached = _CACHE.get(registry_hash)
        if cached is not None:
            return cached

        suffix = registry_hash[:8]
        entity_literal = _literal_of(entity_type_slugs)

        # ExtractedEntity_<hash> = ExtractedEntityBase + type: Literal[slugs]
        EntityModel = create_model(  # type: ignore[call-overload]
            f"ExtractedEntity_{suffix}",
            __base__=ExtractedEntityBase,
            type=(entity_literal, ...),
        )

        extras: dict[str, tuple[Any, Any]] = {
            "entities": (list[EntityModel], Field(default_factory=list)),
        }

        if relation_type_slugs:
            relation_literal = _literal_of(relation_type_slugs)
            RelationModel = create_model(  # type: ignore[call-overload]
                f"ExtractedRelation_{suffix}",
                __base__=ExtractedRelationBase,
                type=(relation_literal, ...),
            )
            extras["relations"] = (list[RelationModel], Field(default_factory=list))

        ResultModel = create_model(  # type: ignore[call-overload]
            f"ExtractionResult_{suffix}",
            __base__=ExtractionResult,
            **extras,
        )
        _CACHE[registry_hash] = ResultModel
        return ResultModel


def _literal_of(values: list[str]):
    """Build a ``typing.Literal[...]`` from a runtime list of strings.

    ``Literal[tuple(values)]`` is the runtime-equivalent of
    ``Literal['a', 'b', ...]`` because ``Literal.__class_getitem__`` accepts a
    tuple. We assume the caller has already filtered out duplicates.
    """
    if not values:
        # An empty Literal would be invalid. Caller guards this case; this
        # raise is defensive only.
        raise ValueError("cannot build Literal from an empty list")
    return Literal[tuple(values)]  # type: ignore[valid-type]


def clear_cache() -> None:
    """Reset the model cache. Useful for tests that mutate the registry."""
    with _LOCK:
        _CACHE.clear()
