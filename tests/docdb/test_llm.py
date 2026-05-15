"""LLM seam tests.

The real LLM client is a thin wrapper around the OpenAI SDK that we
exercise only at integration time. What gets unit-tested here:

* the public seam ``LLMProtocol`` is satisfied by both implementations
* ``FakeLLM`` behaves the way every downstream test will rely on:
  - scripted extract / chat responses are consumed in order
  - exhausted chat_with_tools queue raises a helpful AssertionError
  - extract type mismatch surfaces as a TypeError
  - embed is deterministic, length-normalised, and 1024-d by default
"""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from pydantic import BaseModel

from docdb.llm import LLM, FakeLLM, LLMProtocol
from docdb.llm.client import _to_native_message
from docdb.llm.fake import StubChatCompletion
from docdb.models import ExtractionResult


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------
def test_real_llm_satisfies_protocol() -> None:
    # Constructing the real client must not touch the network.
    assert isinstance(LLM(), LLMProtocol)


def test_fake_llm_satisfies_protocol() -> None:
    assert isinstance(FakeLLM(), LLMProtocol)


# ---------------------------------------------------------------------------
# FakeLLM.extract
# ---------------------------------------------------------------------------
def test_extract_returns_scripted_response_in_order() -> None:
    first = ExtractionResult(title="A")
    second = ExtractionResult(title="B")
    fake = FakeLLM(extract_responses=[first, second])

    assert fake.extract("text1", ExtractionResult).title == "A"
    assert fake.extract("text2", ExtractionResult).title == "B"
    assert [c[0] for c in fake.calls_extract] == ["text1", "text2"]


def test_extract_falls_back_to_default_instance_when_unscripted() -> None:
    fake = FakeLLM()
    result = fake.extract("anything", ExtractionResult)
    # Default ExtractionResult has empty fields and doc_type='other'.
    assert result.doc_type == "other"
    assert result.tags == []


def test_extract_type_mismatch_raises_for_unrelated_schemas() -> None:
    """Strictness still applies for schemas that share no inheritance."""

    class _Unrelated(BaseModel):
        foo: str = ""

    fake = FakeLLM(extract_responses=[ExtractionResult()])

    with pytest.raises(TypeError, match="scripted response"):
        fake.extract("x", _Unrelated)


def test_extract_upcasts_parent_to_dynamic_subclass() -> None:
    """Stage 3 dynamic models inherit from ExtractionResult; scripted parents
    must be auto-upcast so existing tests do not have to know the dynamic
    class name."""

    class _Dynamic(ExtractionResult):
        extra: list[str] = []  # default → not required from upcast payload

    fake = FakeLLM(extract_responses=[ExtractionResult(title="upcast me")])
    out = fake.extract("anything", _Dynamic)
    assert isinstance(out, _Dynamic)
    assert out.title == "upcast me"


# ---------------------------------------------------------------------------
# FakeLLM.chat_with_tools
# ---------------------------------------------------------------------------
def test_chat_returns_scripted_responses_and_records_calls() -> None:
    fake = FakeLLM(
        chat_responses=[
            StubChatCompletion.tool([("c1", "search_documents", '{"query":"x"}')]),
            StubChatCompletion.text("final answer"),
        ]
    )

    first = fake.chat_with_tools([{"role": "user", "content": "hi"}], tools=[{}])
    assert first.choices[0].message.tool_calls[0].function.name == "search_documents"

    second = fake.chat_with_tools([{"role": "user", "content": "hi"}])
    assert second.choices[0].message.content == "final answer"
    assert second.choices[0].message.tool_calls is None

    assert len(fake.calls_chat) == 2
    assert fake.calls_chat[0]["tools"] == [{}]


def test_chat_with_empty_queue_raises() -> None:
    fake = FakeLLM()
    with pytest.raises(AssertionError, match="no scripted responses"):
        fake.chat_with_tools([])


# ---------------------------------------------------------------------------
# FakeLLM.embed
# ---------------------------------------------------------------------------
def test_embed_is_deterministic_and_unit_length() -> None:
    fake = FakeLLM()
    a1 = fake.embed(["alpha"])[0]
    a2 = fake.embed(["alpha"])[0]
    assert a1 == a2
    norm = math.sqrt(sum(x * x for x in a1))
    assert norm == pytest.approx(1.0, abs=1e-5)
    assert len(a1) == 1024


def test_embed_distinct_inputs_are_almost_orthogonal() -> None:
    fake = FakeLLM()
    a, b = fake.embed(["alpha", "bravo"])
    cos = sum(x * y for x, y in zip(a, b))
    assert abs(cos) < 0.2  # noisy but never identical


def test_embed_dim_is_configurable() -> None:
    fake = FakeLLM(embed_dim=8)
    assert len(fake.embed(["x"])[0]) == 8


# ---------------------------------------------------------------------------
# LLM.chat_with_tools — Ollama native path
#
# The real chat path now hits Ollama's ``/api/chat`` (the OpenAI-compat
# endpoint scrambles tool-call args on small models). We patch the
# underlying ``ollama.Client.chat`` to assert the wrapper still exposes the
# OpenAI-style ``.choices[0].message.tool_calls[i].function.{name, arguments}``
# shape that ``docdb.agent.loop`` consumes.
# ---------------------------------------------------------------------------
def _native_text_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=None)
    )


def _native_tool_response(name: str, arguments: dict) -> SimpleNamespace:
    call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))
    return SimpleNamespace(
        message=SimpleNamespace(content="", tool_calls=[call])
    )


def test_chat_with_tools_wraps_text_response(monkeypatch) -> None:
    llm = LLM()
    monkeypatch.setattr(
        llm._ollama,
        "chat",
        lambda **kw: _native_text_response("final answer"),
    )

    resp = llm.chat_with_tools([{"role": "user", "content": "hi"}])

    assert resp.choices[0].message.content == "final answer"
    assert resp.choices[0].message.tool_calls is None


def test_chat_with_tools_wraps_tool_calls(monkeypatch) -> None:
    llm = LLM()
    monkeypatch.setattr(
        llm._ollama,
        "chat",
        lambda **kw: _native_tool_response("search_documents", {"query": "おはよう"}),
    )

    resp = llm.chat_with_tools([{"role": "user", "content": "hi"}], tools=[{}])

    msg = resp.choices[0].message
    assert msg.content is None  # empty content collapses to None
    assert msg.tool_calls is not None and len(msg.tool_calls) == 1
    call = msg.tool_calls[0]
    assert call.id  # synthetic uuid; non-empty
    assert call.function.name == "search_documents"
    # arguments must be a JSON string in OpenAI's wire format, with
    # non-ASCII characters preserved (not \u-escaped).
    assert isinstance(call.function.arguments, str)
    assert "おはよう" in call.function.arguments
    assert json.loads(call.function.arguments) == {"query": "おはよう"}


def test_chat_with_tools_forwards_num_ctx_and_keep_alive(monkeypatch) -> None:
    llm = LLM()
    captured: dict = {}

    def _spy(**kwargs):
        captured.update(kwargs)
        return _native_text_response("ok")

    monkeypatch.setattr(llm._ollama, "chat", _spy)
    llm.chat_with_tools([{"role": "user", "content": "x"}])

    assert captured["options"]["num_ctx"] == llm.settings.num_ctx
    assert captured["options"]["temperature"] == 0
    assert captured["keep_alive"] == llm.settings.keep_alive
    assert captured["model"] == llm.settings.agent_model


def test_to_native_message_unstrings_assistant_tool_call_arguments() -> None:
    # Shape that ``docdb.agent.loop`` builds when echoing a previous
    # assistant turn back into the next chat call (loop.py:114-130).
    echoed = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "search_documents",
                    "arguments": '{"query":"hi"}',
                },
            }
        ],
    }

    out = _to_native_message(echoed)

    assert out["role"] == "assistant"
    assert "id" not in out["tool_calls"][0]
    assert "type" not in out["tool_calls"][0]
    fn = out["tool_calls"][0]["function"]
    assert fn["name"] == "search_documents"
    assert fn["arguments"] == {"query": "hi"}  # str -> dict


def test_to_native_message_renames_tool_result_name() -> None:
    tool_msg = {
        "role": "tool",
        "tool_call_id": "call_abc123",
        "name": "search_documents",
        "content": "[]",
    }

    out = _to_native_message(tool_msg)

    assert out == {
        "role": "tool",
        "content": "[]",
        "tool_name": "search_documents",
    }
