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

import math

import pytest

from docdb.llm import LLM, FakeLLM, LLMProtocol
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


def test_extract_type_mismatch_raises_clearly() -> None:
    class _OtherSchema(ExtractionResult):
        pass

    fake = FakeLLM(extract_responses=[ExtractionResult()])

    with pytest.raises(TypeError, match="scripted response"):
        fake.extract("x", _OtherSchema)


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
