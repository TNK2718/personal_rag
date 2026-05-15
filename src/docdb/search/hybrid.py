"""Hybrid search: Reciprocal Rank Fusion over FTS and vec0.

RRF is a parameter-free way to combine two ranked lists. Given a
document's rank ``r`` in each list it contributes ``1/(k + r)``; the
constant ``k`` (default 60, from the original 2009 paper) damps the
contribution of low-rank items. The fused score is the sum across
lists.

Why we use it here:

* FTS bm25 and vec0 cosine distance live on incompatible scales; trying
  to weight-blend them by raw score is brittle.
* RRF naturally favours documents that show up in *both* rankings —
  exactly what we want for "find me notes that mention `解約` AND are
  semantically about contract termination".
* The fallback paths (FTS-only or vec-only) keep the same call signature,
  so callers don't branch.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Iterable

from docdb.models import Citation
from docdb.search import direct


def hybrid_search(
    conn: sqlite3.Connection,
    query: str | None = None,
    *,
    embedding: list[float] | None = None,
    top_k: int = 10,
    doc_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    rrf_k: int = 60,
    fetch_multiplier: int = 3,
) -> list[Citation]:
    """Fused FTS + vec ranking.

    * ``query`` (non-empty) drives the FTS arm.
    * ``embedding`` (non-None) drives the vec arm.
    * If exactly one is provided, the fusion degenerates into that arm
      with the existing structured filters applied.

    Each arm is a single SQL statement; only the RRF combination lives
    in Python.
    """
    over_fetch = max(top_k * fetch_multiplier, top_k + 10)

    fts_results: list[Citation] = []
    if query and query.strip():
        fts_results = direct.search(
            conn,
            query,
            top_k=over_fetch,
            doc_type=doc_type,
            date_from=date_from,
            date_to=date_to,
        )

    vec_results: list[Citation] = []
    if embedding is not None:
        vec_results = direct.search_by_embedding(
            conn,
            embedding,
            top_k=over_fetch,
            doc_type=doc_type,
            date_from=date_from,
            date_to=date_to,
        )

    if not fts_results and not vec_results:
        return []
    if fts_results and not vec_results:
        return fts_results[:top_k]
    if vec_results and not fts_results:
        return vec_results[:top_k]

    return _rrf_fuse(fts_results, vec_results, top_k=top_k, rrf_k=rrf_k)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _rrf_fuse(
    fts_results: Iterable[Citation],
    vec_results: Iterable[Citation],
    *,
    top_k: int,
    rrf_k: int,
) -> list[Citation]:
    rrf_scores: dict[str, float] = defaultdict(float)
    snippet_pool: dict[str, Citation] = {}

    # FTS arm — take the bm25-ordered list as-is and trust its snippets.
    for rank, c in enumerate(fts_results, start=1):
        rrf_scores[c.document_id] += 1.0 / (rrf_k + rank)
        snippet_pool[c.document_id] = c

    # Vec arm — only fill metadata for documents the FTS arm missed.
    for rank, c in enumerate(vec_results, start=1):
        rrf_scores[c.document_id] += 1.0 / (rrf_k + rank)
        snippet_pool.setdefault(c.document_id, c)

    ranked_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)
    return [
        snippet_pool[doc_id].model_copy(update={"score": rrf_scores[doc_id]})
        for doc_id in ranked_ids[:top_k]
    ]
