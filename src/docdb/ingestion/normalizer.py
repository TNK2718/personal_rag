"""Turn an ``ExtractionResult`` (possibly dynamic, post-Stage-3) into
storage-shape rows.

Three concerns live here:

* canonicalise entity / tag names so case- and width-variants of the
  same thing collapse to one row (NFKC + strip; lowercase for tags);
* derive deterministic IDs (``entity_id_for`` / ``tag_id_for`` /
  ``relation_id_for``) so re-ingesting the same document is idempotent;
* drop the LLM's hallucinations: entities whose ``type`` is not in the
  registry, and relations whose ``source`` / ``target`` cannot be
  resolved to an entity also produced for this document.

Field-value validation against the entity_type's ``fields_schema`` is
NOT done here — it happens at write time in
``DocumentStore.upsert_entity`` so a single source of truth governs
both human-authored creates and LLM-emitted writes.

Everything in this module is pure: no LLM, no DB, no network.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from docdb.models import (
    Entity,
    ExtractionResult,
    Relation,
    Tag,
    entity_id_for,
    relation_id_for,
    tag_id_for,
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
class DocumentRelationLink:
    document_id: str
    relation_id: str
    contexts: list[str] = field(default_factory=list)


@dataclass
class DocumentTagLink:
    document_id: str
    tag_id: str
    confidence: float = 1.0
    source: str = "llm"


@dataclass
class NormalizationDrop:
    kind: str  # 'unknown_entity_type' | 'unresolved_relation' | 'invalid_relation_type'
    reason: str


@dataclass
class NormalizedExtraction:
    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    tags: list[Tag] = field(default_factory=list)
    entity_links: list[DocumentEntityLink] = field(default_factory=list)
    relation_links: list[DocumentRelationLink] = field(default_factory=list)
    tag_links: list[DocumentTagLink] = field(default_factory=list)
    drops: list[NormalizationDrop] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------
def canonicalize_entity_name(name: str) -> str:
    return unicodedata.normalize("NFKC", name).strip()


def canonicalize_tag_name(name: str) -> str:
    return unicodedata.normalize("NFKC", name).strip().lower()


def _dedup_aliases(seq: Iterable[str]) -> list[str]:
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
    entity_type_slugs: Iterable[str] | None = None,
    relation_type_slugs: Iterable[str] | None = None,
    extract_relations: bool = True,
) -> NormalizedExtraction:
    """Project ``extraction`` to storage-shape rows for ``document_id``.

    ``entity_type_slugs`` / ``relation_type_slugs`` come from the registry.
    When None, the normaliser keeps every emitted entity / relation (used
    by tests with hand-built ExtractionResult instances).
    """
    entity_slugs = set(entity_type_slugs) if entity_type_slugs is not None else None
    relation_slugs = set(relation_type_slugs) if relation_type_slugs is not None else None

    tags, tag_links = _build_tags(extraction.tags, document_id)

    raw_entities = list(getattr(extraction, "entities", []) or [])
    entities, entity_links, entity_index, entity_drops = _build_entities(
        raw_entities, document_id, entity_slugs
    )

    relations: list[Relation] = []
    relation_links: list[DocumentRelationLink] = []
    relation_drops: list[NormalizationDrop] = []
    if extract_relations:
        raw_relations = list(getattr(extraction, "relations", []) or [])
        relations, relation_links, relation_drops = _build_relations(
            raw_relations, document_id, entity_index, relation_slugs
        )

    return NormalizedExtraction(
        entities=entities,
        relations=relations,
        tags=tags,
        entity_links=entity_links,
        relation_links=relation_links,
        tag_links=tag_links,
        drops=entity_drops + relation_drops,
    )


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
def _build_entities(
    extracted: list[Any],
    document_id: str,
    entity_slugs: set[str] | None,
) -> tuple[
    list[Entity],
    list[DocumentEntityLink],
    dict[tuple[str, str], str],
    list[NormalizationDrop],
]:
    """Group, canonicalise, dedup, and assign IDs to extracted entities.

    Returns (entities, links, index, drops). ``index`` maps
    (type_slug, lowercased canonical name) → entity_id so the relation
    builder can resolve LLM-emitted ``source`` / ``target`` refs.
    """
    drops: list[NormalizationDrop] = []
    grouped: dict[tuple[str, str], dict] = {}

    for ex in extracted:
        type_slug = _safe_attr(ex, "type")
        name = _safe_attr(ex, "name")
        if not type_slug or not name:
            continue
        if entity_slugs is not None and type_slug not in entity_slugs:
            drops.append(
                NormalizationDrop(
                    kind="unknown_entity_type",
                    reason=f"type={type_slug!r} name={name!r}",
                )
            )
            continue

        canonical = canonicalize_entity_name(name)
        if not canonical:
            continue
        key = (type_slug, canonical.lower())
        bucket = grouped.setdefault(
            key,
            {
                "type_slug": type_slug,
                "canonical_name": canonical,
                "aliases": [],
                "fields": {},
                "mentions": 0,
            },
        )
        bucket["mentions"] += 1
        if name != canonical:
            bucket["aliases"].append(name)
        for alias in _safe_attr(ex, "aliases", []) or []:
            bucket["aliases"].append(alias)

        # First non-empty fields payload wins. The store layer validates it.
        payload_fields = _safe_attr(ex, "fields", {}) or {}
        if payload_fields and not bucket["fields"]:
            bucket["fields"] = dict(payload_fields)

    entities: list[Entity] = []
    links: list[DocumentEntityLink] = []
    index: dict[tuple[str, str], str] = {}
    for bucket in grouped.values():
        canonical = bucket["canonical_name"]
        type_slug = bucket["type_slug"]
        eid = entity_id_for(type_slug, canonical)
        entities.append(
            Entity(
                id=eid,
                type_slug=type_slug,
                canonical_name=canonical,
                aliases=_dedup_aliases(bucket["aliases"]),
                fields=bucket["fields"],
            )
        )
        links.append(
            DocumentEntityLink(
                document_id=document_id,
                entity_id=eid,
                mention_count=bucket["mentions"],
            )
        )
        index[(type_slug, canonical.lower())] = eid
    return entities, links, index, drops


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------
def _build_relations(
    extracted: list[Any],
    document_id: str,
    entity_index: dict[tuple[str, str], str],
    relation_slugs: set[str] | None,
) -> tuple[list[Relation], list[DocumentRelationLink], list[NormalizationDrop]]:
    """Resolve and dedup extracted relations.

    Each relation must point at entities also extracted for this document
    (the registry doesn't help us here — the LLM might mention an entity
    that doesn't appear in this corpus). Unresolved refs land as ``drops``.
    """
    drops: list[NormalizationDrop] = []
    seen: set[str] = set()
    relations: list[Relation] = []
    links: list[DocumentRelationLink] = []

    for ex in extracted:
        type_slug = _safe_attr(ex, "type")
        if not type_slug:
            continue
        if relation_slugs is not None and type_slug not in relation_slugs:
            drops.append(
                NormalizationDrop(
                    kind="invalid_relation_type",
                    reason=f"type={type_slug!r}",
                )
            )
            continue

        src_id = _resolve_ref(entity_index, _safe_attr(ex, "source"))
        tgt_id = _resolve_ref(entity_index, _safe_attr(ex, "target"))
        if not src_id or not tgt_id:
            drops.append(
                NormalizationDrop(
                    kind="unresolved_relation",
                    reason=f"type={type_slug!r} source={_safe_attr(ex, 'source')!r} target={_safe_attr(ex, 'target')!r}",
                )
            )
            continue

        rid = relation_id_for(type_slug, src_id, tgt_id)
        if rid in seen:
            continue
        seen.add(rid)

        relations.append(
            Relation(
                id=rid,
                type_slug=type_slug,
                source_entity_id=src_id,
                target_entity_id=tgt_id,
                fields=dict(_safe_attr(ex, "fields", {}) or {}),
            )
        )
        links.append(DocumentRelationLink(document_id=document_id, relation_id=rid))
    return relations, links, drops


def _resolve_ref(
    entity_index: dict[tuple[str, str], str],
    ref: Any,
) -> str | None:
    if ref is None:
        return None
    ref_type = _safe_attr(ref, "type")
    ref_name = _safe_attr(ref, "name")
    if not ref_type or not ref_name:
        return None
    canonical = canonicalize_entity_name(ref_name).lower()
    return entity_index.get((ref_type, canonical))


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
def _build_tags(
    raw_tags: list[str],
    document_id: str,
) -> tuple[list[Tag], list[DocumentTagLink]]:
    grouped: dict[str, str] = {}
    for raw in raw_tags or []:
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
# Helpers
# ---------------------------------------------------------------------------
def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` off a Pydantic model OR a dict; fall back to default."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# ---------------------------------------------------------------------------
# Due-date heuristic (kept for the deterministic ``task_checkbox`` extractor)
# ---------------------------------------------------------------------------
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
