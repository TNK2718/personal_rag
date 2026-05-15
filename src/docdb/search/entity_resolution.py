"""Query-time mention → entity resolution.

The ingest pipeline canonicalises freshly-extracted entities by
embedding them and KNN-matching against the existing
``entities_vec`` rows. This module is the query-side mirror: when the
user asks a question, embed the question, KNN-match against the same
``entities_vec``, and return candidate entities the SQL-generation
prompt can inject so that text_to_sql filters by ``entities.id``
instead of ``LIKE``.

Vector-space note: ingest embeds entities as
``f"{type_slug}: {canonical_name}\n{description}"`` (see
``ingestion.pipeline._entity_embedding_text``). Query-time embeds the
raw question, so the two are not perfectly aligned — the threshold
default in ``Settings.query_resolution_distance`` is intentionally
looser than ``entity_dedup_distance`` to compensate.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from docdb.llm.base import LLMProtocol
from docdb.search.direct import get_entity, search_entities_by_embedding


@dataclass(frozen=True)
class ResolvedCandidate:
    entity_id: str
    canonical_name: str
    type_slug: str
    aliases: list[str]
    distance: float


def resolve_mentions(
    conn: sqlite3.Connection,
    question: str,
    llm: LLMProtocol,
    *,
    top_k: int,
    distance_threshold: float,
    enabled: bool,
) -> list[ResolvedCandidate]:
    """Return entities that the question's embedding KNN's close to.

    Failures (embed raises, no entities indexed, blank question) all
    degrade to an empty list — callers can treat resolution as
    best-effort enrichment.
    """
    if not enabled or not question.strip():
        return []

    try:
        [vec] = llm.embed([question])
    except Exception:  # noqa: BLE001 — embed offline; degrade gracefully
        return []

    hits = search_entities_by_embedding(conn, vec, type_slug=None, top_k=top_k)
    out: list[ResolvedCandidate] = []
    for entity_id, distance in hits:
        if distance > distance_threshold:
            continue
        ent = get_entity(conn, entity_id)
        if ent is None:
            continue
        out.append(
            ResolvedCandidate(
                entity_id=entity_id,
                canonical_name=ent.canonical_name,
                type_slug=ent.type_slug,
                aliases=list(ent.aliases),
                distance=distance,
            )
        )
    return out
