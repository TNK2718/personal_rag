"""Domain models for DocDB.

Two flavours coexist here:

1. Storage-shape models (``Document``, ``Entity``, ``Relation``, ``Tag``,
   ``Citation``) — what code that reads from SQLite returns.
2. Extraction-shape models (``Extracted*``, ``ExtractionResult``) — what
   the LLM is asked to produce. These define the JSON schema that
   instructor uses for structured outputs and are also re-used by tests
   via ``FakeLLM``.

Identifiers are deterministic where useful: document IDs and entity IDs are
derived from a content / (type, name) hash so that re-ingesting the same
source does not duplicate rows.

NOTE: Stage 2 of the property-graph redesign dropped the dedicated
``Todo`` model, the fixed ``EntityType`` / ``TodoStatus`` / ``Priority``
literals, and the related ``Extracted*`` shapes. Stage 3 will rebuild the
LLM extraction layer using ``docdb.typing.field_spec.build_dynamic_model``.
The legacy ``ExtractionResult`` is therefore a temporary shape with no
entities / todos field — the ingestion pipeline currently skips entity and
relation writes when ``Settings.extraction_legacy_skip`` is enabled.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SourceType = Literal["md", "pdf", "docx", "pptx", "xlsx", "html", "txt"]
DocType = Literal["memo", "meeting", "journal", "reference", "spec", "other"]
Language = Literal["ja", "en", "mixed", "other"]


# ---------------------------------------------------------------------------
# Storage-shape models
# ---------------------------------------------------------------------------
class Document(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    source_type: SourceType
    content_hash: str
    source_path: str | None = None
    source_uri: str | None = None
    title: str | None = None
    doc_type: DocType | None = None
    author: str | None = None
    created_at: str | None = None      # document content date, ISO 8601
    summary: str | None = None
    raw_text: str | None = None
    language: Language | None = None
    metadata: dict = Field(default_factory=dict)


class Entity(BaseModel):
    """Property-graph node.

    ``type_slug`` is a free string slug that must exist in ``entity_types``.
    ``fields`` is a free-form JSON object whose shape is governed by the
    referenced entity_type's ``fields_schema`` (validated in the store layer).
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    type_slug: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    fields: dict = Field(default_factory=dict)


class Relation(BaseModel):
    """Property-graph edge."""

    model_config = ConfigDict(extra="ignore")

    id: str
    type_slug: str
    source_entity_id: str
    target_entity_id: str
    fields: dict = Field(default_factory=dict)


class Tag(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    category: str | None = None


class Citation(BaseModel):
    """Search result row returned by the Direct API and the agent toolbox."""

    model_config = ConfigDict(extra="ignore")

    document_id: str
    title: str | None = None
    snippet: str | None = None
    score: float | None = None
    source_path: str | None = None
    doc_type: DocType | None = None


# ---------------------------------------------------------------------------
# Extraction-shape models (LLM structured-output schemas)
# ---------------------------------------------------------------------------
# Stage 2 leaves only the doc-level header here. Stage 3 will add a dynamic
# ``entities`` / ``relations`` envelope built from the type registry.
class ExtractionResult(BaseModel):
    """LLM call output for a whole document (header only, post-Stage-2)."""

    doc_type: DocType = "other"
    title: str = ""
    summary: str = Field(default="", max_length=600)
    language: Language = "ja"
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic IDs
# ---------------------------------------------------------------------------
def document_id_for(content_hash: str) -> str:
    """Derive a document_id from the document's content hash."""
    return f"doc-{content_hash[:12]}"


def content_hash_for(text: str) -> str:
    """SHA-256 over the normalised text. Used as the dedup key."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def entity_id_for(type_slug: str, canonical_name: str) -> str:
    digest = hashlib.sha256(f"{type_slug}\x1f{canonical_name}".encode("utf-8")).hexdigest()
    return f"ent-{digest[:12]}"


def relation_id_for(type_slug: str, source_entity_id: str, target_entity_id: str) -> str:
    digest = hashlib.sha256(
        f"{type_slug}\x1f{source_entity_id}\x1f{target_entity_id}".encode("utf-8")
    ).hexdigest()
    return f"rel-{digest[:12]}"


def tag_id_for(canonical_name: str) -> str:
    digest = hashlib.sha256(canonical_name.encode("utf-8")).hexdigest()
    return f"tag-{digest[:12]}"


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
