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
