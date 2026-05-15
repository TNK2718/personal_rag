"""Query-time mention → entity resolution tests.

The resolver embeds the user's question, runs a KNN against
``entities_vec`` (no type filter — the question has no a-priori type),
threshold-filters the hits, and returns ``ResolvedCandidate`` rows the
text2sql prompt can inject. ``_KeyedEmbedLLM`` is a local-only fake
that lets each test pin a deterministic vector per text — that way the
KNN result is fully under test control.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docdb.ingestion.store import DocumentStore
from docdb.llm.fake import FakeLLM, _hash_to_unit_vector
from docdb.models import Entity, entity_id_for
from docdb.search.entity_resolution import ResolvedCandidate, resolve_mentions


def _unit_vec(slot: int, dim: int = 1024) -> list[float]:
    v = [0.0] * dim
    v[slot] = 1.0
    return v


@dataclass
class _KeyedEmbedLLM(FakeLLM):
    """FakeLLM with a text→vector override map (mirrors the helper in
    test_pipeline.py — duplicated here to keep test files independent)."""

    embed_overrides: dict[str, list[float]] = field(default_factory=dict)

    def embed(self, texts):
        self.calls_embed.append(list(texts))
        return [
            self.embed_overrides[t]
            if t in self.embed_overrides
            else _hash_to_unit_vector(t, self.embed_dim)
            for t in texts
        ]


def _seed_person(conn, name: str, *, slot: int, aliases: list[str] | None = None) -> str:
    store = DocumentStore(conn)
    ent = Entity(
        id=entity_id_for("person", name),
        type_slug="person",
        canonical_name=name,
        aliases=aliases or [],
    )
    store.upsert_entity(ent, embedding=_unit_vec(slot))
    return ent.id


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_resolve_mentions_returns_candidates_within_threshold(conn) -> None:
    alice_id = _seed_person(conn, "Alice Smith", slot=0)
    bob_id = _seed_person(conn, "Bob Tanaka", slot=42)

    question = "Aliceのタスク見せて"
    llm = _KeyedEmbedLLM(embed_overrides={question: _unit_vec(0)})

    out = resolve_mentions(
        conn, question, llm,
        top_k=5, distance_threshold=0.5, enabled=True,
    )

    ids = [c.entity_id for c in out]
    assert alice_id in ids
    assert all(isinstance(c, ResolvedCandidate) for c in out)
    # Alice is the zero-distance hit; comes first by ascending distance.
    assert out[0].entity_id == alice_id
    # Bob is orthogonal (slot 42 vs slot 0) → L2² = 2 → above threshold.
    assert bob_id not in ids


def test_resolve_mentions_filters_out_distant_hits(conn) -> None:
    near_id = _seed_person(conn, "Near", slot=0)
    _far_id = _seed_person(conn, "Far", slot=1)

    question = "qq"
    # Question vector is exactly Near's vector. Far is orthogonal — L2² = 2.
    llm = _KeyedEmbedLLM(embed_overrides={question: _unit_vec(0)})

    out = resolve_mentions(
        conn, question, llm,
        top_k=5, distance_threshold=0.1, enabled=True,
    )

    ids = [c.entity_id for c in out]
    assert ids == [near_id]


def test_resolve_mentions_respects_top_k(conn) -> None:
    # Five entities; question matches one exactly, others orthogonal.
    ids = [_seed_person(conn, f"P{i}", slot=i) for i in range(5)]
    question = "qq"
    llm = _KeyedEmbedLLM(embed_overrides={question: _unit_vec(0)})

    # Loose threshold so the cap is the only limiter.
    out = resolve_mentions(
        conn, question, llm,
        top_k=2, distance_threshold=10.0, enabled=True,
    )

    assert len(out) == 2
    # Lowest distance is the exact match (P0).
    assert out[0].entity_id == ids[0]


def test_resolve_mentions_populates_canonical_name_aliases_type_slug(conn) -> None:
    alice_id = _seed_person(conn, "Alice Smith", slot=0, aliases=["Alice S.", "Smith"])
    question = "qq"
    llm = _KeyedEmbedLLM(embed_overrides={question: _unit_vec(0)})

    [cand] = resolve_mentions(
        conn, question, llm,
        top_k=1, distance_threshold=0.1, enabled=True,
    )

    assert cand.entity_id == alice_id
    assert cand.canonical_name == "Alice Smith"
    assert cand.type_slug == "person"
    assert cand.aliases == ["Alice S.", "Smith"]
    assert cand.distance >= 0.0


# ---------------------------------------------------------------------------
# Disabled / short-circuit / failure paths
# ---------------------------------------------------------------------------
def test_resolve_mentions_empty_when_disabled(conn) -> None:
    _seed_person(conn, "Alice", slot=0)
    llm = _KeyedEmbedLLM(embed_overrides={"q": _unit_vec(0)})

    out = resolve_mentions(
        conn, "q", llm,
        top_k=5, distance_threshold=0.5, enabled=False,
    )

    assert out == []
    assert llm.calls_embed == []  # no embed when disabled


def test_resolve_mentions_empty_when_question_blank(conn) -> None:
    _seed_person(conn, "Alice", slot=0)
    llm = _KeyedEmbedLLM()

    out = resolve_mentions(
        conn, "   ", llm,
        top_k=5, distance_threshold=0.5, enabled=True,
    )

    assert out == []
    assert llm.calls_embed == []


def test_resolve_mentions_returns_empty_on_embed_error(conn) -> None:
    _seed_person(conn, "Alice", slot=0)

    class _ExplodingEmbedLLM(FakeLLM):
        def embed(self, texts):
            raise RuntimeError("ollama down")

    out = resolve_mentions(
        conn, "Aliceのタスク", _ExplodingEmbedLLM(),
        top_k=5, distance_threshold=0.5, enabled=True,
    )

    assert out == []


def test_resolve_mentions_returns_empty_when_no_entities(conn) -> None:
    # Empty entities_vec table.
    llm = _KeyedEmbedLLM(embed_overrides={"q": _unit_vec(0)})

    out = resolve_mentions(
        conn, "q", llm,
        top_k=5, distance_threshold=0.5, enabled=True,
    )

    assert out == []
