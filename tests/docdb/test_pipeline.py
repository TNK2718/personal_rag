"""End-to-end ingestion pipeline tests.

These run the full parser → extractor (FakeLLM) → normalizer → store
flow against a real SQLite file and check the externally observable
behaviour: which rows land where, when status switches between
created/updated/skipped, and how the pipeline survives failure modes.

Stage 2 narrows ingestion to documents + tags + embeddings; entity
and relation writes return in Stage 3 driven by the type registry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docdb.ingestion.pipeline import IngestionPipeline
from docdb.ingestion.store import DocumentStore
from docdb.llm.fake import FakeLLM
from docdb.models import ExtractionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _meeting_result() -> ExtractionResult:
    return ExtractionResult(
        doc_type="meeting",
        title="プロジェクトA定例",
        summary="議題と次回までのTODO",
        language="ja",
        tags=["meeting", "Project A"],
    )


def _make_pipeline(conn, *, results: list[ExtractionResult] | None = None) -> tuple[IngestionPipeline, FakeLLM]:
    fake = FakeLLM(extract_responses=list(results) if results else [])
    pipeline = IngestionPipeline(store=DocumentStore(conn), llm=fake)
    return pipeline, fake


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_ingest_text_writes_document_and_tags(conn) -> None:
    pipeline, _fake = _make_pipeline(conn, results=[_meeting_result()])

    report = pipeline.ingest_text(
        "---\ndate: 2026-04-15\n---\n# プロジェクトA定例\n本文\n",
        source_path="meeting/2026-04-15.md",
    )

    assert report.status == "created"
    assert report.document_id is not None
    assert report.tags_added == 2
    # Stage 2 deliberately writes no entities; Stage 3 reinstates this.
    assert report.entities_added_by_type == {}

    row = conn.execute(
        "SELECT title, doc_type, language, created_at FROM documents WHERE id = ?",
        (report.document_id,),
    ).fetchone()
    assert row["title"] == "プロジェクトA定例"
    assert row["doc_type"] == "meeting"
    assert row["language"] == "ja"
    assert row["created_at"] == "2026-04-15"

    assert conn.execute(
        "SELECT COUNT(*) AS n FROM tags WHERE canonical_name = ?",
        ("project a",),
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM document_tags WHERE document_id = ?",
        (report.document_id,),
    ).fetchone()["n"] == 2

    # An embedding was written.
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM documents_vec WHERE document_id = ?",
        (report.document_id,),
    ).fetchone()["n"] == 1

    # No entity rows are produced by the pipeline in Stage 2.
    assert conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"] == 0


def test_ingest_text_extracts_created_at_from_filename_when_no_frontmatter(conn) -> None:
    pipeline, _ = _make_pipeline(conn, results=[ExtractionResult(title="t")])
    report = pipeline.ingest_text(
        "本文だけ",
        source_path="memo/2026-05-14-quick.md",
    )
    row = conn.execute(
        "SELECT created_at FROM documents WHERE id = ?", (report.document_id,)
    ).fetchone()
    assert row["created_at"] == "2026-05-14"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
def test_re_ingesting_unchanged_text_is_skipped_without_llm_calls(conn) -> None:
    pipeline, fake = _make_pipeline(conn, results=[_meeting_result()])

    text = "# プロジェクトA\n本文\n"
    first = pipeline.ingest_text(text, source_path="meeting/p.md")
    assert first.status == "created"
    assert len(fake.calls_extract) == 1

    second = pipeline.ingest_text(text, source_path="meeting/p.md")
    assert second.status == "skipped"
    assert second.document_id == first.document_id
    assert len(fake.calls_extract) == 1


def test_editing_a_file_replaces_old_rows_and_returns_updated(conn) -> None:
    pipeline, _ = _make_pipeline(
        conn,
        results=[
            ExtractionResult(title="旧", tags=["旧タグ"]),
            ExtractionResult(title="新", tags=["新タグ"]),
        ],
    )

    first = pipeline.ingest_text("旧本文", source_path="memo/a.md")
    assert first.status == "created"

    second = pipeline.ingest_text("新本文", source_path="memo/a.md")
    assert second.status == "updated"
    assert second.document_id != first.document_id

    titles = [
        r["title"]
        for r in conn.execute(
            "SELECT title FROM documents WHERE source_path = ?", ("memo/a.md",)
        ).fetchall()
    ]
    assert titles == ["新"]


# ---------------------------------------------------------------------------
# Directory walk
# ---------------------------------------------------------------------------
def test_ingest_directory_processes_every_markdown_file(conn, tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# A\n本文A", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n本文B", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.md").write_text("# C\n本文C", encoding="utf-8")
    (tmp_path / "skip.txt").write_text("ignored", encoding="utf-8")

    pipeline, _ = _make_pipeline(
        conn,
        results=[ExtractionResult(title=f"t{i}") for i in range(3)],
    )

    reports = list(pipeline.ingest_directory(tmp_path, glob="**/*.md"))
    assert [r.status for r in reports] == ["created", "created", "created"]
    assert conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 3


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------
class _SilentlyBrokenLLM(FakeLLM):
    """Extract returns a default; embed raises."""

    def embed(self, texts):  # noqa: D401
        raise RuntimeError("ollama embed offline")


def test_embed_failure_reports_error_without_inserting_partial_rows(conn) -> None:
    pipeline = IngestionPipeline(
        store=DocumentStore(conn),
        llm=_SilentlyBrokenLLM(extract_responses=[_meeting_result()]),
    )

    report = pipeline.ingest_text("本文", source_path="m/x.md")
    assert report.status == "error"
    assert "embed failed" in report.error
    assert conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 0


def test_extraction_failure_still_writes_document(conn) -> None:
    class _ExtractFails(FakeLLM):
        def extract(self, text, schema):
            raise RuntimeError("ollama extract offline")

    pipeline = IngestionPipeline(store=DocumentStore(conn), llm=_ExtractFails())
    report = pipeline.ingest_text(
        "---\ntitle: タイトル\n---\n本文\n", source_path="m/x.md"
    )

    assert report.status == "created"
    assert report.extraction_error is not None
    assert "ollama extract offline" in report.extraction_error
    assert conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 1
    row = conn.execute("SELECT title FROM documents").fetchone()
    assert row["title"] == "タイトル"


# ---------------------------------------------------------------------------
# Fuzzy entity dedup across documents
#
# Pipeline embeds each extracted entity, KNN-queries entities_vec, and folds
# matches under ``entity_dedup_distance`` into the pre-existing row's
# aliases. Tests script entity embeddings so the distance is deterministic.
# ---------------------------------------------------------------------------
import json

from docdb.typing.dynamic_model import build_extraction_model, clear_cache
from docdb.typing.registry import registry_hash


@pytest.fixture(autouse=True)
def _reset_dynamic_model_cache():
    # build_extraction_model caches by registry_hash only; tests in this
    # file build models with different slug subsets, so we clear before
    # each test to avoid bleed-through.
    clear_cache()
    yield
    clear_cache()


class _KeyedEmbedLLM(FakeLLM):
    """FakeLLM with a text→vector override map.

    Used to make the entity-embed call deterministic across docs: two
    different canonical_names can be forced to the same vector so the
    KNN merge step fires, while doc-embed calls (which we don't care
    about) fall back to the hash-based default.
    """

    def __init__(self, *, embed_overrides=None, **kwargs):
        super().__init__(**kwargs)
        self.embed_overrides = dict(embed_overrides or {})

    def embed(self, texts):
        self.calls_embed.append(list(texts))
        from docdb.llm.fake import _hash_to_unit_vector

        return [
            self.embed_overrides[t]
            if t in self.embed_overrides
            else _hash_to_unit_vector(t, self.embed_dim)
            for t in texts
        ]


def _unit_vec(slot: int, dim: int = 1024) -> list[float]:
    v = [0.0] * dim
    v[slot] = 1.0
    return v


def _person_extraction(conn, name: str):
    """Build a dynamic ExtractionResult with a single ``person`` entity."""
    Model = build_extraction_model(
        entity_type_slugs=["person"],
        relation_type_slugs=[],
        registry_hash=registry_hash(conn),
    )
    return Model(title=f"doc about {name}", entities=[{"type": "person", "name": name}])


def test_fuzzy_match_merges_two_surface_forms(conn) -> None:
    """Two docs, two surface forms with identical entity-embedding → one row."""
    matched_vec = _unit_vec(0)
    llm = _KeyedEmbedLLM(
        extract_responses=[
            _person_extraction(conn, "Alice Smith"),
            _person_extraction(conn, "Alice S."),
        ],
        embed_overrides={
            "person: Alice Smith": matched_vec,
            "person: Alice S.": matched_vec,
        },
    )
    pipeline = IngestionPipeline(store=DocumentStore(conn), llm=llm)

    r1 = pipeline.ingest_text("doc1 body", source_path="a.md")
    r2 = pipeline.ingest_text("doc2 body", source_path="b.md")

    assert r1.status == "created" and r2.status == "created"
    # Only one person row survives.
    person_rows = conn.execute(
        "SELECT id, canonical_name, aliases FROM entities WHERE type_slug = 'person'"
    ).fetchall()
    assert len(person_rows) == 1
    canonical = person_rows[0]["canonical_name"]
    aliases = json.loads(person_rows[0]["aliases"])
    # First doc wins canonical; second's surface form became an alias.
    assert canonical == "Alice Smith"
    assert "Alice S." in aliases
    # Both documents link to the same merged entity.
    links = conn.execute(
        "SELECT DISTINCT entity_id FROM document_entities"
    ).fetchall()
    assert len(links) == 1
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM document_entities"
    ).fetchone()["n"] == 2


def test_below_threshold_keeps_two_rows(conn) -> None:
    """Orthogonal entity embeddings → distance well above threshold → no merge."""
    llm = _KeyedEmbedLLM(
        extract_responses=[
            _person_extraction(conn, "Alice"),
            _person_extraction(conn, "Bob"),
        ],
        embed_overrides={
            "person: Alice": _unit_vec(0),
            "person: Bob": _unit_vec(500),
        },
    )
    pipeline = IngestionPipeline(store=DocumentStore(conn), llm=llm)
    pipeline.ingest_text("d1", source_path="a.md")
    pipeline.ingest_text("d2", source_path="b.md")

    names = sorted(
        r["canonical_name"]
        for r in conn.execute(
            "SELECT canonical_name FROM entities WHERE type_slug = 'person'"
        ).fetchall()
    )
    assert names == ["Alice", "Bob"]


def test_cross_type_never_merges(conn) -> None:
    """Same canonical_name + same vector across types → KNN filter
    keeps them as two distinct rows under different ``type_slug``."""
    Model = build_extraction_model(
        entity_type_slugs=["person", "task"],
        relation_type_slugs=[],
        registry_hash=registry_hash(conn),
    )
    doc1 = Model(
        title="t",
        entities=[{"type": "person", "name": "review"}],
    )
    doc2 = Model(
        title="t",
        entities=[{"type": "task", "name": "review",
                   "fields": {"status": "pending", "priority": "medium"}}],
    )
    shared = _unit_vec(0)
    llm = _KeyedEmbedLLM(
        extract_responses=[doc1, doc2],
        embed_overrides={
            "person: review": shared,
            "task: review": shared,
        },
    )
    pipeline = IngestionPipeline(store=DocumentStore(conn), llm=llm)
    pipeline.ingest_text("d1", source_path="a.md")
    pipeline.ingest_text("d2", source_path="b.md")

    rows = conn.execute(
        "SELECT type_slug, canonical_name FROM entities ORDER BY type_slug"
    ).fetchall()
    assert [(r["type_slug"], r["canonical_name"]) for r in rows] == [
        ("person", "review"),
        ("task", "review"),
    ]


def test_dedup_disabled_skips_lookup(conn) -> None:
    """With entity_dedup_enabled=False, identical embeddings + different
    canonical_names produce two rows (the unique constraint can't catch
    them)."""
    matched = _unit_vec(0)
    llm = _KeyedEmbedLLM(
        extract_responses=[
            _person_extraction(conn, "Alice"),
            _person_extraction(conn, "Alice S."),
        ],
        embed_overrides={
            "person: Alice": matched,
            "person: Alice S.": matched,
        },
    )
    pipeline = IngestionPipeline(
        store=DocumentStore(conn),
        llm=llm,
        entity_dedup_enabled=False,
    )
    pipeline.ingest_text("d1", source_path="a.md")
    pipeline.ingest_text("d2", source_path="b.md")

    n = conn.execute(
        "SELECT COUNT(*) AS n FROM entities WHERE type_slug = 'person'"
    ).fetchone()["n"]
    assert n == 2


def test_embed_failure_falls_back_to_no_dedup(conn) -> None:
    """If entity-batch embed raises, the doc still ingests and the
    failure lands on extraction_error. Doc embed (call #1) succeeds."""

    class _EntityEmbedBroken(_KeyedEmbedLLM):
        def __init__(self, **kw):
            super().__init__(**kw)
            self._call = 0

        def embed(self, texts):
            self._call += 1
            if self._call == 1:
                return super().embed(texts)  # doc-embed succeeds
            raise RuntimeError("entity embed offline")

    llm = _EntityEmbedBroken(extract_responses=[_person_extraction(conn, "Alice")])
    pipeline = IngestionPipeline(store=DocumentStore(conn), llm=llm)

    report = pipeline.ingest_text("body", source_path="a.md")
    assert report.status == "created"
    assert report.entities_added_by_type.get("person") == 1
    assert report.extraction_error is not None
    assert "entity embed failed" in report.extraction_error


def test_unknown_doc_type_falls_back_to_other(conn) -> None:
    pipeline, _ = _make_pipeline(
        conn,
        results=[
            ExtractionResult.model_construct(  # bypass Literal validation
                doc_type="garbage",
                title="t",
                summary="",
                language="zz",
                tags=[],
            )
        ],
    )
    report = pipeline.ingest_text("本文", source_path="x.md")
    row = conn.execute(
        "SELECT doc_type, language FROM documents WHERE id = ?",
        (report.document_id,),
    ).fetchone()
    assert row["doc_type"] == "other"
    assert row["language"] == "other"
