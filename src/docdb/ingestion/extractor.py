"""LLM-driven metadata extraction.

Takes a ``ParsedDocument`` and asks an ``LLMProtocol`` to fill an
``ExtractionResult``. Stage 3 makes both the system prompt and the
Pydantic schema dynamic: at construction time the extractor receives the
runtime entity/relation type registry plus its hash, builds the
schema-aware system prompt and the dynamic Pydantic class, and reuses
both for every call.

The extractor is intentionally thin:
    * one LLM call per document (a single document = one ingestion unit)
    * input truncated to ``max_input_chars`` so prompts stay bounded
    * recovery: on any LLM error, return an empty ``ExtractionResult``
      together with the error message in ``last_error`` so the pipeline
      can still write the raw document without losing the source
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from docdb.ingestion.parser import ParsedDocument
from docdb.llm.base import LLMProtocol
from docdb.llm.prompts import (
    build_extraction_system_prompt,
    build_extraction_user_prompt,
)
from docdb.models import ExtractionResult
from docdb.typing.dynamic_model import build_extraction_model
from docdb.typing.registry import EntityTypeDef, RelationTypeDef


@dataclass
class ExtractionOutcome:
    result: ExtractionResult
    prompt: str
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class Extractor:
    def __init__(
        self,
        llm: LLMProtocol,
        *,
        max_input_chars: int = 8000,
        entity_types: list[EntityTypeDef] | None = None,
        relation_types: list[RelationTypeDef] | None = None,
        registry_hash: str = "",
    ) -> None:
        self.llm = llm
        self.max_input_chars = max_input_chars
        self.entity_types: list[EntityTypeDef] = list(entity_types or [])
        self.relation_types: list[RelationTypeDef] = list(relation_types or [])
        self._registry_hash = registry_hash
        self._system_prompt = build_extraction_system_prompt(
            self.entity_types, self.relation_types
        )
        entity_slugs = [t.slug for t in self.entity_types]
        relation_slugs = [t.slug for t in self.relation_types]
        self._schema_class: type[BaseModel] = build_extraction_model(
            entity_type_slugs=entity_slugs,
            relation_type_slugs=relation_slugs,
            registry_hash=registry_hash or "static",
        )

    @property
    def schema_class(self) -> type[BaseModel]:
        return self._schema_class

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def extract(self, parsed: ParsedDocument) -> ExtractionOutcome:
        prompt = build_extraction_user_prompt(
            parsed,
            max_body_chars=self.max_input_chars,
            system_prompt=self._system_prompt,
        )
        try:
            result = self.llm.extract(prompt, self._schema_class)
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            return ExtractionOutcome(
                result=self._schema_class(  # type: ignore[call-arg]
                    title=parsed.title or "",
                    summary="",
                ),
                prompt=prompt,
                error=f"{type(exc).__name__}: {exc}",
            )

        if not getattr(result, "title", None) and parsed.title:
            result.title = parsed.title  # type: ignore[assignment]
        return ExtractionOutcome(result=result, prompt=prompt)
