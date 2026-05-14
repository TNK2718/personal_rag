"""Common LLM protocol used by both the real and the fake implementations.

The rest of the codebase (extractor, agent loop, server) accepts an
``LLMProtocol``. Tests construct a ``FakeLLM``; production wires up a
real ``LLM``. This keeps the I/O-heavy bits behind a tight seam.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


@runtime_checkable
class LLMProtocol(Protocol):
    def extract(self, text: str, schema: type[SchemaT]) -> SchemaT: ...

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        model: str | None = None,
    ) -> Any: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
