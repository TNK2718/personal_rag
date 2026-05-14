"""Pure functions that turn an ``ExtractionResult`` into storage-shape rows.

Stage 2 trimmed this module down to tag normalisation only. Entity and
relation normalisation moves to Stage 3, where the LLM extraction layer
is rebuilt around the runtime type registry. Until that lands, the
ingestion pipeline writes only document rows + tags (plus embeddings).

Everything in this module is pure: no LLM, no DB, no network.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from docdb.models import (
    ExtractionResult,
    Tag,
    tag_id_for,
)


# ---------------------------------------------------------------------------
# Link rows (pre-DB shape)
# ---------------------------------------------------------------------------
@dataclass
class DocumentTagLink:
    document_id: str
    tag_id: str
    confidence: float = 1.0
    source: str = "llm"


@dataclass
class NormalizedExtraction:
    tags: list[Tag] = field(default_factory=list)
    tag_links: list[DocumentTagLink] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------
def canonicalize_entity_name(name: str) -> str:
    """NFKC + strip. Case is preserved (proper-noun-friendly).

    Still exported because Stage 3's entity normaliser will reuse it.
    """
    return unicodedata.normalize("NFKC", name).strip()


def canonicalize_tag_name(name: str) -> str:
    """NFKC + lower + strip. Tags are case-insensitive identifiers."""
    return unicodedata.normalize("NFKC", name).strip().lower()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def normalize_extraction(
    extraction: ExtractionResult,
    *,
    document_id: str,
) -> NormalizedExtraction:
    tags, tag_links = _build_tags(extraction.tags, document_id)
    return NormalizedExtraction(tags=tags, tag_links=tag_links)


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
def _build_tags(
    raw_tags: list[str],
    document_id: str,
) -> tuple[list[Tag], list[DocumentTagLink]]:
    grouped: dict[str, str] = {}  # canonical → display name
    for raw in raw_tags:
        canonical = canonicalize_tag_name(raw)
        if not canonical:
            continue
        grouped.setdefault(canonical, unicodedata.normalize("NFKC", raw).strip())

    tags: list[Tag] = []
    links: list[DocumentTagLink] = []
    for canonical, display in grouped.items():
        tid = tag_id_for(canonical)
        tags.append(
            Tag(
                id=tid,
                canonical_name=canonical,
                aliases=[display] if display != canonical else [],
            )
        )
        links.append(DocumentTagLink(document_id=document_id, tag_id=tid))
    return tags, links


# ---------------------------------------------------------------------------
# Due-date heuristic (kept; reused by Stage 3's task-type deterministic extractor)
# ---------------------------------------------------------------------------
# `\b` between a digit and a Japanese character does not behave the way
# casual readers expect (CJK chars count as word characters in Python
# `re`), so explicit (?<!\d)/(?!\d) is used to bound the date tokens.
_ISO_RE = re.compile(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)")
_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?!\d)")
_JP_FULL_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_JP_MD_RE = re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})日")
_DAYS_LATER = re.compile(r"(\d+)\s*日後")
_WEEKS_LATER = re.compile(r"(\d+)\s*週間後")

_RELATIVE_WORDS = {
    "tomorrow": 1,
    "明日": 1,
    "あした": 1,
}


def extract_due_date(text: str, *, today: date | None = None) -> str | None:
    """Best-effort YYYY-MM-DD from common Japanese / English date phrasings."""
    today = today or datetime.now().date()

    if m := _JP_FULL_RE.search(text):
        return _safe_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    if m := _ISO_RE.search(text):
        return _safe_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    if m := _DMY_RE.search(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_iso(y, mo, d)

    if m := _JP_MD_RE.search(text):
        mo, d = int(m.group(1)), int(m.group(2))
        for year in (today.year, today.year + 1):
            iso = _safe_iso(year, mo, d)
            if iso and (year > today.year or date.fromisoformat(iso) >= today):
                return iso
        return None

    if m := _DAYS_LATER.search(text):
        return (today + timedelta(days=int(m.group(1)))).isoformat()

    if m := _WEEKS_LATER.search(text):
        return (today + timedelta(weeks=int(m.group(1)))).isoformat()

    lowered = text.lower()
    for word, offset in _RELATIVE_WORDS.items():
        if word in lowered:
            return (today + timedelta(days=offset)).isoformat()

    if "来週" in text or "next week" in lowered:
        days = ((4 - today.weekday()) % 7) + 7
        return (today + timedelta(days=days)).isoformat()

    if "今週" in text or "this week" in lowered:
        days = (4 - today.weekday()) % 7
        if days == 0:
            days = 7
        return (today + timedelta(days=days)).isoformat()

    return None


def _safe_iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None
