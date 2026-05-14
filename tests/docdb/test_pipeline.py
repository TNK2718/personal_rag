"""End-to-end ingestion pipeline tests.

These run the full parser → extractor (FakeLLM) → normalizer → store
flow against a real SQLite file and check the externally observable
behaviour: which rows land where, when status switches between
created/updated/skipped, and how the pipeline survives failure modes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docdb.ingestion.pipeline import IngestionPipeline
from docdb.ingestion.store import DocumentStore
from docdb.llm.fake import FakeLLM
from docdb.models import (
    ExtractedEntity,
    ExtractedTodo,
    ExtractionResult,
    entity_id_for,
    tag_id_for,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _full_result() -> ExtractionResult:
    return ExtractionResult(
        doc_type="meeting",
        title="プロジェクトA定例",
        summary="議題と次回までのTODO",
        language="ja",
        entities=[ExtractedEntity(name="田中", entity_type="person")],
        tags=["meeting", "Project A"],
        todos=[ExtractedTodo(content="設計レビュー実施", priority="high")],
    )


def _make_pipeline(conn, *, results: list[ExtractionResult] | None = None) -> tuple[IngestionPipeline, FakeLLM]:
    fake = FakeLLM(extract_responses=list(results) if results else [])
    pipeline = IngestionPipeline(store=DocumentStore(conn), llm=fake)
    return pipeline, fake


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_ingest_text_writes_document_entity_tag_and_todo(conn) -> None:
    pipeline, _fake = _make_pipeline(conn, results=[_full_result()])

    report = pipeline.ingest_text(
        "---\ndate: 2026-04-15\n---\n# プロジェクトA定例\n本文\n",
        source_path="meeting/2026-04-15.md",
    )

    assert report.status == "created"
    assert report.document_id is not None
    assert report.entities_added == 1
    assert report.tags_added == 2
    assert report.todos_added == 1

    # Document landed.
    row = conn.execute(
        "SELECT title, doc_type, language, created_at FROM documents WHERE id = ?",
        (report.document_id,),
    ).fetchone()
    assert row["title"] == "プロジェクトA定例"
    assert row["doc_type"] == "meeting"
    assert row["language"] == "ja"
    assert row["created_at"] == "2026-04-15"

    # Entity, tag, todo, and links exist.
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM entities WHERE id = ?",
        (entity_id_for("田中", "person"),),
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM tags WHERE canonical_name = ?",
        ("project a",),
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM document_entities WHERE document_id = ?",
        (report.document_id,),
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM document_tags WHERE document_id = ?",
        (report.document_id,),
    ).fetchone()["n"] == 2
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM todos WHERE source_document_id = ?",
        (report.document_id,),
    ).fetchone()["n"] == 1

    # An embedding was written too.
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM documents_vec WHERE document_id = ?",
        (report.document_id,),
    ).fetchone()["n"] == 1


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
    pipeline, fake = _make_pipeline(
        conn, results=[_full_result()]  # only one scripted extraction
    )

    text = "# プロジェクトA\n本文\n"
    first = pipeline.ingest_text(text, source_path="meeting/p.md")
    assert first.status == "created"
    assert len(fake.calls_extract) == 1

    second = pipeline.ingest_text(text, source_path="meeting/p.md")
    assert second.status == "skipped"
    assert second.document_id == first.document_id
    # No additional LLM call — exactly one scripted response was enough.
    assert len(fake.calls_extract) == 1


def test_editing_a_file_replaces_old_rows_and_returns_updated(conn) -> None:
    pipeline, _ = _make_pipeline(
        conn,
        results=[
            ExtractionResult(
                title="旧",
                tags=["旧タグ"],
                entities=[ExtractedEntity(name="旧人", entity_type="person")],
            ),
            ExtractionResult(
                title="新",
                tags=["新タグ"],
                entities=[ExtractedEntity(name="新人", entity_type="person")],
            ),
        ],
    )

    first = pipeline.ingest_text("旧本文", source_path="memo/a.md")
    assert first.status == "created"

    second = pipeline.ingest_text("新本文", source_path="memo/a.md")
    assert second.status == "updated"
    assert second.document_id != first.document_id  # id derives from hash

    # The old document is gone (delete_by_source ran).
    titles = [
        r["title"]
        for r in conn.execute(
            "SELECT title FROM documents WHERE source_path = ?", ("memo/a.md",)
        ).fetchall()
    ]
    assert titles == ["新"]

    # The old entity row may linger (we use upsert on entities, not
    # delete), but the link to the deleted document must be gone.
    old_links = conn.execute(
        "SELECT COUNT(*) AS n FROM document_entities WHERE document_id = ?",
        (first.document_id,),
    ).fetchone()["n"]
    assert old_links == 0


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
        results=[
            ExtractionResult(title=f"t{i}") for i in range(3)
        ],
    )

    reports = pipeline.ingest_directory(tmp_path, glob="**/*.md")
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
        store=DocumentStore(conn), llm=_SilentlyBrokenLLM(extract_responses=[_full_result()])
    )

    report = pipeline.ingest_text("本文", source_path="m/x.md")
    assert report.status == "error"
    assert "embed failed" in report.error
    # Nothing was written.
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
    # No tags / entities / todos extracted, but the document landed.
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
                entities=[],
                tags=[],
                todos=[],
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
