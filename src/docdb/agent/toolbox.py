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
from docdb.models import Citation, Document, Entity, Relation
from docdb.search import direct
from docdb.search.hybrid import hybrid_search
from docdb.search.sql_guard import UnsafeQueryError, validate_readonly_sql
from docdb.search.text2sql import ALLOWED_TABLES, run_text2sql
from docdb.typing.registry import list_entity_types, list_relation_types


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
    ) -> None:
        self.conn = conn
        self.llm = llm
        self.embedder = embedder or llm
        self.max_results = max_results
        self.max_sql_limit = max_sql_limit
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
                name="search_documents",
                description=(
                    "Search the corpus by query. Uses FTS5 by default; set "
                    "`hybrid=true` to fuse with vector similarity (slower "
                    "but better recall on paraphrases)."
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
                        "hybrid": {"type": "boolean", "default": False},
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
                name="list_doc_types",
                description="Return counts of documents per doc_type.",
                parameters={"type": "object", "properties": {}},
            ),
            ToolSpec(
                name="list_entity_types",
                description=(
                    "Return every registered entity type with its slug, label, and "
                    "fields_schema. Call this before search_entities when the user "
                    "asks about a kind of thing (tasks, people, meetings, ...) so "
                    "you know what type_slug to filter by and which custom fields "
                    "exist."
                ),
                parameters={"type": "object", "properties": {}},
            ),
            ToolSpec(
                name="list_relation_types",
                description="Return every registered relation type with its slug and endpoints.",
                parameters={"type": "object", "properties": {}},
            ),
            ToolSpec(
                name="search_entities",
                description=(
                    "Find entities by partial canonical name, optionally filtered "
                    "by type_slug. The set of valid type slugs comes from "
                    "list_entity_types — it is NOT a fixed enum."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "name_partial": {"type": "string"},
                        "type_slug": {
                            "type": "string",
                            "description": "Slug from list_entity_types (e.g. 'task', 'person').",
                        },
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    },
                    "required": ["name_partial"],
                },
            ),
            ToolSpec(
                name="get_entity_documents",
                description="Return documents that mention a given entity_id.",
                parameters={
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                    },
                    "required": ["entity_id"],
                },
            ),
            ToolSpec(
                name="search_relations",
                description=(
                    "Find relations (property-graph edges) by source/target entity id "
                    "and/or relation type_slug. Useful for questions like "
                    "'who is assigned to X' or 'what tasks does Alice own'."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "source_entity_id": {"type": "string"},
                        "target_entity_id": {"type": "string"},
                        "type_slug": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                    },
                },
            ),
            ToolSpec(
                name="text_to_sql",
                description=(
                    "Translate a natural-language question into a safe read-only "
                    "SELECT against documents / entities / relations / tags and "
                    "run it. Prefer this over `execute_readonly_sql` for any "
                    "cross-table aggregation, count, LIKE search, or schema-aware "
                    "filter — the underlying prompt is given the full schema, so "
                    "column names won't be hallucinated. The natural-language "
                    "question is passed straight through; do not write SQL here."
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
            "search_documents": self._search_documents,
            "find_similar": self._find_similar,
            "get_document": self._get_document,
            "list_doc_types": self._list_doc_types,
            "list_entity_types": self._list_entity_types,
            "list_relation_types": self._list_relation_types,
            "search_entities": self._search_entities,
            "get_entity_documents": self._get_entity_documents,
            "search_relations": self._search_relations,
            "text_to_sql": self._text_to_sql,
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
        hybrid: bool = False,
    ) -> list[dict]:
        top_k = min(int(top_k), self.max_results)
        if hybrid:
            [embedding] = self.embedder.embed([query])
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

    def _list_doc_types(self) -> list[dict]:
        return [
            {"doc_type": name, "count": count}
            for name, count in direct.list_doc_types(self.conn)
        ]

    def _list_entity_types(self) -> list[dict]:
        return [
            {
                "slug": t.slug,
                "label": t.label,
                "description": t.description,
                "fields": [f.model_dump(exclude_none=True) for f in t.fields],
            }
            for t in list_entity_types(self.conn)
        ]

    def _list_relation_types(self) -> list[dict]:
        return [
            {
                "slug": t.slug,
                "label": t.label,
                "description": t.description,
                "source_type_slug": t.source_type_slug,
                "target_type_slug": t.target_type_slug,
            }
            for t in list_relation_types(self.conn)
        ]

    def _search_entities(
        self,
        name_partial: str,
        type_slug: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        top_k = min(int(top_k), self.max_results)
        return [
            _entity_to_dict(e)
            for e in direct.search_entities(
                self.conn, name_partial, type_slug=type_slug, top_k=top_k
            )
        ]

    def _get_entity_documents(self, entity_id: str, top_k: int = 20) -> list[dict]:
        top_k = min(int(top_k), self.max_results)
        return [
            _document_to_dict(d)
            for d in direct.get_entity_documents(self.conn, entity_id, top_k=top_k)
        ]

    def _search_relations(
        self,
        source_entity_id: str | None = None,
        target_entity_id: str | None = None,
        type_slug: str | None = None,
        top_k: int = 50,
    ) -> list[dict]:
        top_k = min(int(top_k), self.max_results)
        return [
            _relation_to_dict(r)
            for r in direct.search_relations(
                self.conn,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                type_slug=type_slug,
                top_k=top_k,
            )
        ]

    def _text_to_sql(self, question: str) -> dict:
        result = run_text2sql(
            self.conn,
            question,
            self.llm,
            max_limit=self.max_sql_limit,
            max_rows=self.max_sql_limit,
        )
        return {
            "sql": result.validated_sql or result.sql,
            "reasoning": result.reasoning,
            "rows": result.rows,
            "error": result.error,
        }

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
# Citation / Document / Entity → dict
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


def _entity_to_dict(e: Entity) -> dict:
    return e.model_dump()


def _relation_to_dict(r: Relation) -> dict:
    return r.model_dump()
