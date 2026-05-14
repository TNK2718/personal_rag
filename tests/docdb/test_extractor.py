"""Extractor and prompt-builder tests.

The extractor sits between the pure parser and the side-effectful
store. Tests cover:
    * the prompt builder injects parsed hints (title, frontmatter,
      source_path) and truncates oversized bodies;
    * the extractor calls LLM.extract exactly once with the
      ExtractionResult schema and the prompt the builder produced;
    * LLM errors surface as a non-fatal ExtractionOutcome with an
      error string and a sensible default result — the pipeline must
      remain able to continue.
"""

from __future__ import annotations

import pytest

from docdb.ingestion.extractor import Extractor
from docdb.ingestion.parser import Parser
from docdb.llm.fake import FakeLLM
from docdb.llm.prompts import EXTRACTION_SYSTEM, build_extraction_user_prompt
from docdb.models import ExtractedEntity, ExtractedTodo, ExtractionResult


@pytest.fixture
def parser() -> Parser:
    return Parser()


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------
def test_user_prompt_includes_system_instructions(parser: Parser) -> None:
    parsed = parser.parse_markdown("# H\n本文", source_path="x.md")
    prompt = build_extraction_user_prompt(parsed)
    assert EXTRACTION_SYSTEM in prompt
    assert "# 本文" in prompt
    assert "本文" in prompt  # the body itself


def test_user_prompt_carries_title_and_frontmatter_hints(parser: Parser) -> None:
    text = "---\ntitle: ABC\nauthor: 田中\n---\n# 章\n本文\n"
    parsed = parser.parse_markdown(text, source_path="path/to/note.md")
    prompt = build_extraction_user_prompt(parsed)

    assert "既存タイトル候補: ABC" in prompt
    assert "source_path: path/to/note.md" in prompt
    assert "author=田中" in prompt


def test_user_prompt_truncates_long_bodies(parser: Parser) -> None:
    big = "あ" * 5000
    parsed = parser.parse_markdown(big, source_path="x.md")
    prompt = build_extraction_user_prompt(parsed, max_body_chars=1000)
    assert "末尾を" in prompt
    assert "省略" in prompt
    # The body portion (between "# 本文" and the truncation marker)
    # must be exactly max_body_chars long, modulo a possible trailing
    # newline from the join.
    body_section = prompt.split("# 本文\n", 1)[1]
    body_only = body_section.split("\n[...", 1)[0].rstrip("\n")
    assert len(body_only) == 1000


def test_user_prompt_does_not_truncate_short_bodies(parser: Parser) -> None:
    parsed = parser.parse_markdown("# H\n本文", source_path="x.md")
    prompt = build_extraction_user_prompt(parsed, max_body_chars=8000)
    assert "省略" not in prompt


# ---------------------------------------------------------------------------
# Extractor — happy path
# ---------------------------------------------------------------------------
def test_extractor_calls_llm_once_with_correct_schema(parser: Parser) -> None:
    parsed = parser.parse_markdown("# H\n本文", source_path="x.md")
    scripted = ExtractionResult(
        doc_type="memo",
        title="H",
        summary="本文のサマリ",
        entities=[ExtractedEntity(name="田中", entity_type="person")],
        tags=["メモ"],
        todos=[ExtractedTodo(content="作業")],
    )
    fake = FakeLLM(extract_responses=[scripted])
    extractor = Extractor(fake)

    outcome = extractor.extract(parsed)

    assert outcome.succeeded
    assert outcome.result is scripted
    assert len(fake.calls_extract) == 1
    text, schema = fake.calls_extract[0]
    assert schema is ExtractionResult
    assert "本文" in text


def test_extractor_fills_missing_title_from_parsed(parser: Parser) -> None:
    # The LLM forgot to emit a title — the extractor must backfill it
    # from the parsed document so we never lose a real H1.
    parsed = parser.parse_markdown("# 真のタイトル\n本文", source_path="x.md")
    fake = FakeLLM(extract_responses=[ExtractionResult(title="")])
    extractor = Extractor(fake)

    out = extractor.extract(parsed)
    assert out.result.title == "真のタイトル"


def test_extractor_preserves_llm_title_when_present(parser: Parser) -> None:
    parsed = parser.parse_markdown("# 元", source_path="x.md")
    fake = FakeLLM(extract_responses=[ExtractionResult(title="LLM版")])
    extractor = Extractor(fake)
    assert extractor.extract(parsed).result.title == "LLM版"


# ---------------------------------------------------------------------------
# Extractor — graceful degradation
# ---------------------------------------------------------------------------
class _ExplodingLLM(FakeLLM):
    def extract(self, text, schema):  # noqa: D401 — match Protocol
        raise RuntimeError("ollama unreachable")


def test_extractor_returns_default_result_on_llm_error(parser: Parser) -> None:
    parsed = parser.parse_markdown("# H\n本文", source_path="x.md")
    extractor = Extractor(_ExplodingLLM())

    out = extractor.extract(parsed)
    assert not out.succeeded
    assert "ollama unreachable" in out.error
    # Title from the parsed document survives even when extraction
    # fails so the pipeline can still write a usable row.
    assert out.result.title == "H"
    assert out.result.entities == []
    assert out.result.todos == []


def test_extractor_truncates_via_max_input_chars(parser: Parser) -> None:
    big = "あ" * 4000
    parsed = parser.parse_markdown(big, source_path="x.md")
    fake = FakeLLM(extract_responses=[ExtractionResult()])
    extractor = Extractor(fake, max_input_chars=500)

    extractor.extract(parsed)
    sent_text, _ = fake.calls_extract[0]
    assert "省略" in sent_text
