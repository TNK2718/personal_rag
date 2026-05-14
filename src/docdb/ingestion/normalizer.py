"""Pure functions that turn an ``ExtractionResult`` into storage-shape rows.

This module is responsible for:

* Canonicalising entity / tag names so case- and width-variants of the
  same thing collapse to one row (NFKC + strip; lowercase for tags).
* Deriving deterministic IDs (entity_id_for / tag_id_for /
  todo_id_for) so re-ingesting the same document is idempotent.
* Computing junction rows (document_entities / document_tags) ready
  for ``DocumentStore.link_*``.
* Best-effort due-date heuristics in Japanese and English. The LLM
  fills ``due_date`` when it can; this backfills the obvious cases
  the LLM missed (or, in offline mode, the cases regex-only TODO
  extraction never tried to fill).

Everything is pure: no LLM, no DB, no network.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from docdb.models import (
    Entity,
    ExtractedEntity,
    ExtractedTodo,
    ExtractionResult,
    Tag,
    Todo,
    entity_id_for,
    now_iso,
    tag_id_for,
    todo_id_for,
)


# ---------------------------------------------------------------------------
# Link rows (pre-DB shape)
# ---------------------------------------------------------------------------
@dataclass
class DocumentEntityLink:
    document_id: str
    entity_id: str
    mention_count: int = 1
    contexts: list[str] = field(default_factory=list)


@dataclass
class DocumentTagLink:
    document_id: str
    tag_id: str
    confidence: float = 1.0
    source: str = "llm"


@dataclass
class NormalizedExtraction:
    entities: list[Entity]
    tags: list[Tag]
    todos: list[Todo]
    entity_links: list[DocumentEntityLink]
    tag_links: list[DocumentTagLink]


# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------
def canonicalize_entity_name(name: str) -> str:
    """NFKC + strip. Case is preserved (proper-noun-friendly)."""
    return unicodedata.normalize("NFKC", name).strip()


def canonicalize_tag_name(name: str) -> str:
    """NFKC + lower + strip. Tags are case-insensitive identifiers."""
    return unicodedata.normalize("NFKC", name).strip().lower()


def _dedup_aliases(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in seq:
        key = canonicalize_entity_name(s).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(canonicalize_entity_name(s))
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def normalize_extraction(
    extraction: ExtractionResult,
    *,
    document_id: str,
    source_section: str | None = None,
    today: date | None = None,
) -> NormalizedExtraction:
    today = today or datetime.now().date()
    timestamp = now_iso()

    entities, entity_links = _build_entities(extraction.entities, document_id)
    tags, tag_links = _build_tags(extraction.tags, document_id)
    todos = _build_todos(
        extraction.todos,
        document_id=document_id,
        source_section=source_section,
        today=today,
        timestamp=timestamp,
    )

    return NormalizedExtraction(
        entities=entities,
        tags=tags,
        todos=todos,
        entity_links=entity_links,
        tag_links=tag_links,
    )


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
def _build_entities(
    extracted: list[ExtractedEntity],
    document_id: str,
) -> tuple[list[Entity], list[DocumentEntityLink]]:
    grouped: dict[tuple[str, str], dict] = {}
    for ex in extracted:
        canonical = canonicalize_entity_name(ex.name)
        if not canonical:
            continue
        key = (canonical.lower(), ex.entity_type)
        bucket = grouped.setdefault(
            key,
            {
                "canonical_name": canonical,
                "entity_type": ex.entity_type,
                "aliases": [],
                "mentions": 0,
            },
        )
        bucket["mentions"] += 1
        if ex.name != canonical:
            bucket["aliases"].append(ex.name)
        bucket["aliases"].extend(ex.aliases)

    entities: list[Entity] = []
    links: list[DocumentEntityLink] = []
    for bucket in grouped.values():
        canonical = bucket["canonical_name"]
        entity_type = bucket["entity_type"]
        eid = entity_id_for(canonical, entity_type)
        entities.append(
            Entity(
                id=eid,
                canonical_name=canonical,
                entity_type=entity_type,
                aliases=_dedup_aliases(bucket["aliases"]),
            )
        )
        links.append(
            DocumentEntityLink(
                document_id=document_id,
                entity_id=eid,
                mention_count=bucket["mentions"],
            )
        )
    return entities, links


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
        # First-seen display form wins.
        grouped.setdefault(canonical, unicodedata.normalize("NFKC", raw).strip())

    tags: list[Tag] = []
    links: list[DocumentTagLink] = []
    for canonical, display in grouped.items():
        tid = tag_id_for(canonical)
        tags.append(Tag(id=tid, canonical_name=canonical, aliases=[display] if display != canonical else []))
        links.append(DocumentTagLink(document_id=document_id, tag_id=tid))
    return tags, links


# ---------------------------------------------------------------------------
# Todos
# ---------------------------------------------------------------------------
def _build_todos(
    extracted: list[ExtractedTodo],
    *,
    document_id: str,
    source_section: str | None,
    today: date,
    timestamp: str,
) -> list[Todo]:
    seen_ids: set[str] = set()
    out: list[Todo] = []
    for ex in extracted:
        content = ex.content.strip()
        if not content:
            continue
        tid = todo_id_for(document_id, content)
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        due = ex.due_date or extract_due_date(content, today=today)
        out.append(
            Todo(
                id=tid,
                content=content,
                priority=ex.priority,
                due_date=due,
                source_document_id=document_id,
                source_section=source_section,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Due-date heuristic
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
    """Best-effort YYYY-MM-DD from common Japanese / English date phrasings.

    The order matters — explicit ISO dates beat ambiguous "31/12" forms.
    """
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
        # Next Friday.
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
