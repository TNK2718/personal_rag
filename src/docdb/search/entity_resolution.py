"""Query-time mention → entity resolution.

The ingest pipeline canonicalises freshly-extracted entities by
embedding them and KNN-matching against the existing
``entities_vec`` rows. This module is the query-side mirror, invoked
as a **retry fallback** by ``run_text2sql``: when the primary
SQL-generation attempt errors out or returns zero rows, the question
is embedded, KNN-matched against ``entities_vec`` for candidate
entities, and rewritten so that any alias surface form is substituted
with its canonical_name (or, for fuzzy matches that don't substring-
match the question, the canonical_name is appended as a trailing
hint). The retry then re-asks the LLM with the canonicalised question
and the natural ``WHERE canonical_name = 'X'`` SQL pattern works.

Lazy by design: most queries hit the primary path and never trigger
resolution. The embedding cost is paid only when the first attempt
failed, which means resolution latency rides on top of an already-
broken request — fine — instead of every successful one.

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


def canonicalize_mentions_in_question(
    question: str, candidates: list[ResolvedCandidate]
) -> str:
    """Rewrite ``question`` so KNN-found entities surface in canonical form.

    Per-candidate behavior:
      * ``canonical_name`` already substring of question → no change
      * any alias substring of question → replace it in place with
        ``canonical_name`` (so the LLM's natural
        ``WHERE canonical_name = 'X'`` SQL pattern hits the indexed row)
      * neither matches → fuzzy KNN hit; the canonical_name is collected
        and all unmatched canonical_names are appended as one
        ``(関連: X, Y)`` parenthetical at the end of the rewritten
        question, so the model still sees the canonical form even when
        the surface form differs

    The rewrite is idempotent — feeding the output back through this
    function returns the same string.
    """
    rewritten = question
    fallback_hints: list[str] = []
    seen_ids: set[str] = set()
    for c in candidates:
        if c.entity_id in seen_ids:
            continue
        seen_ids.add(c.entity_id)
        if c.canonical_name in rewritten:
            continue  # already canonical
        substring_matched = False
        for alias in c.aliases:
            if alias and alias in rewritten:
                rewritten = rewritten.replace(alias, c.canonical_name, 1)
                substring_matched = True
                break
        if not substring_matched:
            fallback_hints.append(c.canonical_name)
    if fallback_hints:
        rewritten = f"{rewritten} (関連: {', '.join(fallback_hints)})"
    return rewritten
