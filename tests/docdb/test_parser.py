"""Parser contract tests.

The parser is the pipeline's first stage. Downstream code (extractor,
normaliser, store) relies on these guarantees:

* the raw_text on the returned document is byte-identical to the input
  (so content_hash stays stable across re-ingestion);
* frontmatter is recognised only when the file starts with ``---``;
* headers split the body in document order, with everything before the
  first header preserved as a ``__preamble__`` section.

The regex TODO fallback was moved out of this module in Stage 2. Stage 3
brings it back as a per-type "deterministic extractor" in
``docdb.typing.deterministic``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docdb.ingestion.parser import Parser, ParsedDocument, Section


@pytest.fixture
def parser() -> Parser:
    return Parser()


# ---------------------------------------------------------------------------
# Markdown — sections / frontmatter / title
# ---------------------------------------------------------------------------
def test_parse_markdown_splits_on_headers(parser: Parser) -> None:
    text = "# 概要\n本文\n\n## 詳細\n中身\n"
    doc = parser.parse_markdown(text, source_path="memo/x.md")

    assert [s.header for s in doc.sections] == ["概要", "詳細"]
    assert [s.level for s in doc.sections] == [1, 2]
    assert doc.sections[0].body == "本文"
    assert doc.sections[1].body == "中身"


def test_parse_markdown_keeps_preamble(parser: Parser) -> None:
    text = "前書き\n\n# 章\n本文"
    doc = parser.parse_markdown(text, source_path="memo/x.md")

    assert doc.sections[0].header == "__preamble__"
    assert doc.sections[0].body == "前書き"
    assert doc.sections[1].header == "章"


def test_parse_markdown_extracts_yaml_frontmatter(parser: Parser) -> None:
    text = (
        "---\n"
        "title: 月例ミーティング\n"
        "author: 田中\n"
        "tags: meeting, q2\n"
        "---\n"
        "# 議題\n本文\n"
    )
    doc = parser.parse_markdown(text, source_path="meeting/x.md")

    assert doc.frontmatter == {
        "title": "月例ミーティング",
        "author": "田中",
        "tags": "meeting, q2",
    }
    # The section body must not contain the frontmatter block.
    assert "title:" not in doc.sections[0].body


def test_parse_markdown_strips_surrounding_quotes_in_frontmatter(parser: Parser) -> None:
    text = '---\ntitle: "クォート付き"\n---\n本文\n'
    doc = parser.parse_markdown(text, source_path="x.md")
    assert doc.frontmatter["title"] == "クォート付き"


def test_parse_markdown_ignores_garbage_after_dashes(parser: Parser) -> None:
    text = "----\n本文だけ\n"  # not a real frontmatter delimiter
    doc = parser.parse_markdown(text, source_path="x.md")
    assert doc.frontmatter == {}


def test_title_prefers_frontmatter_over_first_header(parser: Parser) -> None:
    text = "---\ntitle: FMタイトル\n---\n# 別タイトル\n"
    doc = parser.parse_markdown(text, source_path="x.md")
    assert doc.title == "FMタイトル"


def test_title_falls_back_to_first_header(parser: Parser) -> None:
    doc = parser.parse_markdown("# H1\n## H2\n", source_path="x.md")
    assert doc.title == "H1"


def test_title_falls_back_to_filename_when_no_header(parser: Parser) -> None:
    doc = parser.parse_markdown("本文のみ\n", source_path="notes/2026-05-14-quick.md")
    assert doc.title == "2026-05-14-quick"


# ---------------------------------------------------------------------------
# raw_text and content_hash stability
# ---------------------------------------------------------------------------
def test_raw_text_is_preserved_for_hashing(parser: Parser) -> None:
    text = "---\ntitle: t\n---\n# H\n本文\n"
    doc = parser.parse_markdown(text, source_path="x.md")
    assert doc.raw_text == text


def test_same_input_yields_same_content_hash(parser: Parser) -> None:
    a = parser.parse_markdown("# A\nfoo", source_path="x.md")
    b = parser.parse_markdown("# A\nfoo", source_path="y.md")  # different path
    assert a.content_hash == b.content_hash


def test_different_input_yields_different_content_hash(parser: Parser) -> None:
    a = parser.parse_markdown("# A\nfoo", source_path="x.md")
    b = parser.parse_markdown("# A\nbar", source_path="x.md")
    assert a.content_hash != b.content_hash


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------
def test_parse_text_uses_first_nonblank_line_as_title(parser: Parser) -> None:
    doc = parser.parse_text("\n\n一行目\n二行目\n", source_path="x.txt")
    assert doc.title == "一行目"
    assert doc.source_type == "txt"


def test_parse_text_empty_input_yields_no_sections(parser: Parser) -> None:
    doc = parser.parse_text("", source_path="x.txt")
    assert doc.sections == []


# ---------------------------------------------------------------------------
# File dispatch
# ---------------------------------------------------------------------------
def test_parse_file_dispatches_by_extension(parser: Parser, tmp_path: Path) -> None:
    md = tmp_path / "a.md"
    md.write_text("# Hello\n本文\n", encoding="utf-8")
    txt = tmp_path / "b.txt"
    txt.write_text("plain content", encoding="utf-8")

    md_doc = parser.parse_file(md)
    txt_doc = parser.parse_file(txt)

    assert md_doc.source_type == "md"
    assert md_doc.title == "Hello"
    assert txt_doc.source_type == "txt"
    assert txt_doc.title == "plain content"


def test_parse_file_handles_unknown_extension_as_text(
    parser: Parser, tmp_path: Path
) -> None:
    f = tmp_path / "weird.rst"
    f.write_text("some content", encoding="utf-8")
    doc = parser.parse_file(f)
    assert doc.source_type == "txt"


# ---------------------------------------------------------------------------
# Returned shape sanity
# ---------------------------------------------------------------------------
def test_parsed_document_is_a_dataclass_with_expected_fields(parser: Parser) -> None:
    doc = parser.parse_markdown("# H\n本文", source_path="x.md")
    assert isinstance(doc, ParsedDocument)
    assert isinstance(doc.sections[0], Section)
    assert doc.body_without_frontmatter == "# H\n本文"
