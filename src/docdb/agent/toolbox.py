"""Tool definitions and dispatch for the search agent.

A ``Toolbox`` instance wraps a SQLite connection and an LLM (for
Text2SQL). Each tool is declared with a JSON Schema parameter set so
the model receives the same descriptions OpenAI's tool API expects;
the matching Python handler validates the arguments and runs the
operation, then encodes the result back to a JSON string the LLM can
consume.

Why everything is one class:

* The agent loop only sees ``Toolbox.openai_tools()`` and
  ``Toolbox.invoke(name, arguments_json)`` — that's the entire seam.
* The conn + llm dependency injection lives in one place; tests can
  swap the LLM for a FakeLLM and the conn for an in-memory DB.
* Tools share helpers (Citation → dict, Document → dict) so the agent
  never has to peer inside Pydantic models.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from docdb.llm.base import LLMProtocol
from docdb.models import Citation, Document
from docdb.search import direct
from docdb.search.hybrid import hybrid_search
from docdb.search.sql_guard import UnsafeQueryError, validate_readonly_sql
from docdb.search.text2sql import ALLOWED_TABLES, run_text2sql
from docdb.typing.registry import (
    get_entity_type,
    get_relation_type,
    list_entity_types,
    list_relation_types,
)


# ---------------------------------------------------------------------------
# Spec / invocation records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema (object)

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolInvocation:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    result_json: str = "null"
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# Toolbox
# ---------------------------------------------------------------------------
Handler = Callable[..., Any]


class Toolbox:
    def __init__(
        self,
        conn: sqlite3.Connection,
        llm: LLMProtocol,
        *,
        embedder: LLMProtocol | None = None,
        max_results: int = 20,
        max_sql_limit: int = 100,
        text2sql_prompt_max_bytes: int = 30_000,
        query_resolution_enabled: bool = True,
        query_resolution_top_k: int = 15,
        query_resolution_distance: float = 0.55,
    ) -> None:
        self.conn = conn
        self.llm = llm
        self.embedder = embedder or llm
        self.max_results = max_results
        self.max_sql_limit = max_sql_limit
        self.text2sql_prompt_max_bytes = text2sql_prompt_max_bytes
        self.query_resolution_enabled = query_resolution_enabled
        self.query_resolution_top_k = query_resolution_top_k
        self.query_resolution_distance = query_resolution_distance
        self._specs, self._handlers = self._build()

    # -- Public surface ----------------------------------------------------
    def specs(self) -> list[ToolSpec]:
        return list(self._specs)

    def openai_tools(self) -> list[dict]:
        return [s.to_openai() for s in self._specs]

    def invoke(self, name: str, arguments_json: str | dict) -> ToolInvocation:
        """Dispatch ``name`` with parsed ``arguments_json``.

        ``arguments_json`` accepts either a JSON-encoded string (what
        OpenAI tool-calling delivers) or an already-parsed dict (handy
        for tests).
        """
        if isinstance(arguments_json, dict):
            args = arguments_json
        else:
            try:
                args = json.loads(arguments_json) if arguments_json else {}
            except json.JSONDecodeError as exc:
                return ToolInvocation(
                    name=name, error=f"invalid JSON arguments: {exc}"
                )

        handler = self._handlers.get(name)
        if handler is None:
            return ToolInvocation(
                name=name, arguments=args, error=f"unknown tool: {name}"
            )

        try:
            result = handler(**args)
        except TypeError as exc:
            return ToolInvocation(
                name=name,
                arguments=args,
                error=f"bad arguments for {name}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return ToolInvocation(
                name=name,
                arguments=args,
                error=f"{type(exc).__name__}: {exc}",
            )

        encoded = json.dumps(result, ensure_ascii=False, default=str)
        return ToolInvocation(
            name=name, arguments=args, result=result, result_json=encoded
        )

    # -- Tool definitions --------------------------------------------------
    def _build(self) -> tuple[list[ToolSpec], dict[str, Handler]]:
        specs: list[ToolSpec] = [
            ToolSpec(
                name="text_to_sql",
                description=(
                    "**Default tool for any structured query.** Translate a "
                    "natural-language question into a safe read-only SELECT "
                    "against documents / entities / relations / tags and run "
                    "it. The schema (every entity/relation type slug and its "
                    "fields) is injected into the prompt automatically — you "
                    "do NOT need to look up table or column names first. Try "
                    "this first for any question involving counts, filters, "
                    "joins, type-based conditions (tasks/meetings/people/…), "
                    "date ranges, or LIKE matches. Only fall back to "
                    "`search_documents` when the question requires free-text "
                    "semantic matching (paraphrase / concept search) that SQL "
                    "cannot express. The natural-language question is passed "
                    "straight through; do NOT write SQL here."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The natural-language question to translate into SQL.",
                        }
                    },
                    "required": ["question"],
                },
            ),
            ToolSpec(
                name="search_documents",
                description=(
                    "Free-text semantic / lexical search **fallback** for "
                    "questions SQL cannot express (paraphrase, concept search, "
                    "fuzzy body matches). Prefer `text_to_sql` for any "
                    "structured filter or aggregation. By default fuses FTS5 "
                    "with vector similarity (RRF). Set `hybrid=false` to skip "
                    "the embed call and run pure FTS. If the embedder is "
                    "unavailable, falls back to FTS automatically."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                        "doc_type": {
                            "type": "string",
                            "enum": ["memo", "meeting", "journal", "reference", "spec", "other"],
                        },
                        "date_from": {"type": "string", "description": "ISO YYYY-MM-DD lower bound"},
                        "date_to": {"type": "string", "description": "ISO YYYY-MM-DD upper bound"},
                        "hybrid": {"type": "boolean", "default": True},
                    },
                    "required": ["query"],
                },
            ),
            ToolSpec(
                name="find_similar",
                description="Return documents semantically similar to a given document_id.",
                parameters={
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                    },
                    "required": ["document_id"],
                },
            ),
            ToolSpec(
                name="get_document",
                description="Fetch a single document by id, including raw text.",
                parameters={
                    "type": "object",
                    "properties": {"document_id": {"type": "string"}},
                    "required": ["document_id"],
                },
            ),
            ToolSpec(
                name="describe_schema",
                description=(
                    "Inspect the catalog of entity types, relation types, and "
                    "doc types. Default returns a compact summary (slug, label, "
                    "counts; no per-field schema). Pass `kind` to scope to one "
                    "catalog, and `kind`+`slug` to drill into a single type and "
                    "get its full fields_schema / endpoints. Call this before "
                    "search_entities when the user asks about a kind of thing "
                    "(tasks, people, meetings, ...) so you know which type_slug "
                    "to filter by."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["entities", "relations", "doc_types"],
                            "description": "Restrict the result to one catalog. Omit for a full summary.",
                        },
                        "slug": {
                            "type": "string",
                            "description": (
                                "Drill into one type and return its full "
                                "fields_schema (entities) or endpoints "
                                "(relations). Requires `kind` to be 'entities' "
                                "or 'relations'."
                            ),
                        },
                    },
                },
            ),
            ToolSpec(
                name="execute_readonly_sql",
                description=(
                    "Last-resort escape hatch: execute a hand-crafted SELECT "
                    "against the schema. Prefer `text_to_sql` unless you have a "
                    "very specific query you want to run verbatim. Tables: "
                    "documents(id, title, raw_text, summary, doc_type, ...), "
                    "entities(id, type_slug, canonical_name, fields JSON), "
                    "relations(id, type_slug, source_entity_id, target_entity_id). "
                    "FTS via documents_fts MATCH 'word'. SELECT-only, allowlisted "
                    "tables, auto LIMIT."
                ),
                parameters={
                    "type": "object",
                    "properties": {"sql": {"type": "string"}},
                    "required": ["sql"],
                },
            ),
        ]

        handlers: dict[str, Handler] = {
            "text_to_sql": self._text_to_sql,
            "search_documents": self._search_documents,
            "get_document": self._get_document,
            "find_similar": self._find_similar,
            "describe_schema": self._describe_schema,
            "execute_readonly_sql": self._execute_readonly_sql,
        }
        return specs, handlers

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _search_documents(
        self,
        query: str,
        top_k: int = 10,
        doc_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        hybrid: bool = True,
    ) -> list[dict]:
        top_k = min(int(top_k), self.max_results)
        embedding: list[float] | None = None
        if hybrid:
            try:
                [embedding] = self.embedder.embed([query])
            except Exception:  # noqa: BLE001 — embedder offline; fall back to FTS
                embedding = None
        if hybrid and embedding is not None:
            hits = hybrid_search(
                self.conn,
                query,
                embedding=embedding,
                top_k=top_k,
                doc_type=doc_type,
                date_from=date_from,
                date_to=date_to,
            )
        else:
            hits = direct.search(
                self.conn,
                query,
                top_k=top_k,
                doc_type=doc_type,
                date_from=date_from,
                date_to=date_to,
            )
        return [_citation_to_dict(c) for c in hits]

    def _find_similar(self, document_id: str, top_k: int = 5) -> list[dict]:
        top_k = min(int(top_k), self.max_results)
        return [
            _citation_to_dict(c)
            for c in direct.find_similar(self.conn, document_id, top_k=top_k)
        ]

    def _get_document(self, document_id: str) -> dict | None:
        doc = direct.get_document(self.conn, document_id)
        return _document_to_dict(doc) if doc else None

    def _describe_schema(
        self,
        kind: str | None = None,
        slug: str | None = None,
    ) -> dict:
        if slug is not None and kind not in ("entities", "relations"):
            return {"error": "slug requires kind to be 'entities' or 'relations'"}

        if kind == "entities":
            return {"entity_types": self._entity_types_payload(slug=slug)}
        if kind == "relations":
            return {"relation_types": self._relation_types_payload(slug=slug)}
        if kind == "doc_types":
            return {"doc_types": self._doc_types_payload()}

        return {
            "entity_types": self._entity_types_payload(),
            "relation_types": self._relation_types_payload(),
            "doc_types": self._doc_types_payload(),
        }

    def _entity_types_payload(self, *, slug: str | None = None) -> list[dict]:
        counts = direct.count_entities_by_type(self.conn)
        if slug is not None:
            t = get_entity_type(self.conn, slug)
            if t is None:
                return []
            return [
                {
                    "slug": t.slug,
                    "label": t.label,
                    "description": t.description,
                    "count": counts.get(t.slug, 0),
                    "fields": [f.model_dump(exclude_none=True) for f in t.fields],
                }
            ]
        return [
            {
                "slug": t.slug,
                "label": t.label,
                "count": counts.get(t.slug, 0),
            }
            for t in list_entity_types(self.conn)
        ]

    def _relation_types_payload(self, *, slug: str | None = None) -> list[dict]:
        if slug is not None:
            t = get_relation_type(self.conn, slug)
            if t is None:
                return []
            return [
                {
                    "slug": t.slug,
                    "label": t.label,
                    "description": t.description,
                    "source_type_slug": t.source_type_slug,
                    "target_type_slug": t.target_type_slug,
                    "fields": [f.model_dump(exclude_none=True) for f in t.fields],
                }
            ]
        return [
            {
                "slug": t.slug,
                "label": t.label,
                "source_type_slug": t.source_type_slug,
                "target_type_slug": t.target_type_slug,
            }
            for t in list_relation_types(self.conn)
        ]

    def _doc_types_payload(self) -> list[dict]:
        return [
            {"doc_type": name, "count": count}
            for name, count in direct.list_doc_types(self.conn)
        ]

    def _text_to_sql(self, question: str) -> dict:
        result = run_text2sql(
            self.conn,
            question,
            self.llm,
            max_limit=self.max_sql_limit,
            max_rows=self.max_sql_limit,
            max_prompt_bytes=self.text2sql_prompt_max_bytes,
            resolution_enabled=self.query_resolution_enabled,
            resolution_top_k=self.query_resolution_top_k,
            resolution_distance_threshold=self.query_resolution_distance,
        )
        payload: dict = {
            "sql": result.validated_sql or result.sql,
            "reasoning": result.reasoning,
            "rows": result.rows,
            "error": result.error,
        }
        # Only surfaced when the retry path fired; lets the agent
        # acknowledge the surface-form rewrite in its final answer.
        if result.rewritten_question:
            payload["rewritten_question"] = result.rewritten_question
        return payload

    def _execute_readonly_sql(self, sql: str) -> dict:
        try:
            safe = validate_readonly_sql(
                sql,
                allowed_tables=ALLOWED_TABLES,
                max_limit=self.max_sql_limit,
            )
        except UnsafeQueryError as exc:
            return {"error": f"unsafe sql: {exc}", "rows": []}
        try:
            cursor = self.conn.execute(safe)
            rows = cursor.fetchmany(self.max_sql_limit)
        except sqlite3.Error as exc:
            return {"error": f"sqlite error: {exc}", "rows": []}
        return {"sql": safe, "rows": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Citation / Document → dict
# ---------------------------------------------------------------------------
def _citation_to_dict(c: Citation) -> dict:
    return {
        "document_id": c.document_id,
        "title": c.title,
        "snippet": c.snippet,
        "score": c.score,
        "source_path": c.source_path,
        "doc_type": c.doc_type,
    }


def _document_to_dict(d: Document) -> dict:
    payload = d.model_dump()
    # raw_text can be large; the agent rarely needs more than a snippet.
    if payload.get("raw_text") and len(payload["raw_text"]) > 2000:
        payload["raw_text"] = payload["raw_text"][:2000] + "\n[... truncated ...]"
    return payload
