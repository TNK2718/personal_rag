"""``docdb`` command-line entry point.

The CLI is the user-visible surface for the ingestion stack. Every
subcommand is a thin wrapper over the library API so the same logic
runs from tests, from cron, and from the upcoming Flask server.

Subcommands:
    docdb init
    docdb ingest <PATH>
    docdb ingest-dir <DIR> [--glob ...]
    docdb stats
    docdb search <QUERY> [--top-k] [--doc-type]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from docdb.agent.loop import SearchAgent
from docdb.agent.toolbox import Toolbox
from docdb.config import Settings, get_settings
from docdb.ingestion import (
    DocumentStore,
    IngestionPipeline,
    IngestionReport,
)
from docdb.llm.base import LLMProtocol
from docdb.llm.client import LLM
from docdb.schema.connection import connection, init_db
from docdb.search.direct import (
    count_documents,
    list_doc_types,
    search as direct_search,
)


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------
def _resolve_settings(db_path: Path | None) -> Settings:
    s = get_settings()
    if db_path is not None:
        s = s.model_copy(update={"db_path": db_path})
    return s


def _make_llm(settings: Settings) -> LLMProtocol:
    """Real Ollama-backed client by default; override via a Click ctx for tests."""
    return LLM(settings)


# ---------------------------------------------------------------------------
# Click root
# ---------------------------------------------------------------------------
@click.group()
@click.option(
    "--db",
    "db_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Override DOCDB_DB_PATH for this invocation.",
)
@click.pass_context
def main(ctx: click.Context, db_path: Path | None) -> None:
    """DocDB: local agentic search over a personal markdown corpus."""
    settings = _resolve_settings(db_path)
    ctx.ensure_object(dict)
    ctx.obj.setdefault("settings", settings)
    # llm_factory is overridable in tests via ctx.obj["llm_factory"].
    ctx.obj.setdefault("llm_factory", _make_llm)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------
@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Create the SQLite file and apply schema.sql idempotently."""
    settings: Settings = ctx.obj["settings"]
    init_db(settings.db_path)
    click.echo(f"initialised {settings.db_path}")


# ---------------------------------------------------------------------------
# ingest / ingest-dir
# ---------------------------------------------------------------------------
def _print_report(report: IngestionReport) -> None:
    badge = {
        "created": "+",
        "updated": "~",
        "skipped": "=",
        "error": "!",
    }[report.status]
    extra = []
    if report.tags_added:
        extra.append(f"tags={report.tags_added}")
    for slug, count in (report.entities_added_by_type or {}).items():
        extra.append(f"{slug}={count}")
    suffix = f"  [{', '.join(extra)}]" if extra else ""
    line = f"{badge} {report.status:<8} {report.source_path}{suffix}"
    click.echo(line)
    if report.error:
        click.echo(f"    error: {report.error}", err=True)
    if report.extraction_error:
        click.echo(f"    extraction warning: {report.extraction_error}", err=True)


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def ingest(ctx: click.Context, path: Path) -> None:
    """Ingest a single file."""
    settings: Settings = ctx.obj["settings"]
    init_db(settings.db_path)
    llm = ctx.obj["llm_factory"](settings)
    with connection(settings.db_path) as conn:
        pipeline = IngestionPipeline(store=DocumentStore(conn), llm=llm)
        report = pipeline.ingest_file(path)
    _print_report(report)
    if report.status == "error":
        sys.exit(1)


@main.command("ingest-dir")
@click.argument(
    "directory",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--glob", "glob_pattern", default="**/*.md", show_default=True)
@click.pass_context
def ingest_dir(ctx: click.Context, directory: Path, glob_pattern: str) -> None:
    """Recursively ingest every file under DIRECTORY that matches --glob."""
    settings: Settings = ctx.obj["settings"]
    init_db(settings.db_path)
    llm = ctx.obj["llm_factory"](settings)
    counts: dict[str, int] = {"created": 0, "updated": 0, "skipped": 0, "error": 0}
    targets = [p for p in sorted(directory.glob(glob_pattern)) if p.is_file()]
    total = len(targets)
    click.echo(f"found {total} file(s) matching {glob_pattern} under {directory}")
    if total == 0:
        return
    with connection(settings.db_path) as conn:
        pipeline = IngestionPipeline(store=DocumentStore(conn), llm=llm)
        for i, path in enumerate(targets, 1):
            click.echo(f"[{i}/{total}] processing {path} ...", nl=True)
            sys.stdout.flush()
            report = pipeline.ingest_file(path)
            _print_report(report)
            counts[report.status] = counts.get(report.status, 0) + 1
    click.echo(
        "\nsummary: "
        + " ".join(f"{k}={v}" for k, v in counts.items() if v)
    )


# ---------------------------------------------------------------------------
# stats / search
# ---------------------------------------------------------------------------
@main.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Print row counts for the corpus."""
    settings: Settings = ctx.obj["settings"]
    with connection(settings.db_path, readonly=True) as conn:
        total = count_documents(conn)
        breakdown = list_doc_types(conn)
        by_type = conn.execute(
            "SELECT type_slug, COUNT(*) AS n FROM entities "
            "GROUP BY type_slug ORDER BY n DESC, type_slug"
        ).fetchall()
        relations = conn.execute("SELECT COUNT(*) AS n FROM relations").fetchone()["n"]
        tags = conn.execute("SELECT COUNT(*) AS n FROM tags").fetchone()["n"]

    click.echo(f"documents: {total}")
    for name, n in breakdown:
        click.echo(f"  {name}: {n}")
    click.echo("entities:")
    if not by_type:
        click.echo("  (none)")
    for r in by_type:
        click.echo(f"  {r['type_slug']}: {int(r['n'])}")
    click.echo(f"relations: {int(relations)}")
    click.echo(f"tags:      {int(tags)}")


@main.command()
@click.argument("query")
@click.option("--top-k", default=10, show_default=True, type=int)
@click.option("--doc-type", default=None)
@click.pass_context
def search(ctx: click.Context, query: str, top_k: int, doc_type: str | None) -> None:
    """Run an FTS search and print the top matches."""
    settings: Settings = ctx.obj["settings"]
    with connection(settings.db_path, readonly=True) as conn:
        hits = direct_search(conn, query, top_k=top_k, doc_type=doc_type)
    if not hits:
        click.echo("(no results)")
        return
    for c in hits:
        score = f"{c.score:.3f}" if c.score is not None else "  -  "
        click.echo(f"{score}  {c.document_id}  {c.title or c.source_path or ''}")
        if c.snippet:
            click.echo(f"        {c.snippet}")


# ---------------------------------------------------------------------------
# ask (agent)
# ---------------------------------------------------------------------------
@main.command()
@click.argument("question")
@click.option("--max-iters", default=8, show_default=True, type=int)
@click.option(
    "--show-trace/--no-show-trace",
    default=False,
    help="Print every tool call and its arguments after the answer.",
)
@click.pass_context
def ask(
    ctx: click.Context,
    question: str,
    max_iters: int,
    show_trace: bool,
) -> None:
    """Ask the agent a natural-language question."""
    settings: Settings = ctx.obj["settings"]
    llm = ctx.obj["llm_factory"](settings)
    with connection(settings.db_path) as conn:
        toolbox = Toolbox(conn, llm)
        agent = SearchAgent(toolbox=toolbox, llm=llm, max_iters=max_iters)
        result = agent.run(question)

    if result.error:
        click.echo(f"error: {result.error}", err=True)
        sys.exit(1)

    click.echo(result.answer or "(no answer)")
    if result.exhausted:
        click.echo(
            f"\n[warning] agent reached max_iters={max_iters} without a "
            "final answer",
            err=True,
        )

    if result.citations:
        click.echo("\ncitations:")
        for c in result.citations:
            label = c.title or c.source_path or ""
            click.echo(f"  - {c.document_id}  {label}")

    if show_trace:
        click.echo("\ntrace:")
        for t in result.trace:
            badge = "!" if t.error else "·"
            args_repr = json.dumps(t.arguments, ensure_ascii=False)
            click.echo(f"  [{t.iteration}] {badge} {t.tool}({args_repr})")
            if t.error:
                click.echo(f"      error: {t.error}")


if __name__ == "__main__":  # pragma: no cover
    main()
