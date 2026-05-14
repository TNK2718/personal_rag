"""Normalizer + due-date heuristic contract tests."""

from __future__ import annotations

from datetime import date

import pytest

from docdb.ingestion.normalizer import (
    DocumentEntityLink,
    DocumentTagLink,
    canonicalize_entity_name,
    canonicalize_tag_name,
    extract_due_date,
    normalize_extraction,
)
from docdb.models import (
    ExtractedEntity,
    ExtractedTodo,
    ExtractionResult,
    entity_id_for,
    tag_id_for,
)


# ---------------------------------------------------------------------------
# Canonicalisation primitives
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  田中  ", "田中"),
        ("ｱｲｳ", "アイウ"),         # halfwidth katakana → fullwidth
        ("ＡＢＣ", "ABC"),          # fullwidth ascii → ascii
    ],
)
def test_canonicalize_entity_name_nfkc_and_strip(raw: str, expected: str) -> None:
    assert canonicalize_entity_name(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        (" Python ", "python"),
        ("ＰＹＴＨＯＮ", "python"),
        ("メモ", "メモ"),
    ],
)
def test_canonicalize_tag_name_lowercases(raw: str, expected: str) -> None:
    assert canonicalize_tag_name(raw) == expected


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
def test_normalize_collapses_case_and_width_variants_of_same_entity() -> None:
    ext = ExtractionResult(
        entities=[
            ExtractedEntity(name="田中", entity_type="person"),
            ExtractedEntity(name="田中", entity_type="person", aliases=["Tanaka"]),
        ],
    )
    out = normalize_extraction(ext, document_id="doc-1")

    assert len(out.entities) == 1
    e = out.entities[0]
    assert e.canonical_name == "田中"
    assert "Tanaka" in e.aliases
    assert out.entity_links[0].mention_count == 2


def test_normalize_distinguishes_same_name_with_different_type() -> None:
    ext = ExtractionResult(
        entities=[
            ExtractedEntity(name="Apple", entity_type="org"),
            ExtractedEntity(name="Apple", entity_type="product"),
        ],
    )
    out = normalize_extraction(ext, document_id="doc-1")
    assert {e.entity_type for e in out.entities} == {"org", "product"}
    assert len({e.id for e in out.entities}) == 2


def test_normalize_entity_link_uses_deterministic_id() -> None:
    ext = ExtractionResult(
        entities=[ExtractedEntity(name="Alice", entity_type="person")],
    )
    out = normalize_extraction(ext, document_id="doc-X")
    expected_id = entity_id_for("Alice", "person")
    assert out.entities[0].id == expected_id
    assert out.entity_links == [
        DocumentEntityLink(document_id="doc-X", entity_id=expected_id, mention_count=1)
    ]


def test_normalize_skips_empty_entity_names() -> None:
    # ExtractedEntity validates name min_length=1, so we feed an
    # entity whose name is whitespace only via direct construction
    # (which the model still accepts) — the normalizer must drop it.
    ext = ExtractionResult(
        entities=[ExtractedEntity(name=" 　 ", entity_type="person")],
    )
    out = normalize_extraction(ext, document_id="doc-1")
    assert out.entities == []
    assert out.entity_links == []


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
def test_normalize_tags_are_canonicalised_and_deduped() -> None:
    ext = ExtractionResult(tags=["Python", "python", "  PYTHON  ", "メモ"])
    out = normalize_extraction(ext, document_id="doc-1")
    names = {t.canonical_name for t in out.tags}
    assert names == {"python", "メモ"}
    assert all(t.id == tag_id_for(t.canonical_name) for t in out.tags)


def test_normalize_emits_one_tag_link_per_tag() -> None:
    ext = ExtractionResult(tags=["a", "b", "a"])
    out = normalize_extraction(ext, document_id="doc-Y")
    assert {l.tag_id for l in out.tag_links} == {tag_id_for("a"), tag_id_for("b")}
    assert all(l.document_id == "doc-Y" for l in out.tag_links)
    assert all(l.source == "llm" for l in out.tag_links)


# ---------------------------------------------------------------------------
# Todos
# ---------------------------------------------------------------------------
def test_normalize_todos_get_document_scoped_ids_and_timestamps() -> None:
    ext = ExtractionResult(
        todos=[
            ExtractedTodo(content="設計レビュー", priority="high"),
            ExtractedTodo(content="ドキュメント更新"),
        ],
    )
    out = normalize_extraction(ext, document_id="doc-1", source_section="議題")

    assert [t.content for t in out.todos] == ["設計レビュー", "ドキュメント更新"]
    assert all(t.source_document_id == "doc-1" for t in out.todos)
    assert all(t.source_section == "議題" for t in out.todos)
    assert all(t.created_at and t.updated_at for t in out.todos)
    assert out.todos[0].priority == "high"


def test_normalize_todos_dedupe_within_a_single_document() -> None:
    ext = ExtractionResult(
        todos=[
            ExtractedTodo(content="同じ作業"),
            ExtractedTodo(content="同じ作業"),
        ],
    )
    out = normalize_extraction(ext, document_id="doc-1")
    assert len(out.todos) == 1


def test_normalize_todos_use_llm_due_date_when_present() -> None:
    ext = ExtractionResult(
        todos=[ExtractedTodo(content="提出", due_date="2026-12-31")],
    )
    out = normalize_extraction(ext, document_id="doc-1")
    assert out.todos[0].due_date == "2026-12-31"


def test_normalize_todos_fall_back_to_due_date_heuristic() -> None:
    ext = ExtractionResult(
        todos=[ExtractedTodo(content="2026-09-30までに提出")],
    )
    out = normalize_extraction(ext, document_id="doc-1", today=date(2026, 5, 1))
    assert out.todos[0].due_date == "2026-09-30"


# ---------------------------------------------------------------------------
# Due-date heuristic
# ---------------------------------------------------------------------------
def test_due_date_iso_form() -> None:
    assert extract_due_date("締切 2026-09-30") == "2026-09-30"
    assert extract_due_date("by 2026/09/30") == "2026-09-30"


def test_due_date_dmy_form() -> None:
    # 31/12/2026 → 2026-12-31 (assumed DMY when the third field is 4-digit)
    assert extract_due_date("31/12/2026 まで") == "2026-12-31"


def test_due_date_japanese_full_form() -> None:
    assert extract_due_date("2026年9月30日") == "2026-09-30"


def test_due_date_japanese_month_day_uses_next_occurrence() -> None:
    today = date(2026, 5, 1)
    # 4/30 already passed → next year
    assert extract_due_date("4月30日まで", today=today) == "2027-04-30"
    # 9/30 is later this year
    assert extract_due_date("9月30日まで", today=today) == "2026-09-30"


def test_due_date_n_days_later() -> None:
    today = date(2026, 5, 1)
    assert extract_due_date("3日後に提出", today=today) == "2026-05-04"


def test_due_date_n_weeks_later() -> None:
    today = date(2026, 5, 1)
    assert extract_due_date("2週間後", today=today) == "2026-05-15"


def test_due_date_tomorrow() -> None:
    today = date(2026, 5, 1)
    assert extract_due_date("明日まで", today=today) == "2026-05-02"
    assert extract_due_date("by tomorrow", today=today) == "2026-05-02"


def test_due_date_next_week_picks_next_friday() -> None:
    # 2026-05-01 is a Friday; next Friday is 2026-05-08.
    assert extract_due_date("来週中に対応", today=date(2026, 5, 1)) == "2026-05-08"


def test_due_date_unknown_phrase_returns_none() -> None:
    assert extract_due_date("いつかやる") is None
    assert extract_due_date("") is None


def test_due_date_invalid_date_returns_none() -> None:
    # 2/30 doesn't exist; heuristic returns None rather than crash.
    assert extract_due_date("2026年2月30日") is None
