"""docdb CLI integration tests.

Click's CliRunner gives us in-process invocation; we plug the FakeLLM
into ctx.obj["llm_factory"] so no commands talk to the network.

What gets covered:
    * `init` creates the DB file and applies schema.
    * `ingest` and `ingest-dir` write rows that `stats` and `search`
      then read back.
    * `migrate-todos` imports a legacy todos.json shape and links to
      the matching document by source_path when one exists.
    * `--db` overrides the configured DB path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from docdb.cli import main
from docdb.config import Settings
from docdb.llm.fake import FakeLLM, StubChatCompletion
from docdb.models import ExtractedEntity, ExtractedTodo, ExtractionResult


def _factory(*results: ExtractionResult):
    """Return a callable that produces a FakeLLM scripted with `results`.

    The CLI calls llm_factory(settings) once per command, so each
    invocation receives a fresh queue of scripted responses.
    """
    queue = list(results)

    def make(_settings: Settings) -> FakeLLM:
        return FakeLLM(extract_responses=list(queue))

    return make


def _chat_factory(*chats: StubChatCompletion):
    """Factory for commands that only call chat_with_tools (e.g. ask)."""
    queue = list(chats)

    def make(_settings: Settings) -> FakeLLM:
        return FakeLLM(chat_responses=list(queue))

    return make


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------
def test_init_creates_database_file(runner: CliRunner, tmp_path: Path) -> None:
    db = tmp_path / "docdb.sqlite"
    result = runner.invoke(main, ["--db", str(db), "init"])
    assert result.exit_code == 0, result.output
    assert db.exists()
    assert "initialised" in result.output


# ---------------------------------------------------------------------------
# ingest + stats + search
# ---------------------------------------------------------------------------
def test_ingest_then_stats_then_search(runner: CliRunner, tmp_path: Path) -> None:
    db = tmp_path / "docdb.sqlite"
    note = tmp_path / "memo.md"
    note.write_text("# 解約条項メモ\n本契約の解約条項について\n", encoding="utf-8")

    extraction = ExtractionResult(
        doc_type="memo",
        title="解約条項メモ",
        summary="契約解除の規定",
        language="ja",
        tags=["契約"],
        entities=[ExtractedEntity(name="解約条項", entity_type="other")],
        todos=[ExtractedTodo(content="関係者に共有")],
    )

    ingest_result = runner.invoke(
        main,
        ["--db", str(db), "ingest", str(note)],
        obj={"llm_factory": _factory(extraction)},
    )
    assert ingest_result.exit_code == 0, ingest_result.output
    assert "+ created" in ingest_result.output

    stats_result = runner.invoke(main, ["--db", str(db), "stats"])
    assert stats_result.exit_code == 0, stats_result.output
    assert "documents: 1" in stats_result.output
    assert "memo: 1" in stats_result.output

    search_result = runner.invoke(
        main, ["--db", str(db), "search", "解約条項"]
    )
    assert search_result.exit_code == 0, search_result.output
    assert "解約条項メモ" in search_result.output


def test_ingest_dir_summarises_results(runner: CliRunner, tmp_path: Path) -> None:
    db = tmp_path / "docdb.sqlite"
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# A\n本文A", encoding="utf-8")
    (notes / "b.md").write_text("# B\n本文B", encoding="utf-8")

    result = runner.invoke(
        main,
        ["--db", str(db), "ingest-dir", str(notes)],
        obj={
            "llm_factory": _factory(
                ExtractionResult(title="A"), ExtractionResult(title="B")
            )
        },
    )
    assert result.exit_code == 0, result.output
    assert "created=2" in result.output


def test_ingest_skips_unchanged_file_on_second_run(
    runner: CliRunner, tmp_path: Path
) -> None:
    db = tmp_path / "docdb.sqlite"
    note = tmp_path / "x.md"
    note.write_text("# X\n本文", encoding="utf-8")

    factory = _factory(ExtractionResult(title="X"))
    first = runner.invoke(
        main, ["--db", str(db), "ingest", str(note)], obj={"llm_factory": factory}
    )
    second = runner.invoke(
        main, ["--db", str(db), "ingest", str(note)], obj={"llm_factory": factory}
    )

    assert "+ created" in first.output
    assert "= skipped" in second.output


def test_search_against_empty_db_prints_no_results_message(
    runner: CliRunner, tmp_path: Path
) -> None:
    db = tmp_path / "docdb.sqlite"
    runner.invoke(main, ["--db", str(db), "init"])
    result = runner.invoke(main, ["--db", str(db), "search", "anything"])
    assert result.exit_code == 0
    assert "(no results)" in result.output


# ---------------------------------------------------------------------------
# ask (agent)
# ---------------------------------------------------------------------------
def _seed_corpus(runner: CliRunner, db: Path, note_path: Path) -> str:
    """Ingest one document and return its document_id."""
    note_path.write_text("# 解約条項メモ\n本契約の解約条項について\n", encoding="utf-8")
    runner.invoke(
        main,
        ["--db", str(db), "ingest", str(note_path)],
        obj={
            "llm_factory": _factory(
                ExtractionResult(doc_type="memo", title="解約条項メモ")
            )
        },
    )
    # Look up the resulting doc id; the CLI does not print it, so we
    # query the DB directly.
    import sqlite3

    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT id FROM documents LIMIT 1").fetchone()
    return row["id"]


def test_ask_prints_answer_and_citations(
    runner: CliRunner, tmp_path: Path
) -> None:
    db = tmp_path / "docdb.sqlite"
    doc_id = _seed_corpus(runner, db, tmp_path / "memo.md")

    chat_factory = _chat_factory(
        StubChatCompletion.tool(
            [("c1", "search_documents", json.dumps({"query": "解約条項"}))]
        ),
        StubChatCompletion.text(
            f"解約条項は 30 日前の通知が必要です [doc:{doc_id}]"
        ),
    )

    result = runner.invoke(
        main,
        ["--db", str(db), "ask", "解約条項について教えて"],
        obj={"llm_factory": chat_factory},
    )

    assert result.exit_code == 0, result.output
    assert "解約条項は 30 日前" in result.output
    assert "citations:" in result.output
    assert doc_id in result.output


def test_ask_with_show_trace_prints_tool_calls(
    runner: CliRunner, tmp_path: Path
) -> None:
    db = tmp_path / "docdb.sqlite"
    _seed_corpus(runner, db, tmp_path / "memo.md")

    chat_factory = _chat_factory(
        StubChatCompletion.tool([("c1", "list_doc_types", "{}")]),
        StubChatCompletion.text("ok"),
    )

    result = runner.invoke(
        main,
        ["--db", str(db), "ask", "doc_type の集計は?", "--show-trace"],
        obj={"llm_factory": chat_factory},
    )

    assert result.exit_code == 0, result.output
    assert "trace:" in result.output
    assert "list_doc_types" in result.output


def test_ask_handles_no_answer_path(runner: CliRunner, tmp_path: Path) -> None:
    db = tmp_path / "docdb.sqlite"
    _seed_corpus(runner, db, tmp_path / "memo.md")

    # LLM returns blank content with no tool calls.
    chat_factory = _chat_factory(StubChatCompletion.text(""))

    result = runner.invoke(
        main,
        ["--db", str(db), "ask", "?"],
        obj={"llm_factory": chat_factory},
    )
    assert result.exit_code == 0
    assert "(no answer)" in result.output


# ---------------------------------------------------------------------------
# migrate-todos
# ---------------------------------------------------------------------------
def test_migrate_todos_imports_legacy_json(runner: CliRunner, tmp_path: Path) -> None:
    db = tmp_path / "docdb.sqlite"

    legacy = [
        {
            "id": "legacy-1",
            "content": "古いタスク",
            "status": "in_progress",
            "priority": "high",
            "due_date": "2026-06-30",
            "source_file": "memo/legacy.md",
            "source_section": "TODO",
            "created_at": "2025-12-01T09:00:00",
            "updated_at": "2026-01-15T10:00:00",
        },
        {
            "id": "legacy-2",
            "content": "",  # empty → must be skipped
            "status": "pending",
            "priority": "low",
            "source_file": "",
            "source_section": "",
            "created_at": "",
            "updated_at": "",
        },
    ]
    legacy_path = tmp_path / "todos.json"
    legacy_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    result = runner.invoke(
        main, ["--db", str(db), "migrate-todos", str(legacy_path)]
    )
    assert result.exit_code == 0, result.output
    assert "imported=1" in result.output
    assert "skipped=1" in result.output

    # The single imported todo lives under the right shape.
    import sqlite3

    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT content, status, priority, due_date FROM todos"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["content"] == "古いタスク"
    assert rows[0]["status"] == "in_progress"
    assert rows[0]["priority"] == "high"
    assert rows[0]["due_date"] == "2026-06-30"


def test_migrate_todos_links_to_existing_document(
    runner: CliRunner, tmp_path: Path
) -> None:
    db = tmp_path / "docdb.sqlite"
    note = tmp_path / "linked.md"
    note.write_text("# 元文書\n本文", encoding="utf-8")

    # Ingest first so the document exists, then run the migration.
    runner.invoke(
        main,
        ["--db", str(db), "ingest", str(note)],
        obj={"llm_factory": _factory(ExtractionResult(title="元文書"))},
    )

    legacy = [
        {
            "content": "リンク対象タスク",
            "source_file": str(note),
            "status": "pending",
            "priority": "medium",
        }
    ]
    legacy_path = tmp_path / "todos.json"
    legacy_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    result = runner.invoke(
        main, ["--db", str(db), "migrate-todos", str(legacy_path)]
    )
    assert result.exit_code == 0, result.output

    import sqlite3

    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT source_document_id FROM todos WHERE content = ?",
            ("リンク対象タスク",),
        ).fetchone()
    assert row["source_document_id"] is not None


def test_migrate_todos_rejects_non_array_json(
    runner: CliRunner, tmp_path: Path
) -> None:
    db = tmp_path / "docdb.sqlite"
    f = tmp_path / "todos.json"
    f.write_text('{"not": "a list"}', encoding="utf-8")
    result = runner.invoke(main, ["--db", str(db), "migrate-todos", str(f)])
    assert result.exit_code != 0
    assert "does not contain a JSON array" in result.output
