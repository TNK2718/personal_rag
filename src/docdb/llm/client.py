"""Real LLM client backed by Ollama.

Two transports live side-by-side here, because the OpenAI-compatibility
layer at ``/v1/chat/completions`` mangles tool-call arguments on small
models (notably granite4.1:3b emits scrambled JSON when called with
``tools=[...]``). Ollama's own ``/api/chat`` endpoint does not have that
problem, so tool-calling routes through the native client; ``extract``
and ``embed`` stay on the OpenAI SDK because ``instructor`` is built
around it.

* ``extract``: structured JSON extraction via ``instructor`` against
  ``extract_model`` (OpenAI-compat path).
* ``chat_with_tools``: tool-calling against ``agent_model`` (Ollama
  native path). Wrapped to walk like an OpenAI ``ChatCompletion`` so
  ``loop.py`` stays unaware of the transport.
* ``embed``: vector embeddings via ``embed_model`` (OpenAI-compat path).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, TypeVar

import instructor
import ollama
from openai import OpenAI
from pydantic import BaseModel

from docdb.config import Settings, get_settings


SchemaT = TypeVar("SchemaT", bound=BaseModel)


# ---------------------------------------------------------------------------
# OpenAI-compat ChatCompletion shape, reconstructed over Ollama's native
# response. Only the attributes ``docdb.agent.loop`` reads are populated.
# ---------------------------------------------------------------------------
@dataclass
class _ShimFunction:
    name: str
    arguments: str  # JSON-encoded, matching OpenAI's wire format


@dataclass
class _ShimToolCall:
    id: str
    function: _ShimFunction
    type: str = "function"


@dataclass
class _ShimMessage:
    content: str | None
    tool_calls: list[_ShimToolCall] | None
    role: str = "assistant"


@dataclass
class _ShimChoice:
    message: _ShimMessage


@dataclass
class _ShimCompletion:
    choices: list[_ShimChoice]


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
        # Native client for tool-calling. Strip the OpenAI-compat ``/v1``
        # suffix so the same ``DOCDB_OLLAMA_BASE_URL`` env var configures
        # both transports.
        native_host = (
            self.settings.ollama_base_url.rstrip("/").removesuffix("/v1")
            or "http://localhost:11434"
        )
        self._ollama = ollama.Client(host=native_host)

    # ------------------------------------------------------------------
    # Structured extraction (ingestion pipeline)
    # ------------------------------------------------------------------
    def extract(self, text: str, schema: type[SchemaT]) -> SchemaT:
        return self._instructor.chat.completions.create(
            model=self.settings.extract_model,
            response_model=schema,
            messages=[{"role": "user", "content": text}],
            extra_body={
                "keep_alive": self.settings.keep_alive,
                "options": {"num_ctx": self.settings.num_ctx},
            },
            temperature=0,
        )

    # ------------------------------------------------------------------
    # Tool-calling chat (search agent) — Ollama native /api/chat
    # ------------------------------------------------------------------
    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        model: str | None = None,
    ) -> _ShimCompletion:
        resp = self._ollama.chat(
            model=model or self.settings.agent_model,
            messages=[_to_native_message(m) for m in messages],
            tools=list(tools) if tools else None,
            options={"num_ctx": self.settings.num_ctx, "temperature": 0},
            keep_alive=self.settings.keep_alive,
        )
        return _wrap_ollama_response(resp)

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


# ---------------------------------------------------------------------------
# Native <-> OpenAI-compat message shape translation
# ---------------------------------------------------------------------------
def _to_native_message(message: dict) -> dict:
    """Translate one OpenAI-style message dict into Ollama's native shape.

    The agent loop builds messages in OpenAI's wire format: tool_calls
    have a string ``arguments`` field and a generated ``id``; tool
    results carry ``tool_call_id`` + ``name``. Ollama's native API has
    no ids, expects ``arguments`` as an object, and uses ``tool_name``
    on tool-result messages.
    """
    role = message.get("role")

    if role == "assistant" and message.get("tool_calls"):
        translated_calls = []
        for call in message["tool_calls"]:
            fn = call.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args else {}
                except json.JSONDecodeError:
                    args = {}
            translated_calls.append(
                {"function": {"name": fn.get("name", ""), "arguments": args}}
            )
        out = {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": translated_calls,
        }
        return out

    if role == "tool":
        out = {"role": "tool", "content": message.get("content", "")}
        # OpenAI puts the producing tool's name in ``name``; Ollama
        # native reads it from ``tool_name``.
        name = message.get("name") or message.get("tool_name")
        if name:
            out["tool_name"] = name
        return out

    return dict(message)


def _wrap_ollama_response(resp: Any) -> _ShimCompletion:
    """Re-shape an Ollama native ``ChatResponse`` into the OpenAI-compat
    layout that ``docdb.agent.loop`` already consumes."""
    native_msg = resp.message
    raw_calls = getattr(native_msg, "tool_calls", None) or []

    shim_calls: list[_ShimToolCall] | None = None
    if raw_calls:
        shim_calls = []
        for call in raw_calls:
            fn = call.function
            args_obj = fn.arguments
            args_str = json.dumps(args_obj or {}, ensure_ascii=False)
            shim_calls.append(
                _ShimToolCall(
                    id=uuid.uuid4().hex,
                    function=_ShimFunction(name=fn.name, arguments=args_str),
                )
            )

    return _ShimCompletion(
        choices=[
            _ShimChoice(
                message=_ShimMessage(
                    content=native_msg.content or None,
                    tool_calls=shim_calls,
                )
            )
        ]
    )
