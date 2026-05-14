"""In-process fake LLM for tests.

The fake mirrors the LLM seam so callers do not need to mock OpenAI or
instructor. Three independent channels:

* ``extract_responses``: a queue of values returned by ``extract`` in
  order; if exhausted, the fake constructs a default instance of the
  requested schema.
* ``chat_responses``: a queue of pre-built objects returned by
  ``chat_with_tools``. These should look like an OpenAI
  ``ChatCompletion`` (have ``.choices[0].message`` with optional
  ``.tool_calls``). ``StubChatMessage`` / ``StubChatCompletion`` are
  provided to build them ergonomically.
* ``embed`` returns deterministic 1024-d vectors derived from the
  input string's hash, so test assertions can compare similarity
  ordering without sampling randomness.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel


SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass
class StubToolCall:
    id: str
    name: str
    arguments: str  # JSON string, matching OpenAI's wire format

    @property
    def function(self) -> "StubToolCall":
        # Mimic chat_completion.message.tool_calls[i].function.{name,arguments}
        return self


@dataclass
class StubChatMessage:
    content: str | None = None
    tool_calls: list[StubToolCall] | None = None
    role: str = "assistant"


@dataclass
class _Choice:
    message: StubChatMessage


@dataclass
class StubChatCompletion:
    choices: list[_Choice]

    @classmethod
    def text(cls, content: str) -> "StubChatCompletion":
        return cls(choices=[_Choice(message=StubChatMessage(content=content))])

    @classmethod
    def tool(
        cls,
        calls: list[tuple[str, str, str]],  # (id, name, arguments_json)
        content: str | None = None,
    ) -> "StubChatCompletion":
        tcs = [StubToolCall(id=i, name=n, arguments=a) for i, n, a in calls]
        return cls(choices=[_Choice(message=StubChatMessage(content=content, tool_calls=tcs))])


def _hash_to_unit_vector(text: str, dim: int = 1024) -> list[float]:
    """Deterministic, length-normalised pseudo-embedding for tests.

    Same input always yields the same vector; different inputs are
    almost-orthogonal so cosine similarity ordering is meaningful.

    Implementation: chain SHA-512 to fill ``dim`` bytes, then map each
    byte to [-1, 1) and L2-normalise. Bytes are well-defined for every
    input, so NaN/Inf cannot leak in.
    """
    raw_bytes = bytearray()
    seed = text.encode("utf-8")
    while len(raw_bytes) < dim:
        seed = hashlib.sha512(seed).digest()
        raw_bytes.extend(seed)
    raw = [(b / 127.5) - 1.0 for b in raw_bytes[:dim]]
    norm = sum(x * x for x in raw) ** 0.5 or 1.0
    return [x / norm for x in raw]


@dataclass
class FakeLLM:
    extract_responses: list[BaseModel] = field(default_factory=list)
    chat_responses: list[StubChatCompletion] = field(default_factory=list)
    embed_dim: int = 1024

    calls_extract: list[tuple[str, type[BaseModel]]] = field(default_factory=list)
    calls_chat: list[dict[str, Any]] = field(default_factory=list)
    calls_embed: list[list[str]] = field(default_factory=list)

    # ------------------------------------------------------------------
    def extract(self, text: str, schema: type[SchemaT]) -> SchemaT:
        self.calls_extract.append((text, schema))
        if self.extract_responses:
            val = self.extract_responses.pop(0)
            if not isinstance(val, schema):
                raise TypeError(
                    f"FakeLLM.extract scripted response is {type(val).__name__}, "
                    f"caller asked for {schema.__name__}"
                )
            return val
        # Fall back to a default-constructed instance (works when every
        # field has a default; otherwise this raises and signals that
        # the test forgot to script the response).
        return schema()

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        model: str | None = None,
    ) -> StubChatCompletion:
        self.calls_chat.append({"messages": messages, "tools": tools, "model": model})
        if not self.chat_responses:
            raise AssertionError("FakeLLM.chat_with_tools called with no scripted responses left")
        return self.chat_responses.pop(0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls_embed.append(list(texts))
        return [_hash_to_unit_vector(t, self.embed_dim) for t in texts]
