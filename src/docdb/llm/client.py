"""Real LLM client backed by Ollama's OpenAI-compatible endpoint.

This class is the only place in the codebase that talks to Ollama. It
exposes three operations:

* ``extract``: structured JSON extraction via ``instructor`` and the
  configured ``extract_model``.
* ``chat_with_tools``: OpenAI tool-calling against the configured
  ``agent_model``.
* ``embed``: vector embeddings via the configured ``embed_model``.

The ``keep_alive`` setting is forwarded through ``extra_body`` so
qwen3 stays warm between successive requests (Ollama-specific knob
that survives the OpenAI compatibility layer).
"""

from __future__ import annotations

from typing import Any, TypeVar

import instructor
from openai import OpenAI
from pydantic import BaseModel

from docdb.config import Settings, get_settings


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLM:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._openai = OpenAI(
            base_url=self.settings.ollama_base_url,
            api_key="ollama",
        )
        self._instructor = instructor.from_openai(
            self._openai,
            mode=instructor.Mode.JSON,
        )

    # ------------------------------------------------------------------
    # Structured extraction (ingestion pipeline)
    # ------------------------------------------------------------------
    def extract(self, text: str, schema: type[SchemaT]) -> SchemaT:
        return self._instructor.chat.completions.create(
            model=self.settings.extract_model,
            response_model=schema,
            messages=[{"role": "user", "content": text}],
            extra_body={"keep_alive": self.settings.keep_alive},
            temperature=0,
        )

    # ------------------------------------------------------------------
    # Tool-calling chat (search agent)
    # ------------------------------------------------------------------
    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        model: str | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model or self.settings.agent_model,
            "messages": messages,
            "temperature": 0,
            "extra_body": {"keep_alive": self.settings.keep_alive},
        }
        if tools:
            kwargs["tools"] = tools
        return self._openai.chat.completions.create(**kwargs)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._openai.embeddings.create(
            model=self.settings.embed_model,
            input=texts,
            extra_body={"keep_alive": self.settings.keep_alive},
        )
        return [item.embedding for item in resp.data]
