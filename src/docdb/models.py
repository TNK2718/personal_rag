"""Domain models for DocDB.

Two flavours coexist here:

1. Storage-shape models (``Document``, ``Entity``, ``Tag``, ``Todo``,
   ``Citation``) — what code that reads from SQLite returns.
2. Extraction-shape models (``Extracted*``, ``ExtractionResult``) — what
   the LLM is asked to produce. These define the JSON schema that
   instructor uses for structured outputs and are also re-used by tests
   via ``FakeLLM``.

Identifiers are deterministic where useful: document IDs and todo IDs
are derived from a content hash so that re-ingesting the same source
does not duplicate rows.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SourceType = Literal["md", "pdf", "docx", "pptx", "xlsx", "html", "txt"]
DocType = Literal["memo", "meeting", "journal", "reference", "spec", "other"]
EntityType = Literal["person", "org", "product", "tech", "place", "other"]
Language = Literal["ja", "en", "mixed", "other"]
TodoStatus = Literal["pending", "in_progress", "completed", "cancelled"]
Priority = Literal["high", "medium", "low"]


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
    model_config = ConfigDict(extra="ignore")

    id: str
    canonical_name: str
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    metadata: dict = Field(default_factory=dict)


class Tag(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    category: str | None = None


class Todo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    content: str
    status: TodoStatus = "pending"
    priority: Priority = "medium"
    due_date: str | None = None
    source_document_id: str | None = None
    source_section: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


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
class ExtractedEntity(BaseModel):
    name: str = Field(min_length=1)
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)


class ExtractedTodo(BaseModel):
    content: str = Field(min_length=1)
    priority: Priority = "medium"
    due_date: str | None = None


class ExtractionResult(BaseModel):
    """Single LLM call output for a whole document."""

    doc_type: DocType = "other"
    title: str = ""
    summary: str = Field(default="", max_length=600)
    language: Language = "ja"
    entities: list[ExtractedEntity] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    todos: list[ExtractedTodo] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic IDs
# ---------------------------------------------------------------------------
def document_id_for(content_hash: str) -> str:
    """Derive a document_id from the document's content hash."""
    return f"doc-{content_hash[:12]}"


def content_hash_for(text: str) -> str:
    """SHA-256 over the normalised text. Used as the dedup key."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def todo_id_for(source_document_id: str | None, content: str) -> str:
    src = source_document_id or "__free__"
    digest = hashlib.sha256(f"{src}\x1f{content}".encode("utf-8")).hexdigest()
    return f"todo-{digest[:12]}"


def entity_id_for(canonical_name: str, entity_type: str) -> str:
    digest = hashlib.sha256(f"{entity_type}\x1f{canonical_name}".encode("utf-8")).hexdigest()
    return f"ent-{digest[:12]}"


def tag_id_for(canonical_name: str) -> str:
    digest = hashlib.sha256(canonical_name.encode("utf-8")).hexdigest()
    return f"tag-{digest[:12]}"


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
