"""Normalizer + due-date heuristic contract tests.

Stage 2 trimmed the normalizer to tag normalization + the due-date
heuristic; entity / todo extraction moves to Stage 3.
"""

from __future__ import annotations

from datetime import date

import pytest

from docdb.ingestion.normalizer import (
    canonicalize_entity_name,
    canonicalize_tag_name,
    extract_due_date,
    normalize_extraction,
)
from docdb.models import ExtractionResult, tag_id_for


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
# Due-date heuristic (kept for Stage 3's task-type deterministic extractor)
# ---------------------------------------------------------------------------
def test_due_date_iso_form() -> None:
    assert extract_due_date("締切 2026-09-30") == "2026-09-30"
    assert extract_due_date("by 2026/09/30") == "2026-09-30"


def test_due_date_dmy_form() -> None:
    assert extract_due_date("31/12/2026 まで") == "2026-12-31"


def test_due_date_japanese_full_form() -> None:
    assert extract_due_date("2026年9月30日") == "2026-09-30"


def test_due_date_japanese_month_day_uses_next_occurrence() -> None:
    today = date(2026, 5, 1)
    assert extract_due_date("4月30日まで", today=today) == "2027-04-30"
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
    assert extract_due_date("来週中に対応", today=date(2026, 5, 1)) == "2026-05-08"


def test_due_date_unknown_phrase_returns_none() -> None:
    assert extract_due_date("いつかやる") is None
    assert extract_due_date("") is None


def test_due_date_invalid_date_returns_none() -> None:
    assert extract_due_date("2026年2月30日") is None
