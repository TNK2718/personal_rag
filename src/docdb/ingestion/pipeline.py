"""End-to-end ingestion orchestrator.

Glue layer over parser → extractor → normalizer → store.

The pipeline guarantees:

* **content-hash idempotency** — re-running ingest on an unchanged file
  returns status "skipped" without touching the DB or the LLM.
* **clean updates** — when a file's content changes, the old document
  rows (and its entity/tag links) are deleted before the new ones are
  written, so the corpus never accumulates stale rows from earlier
  ingests of the same source_path.
* **graceful degradation** — an LLM failure does not break ingestion;
  the document, its raw text, and a heuristic title still land in the
  DB and the IngestionReport carries the error message.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Literal

from docdb.ingestion.extractor import Extractor
from docdb.ingestion.normalizer import normalize_extraction
from docdb.ingestion.parser import ParsedDocument, Parser
from docdb.ingestion.store import DocumentStore
from docdb.llm.base import LLMProtocol
from docdb.models import (
    Document,
    DocType,
    Language,
    SourceType,
    content_hash_for,
    document_id_for,
)


Status = Literal["created", "updated", "skipped", "error"]


@dataclass
class IngestionReport:
    source_path: str
    status: Status
    document_id: str | None = None
    todos_added: int = 0
    entities_added: int = 0
    tags_added: int = 0
    error: str | None = None
    extraction_error: str | None = None  # non-fatal


@dataclass
class IngestionPipeline:
    store: DocumentStore
    llm: LLMProtocol
    parser: Parser = field(default_factory=Parser)
    extractor: Extractor | None = None

    def __post_init__(self) -> None:
        if self.extractor is None:
            self.extractor = Extractor(self.llm)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------
    def ingest_file(self, path: Path | str) -> IngestionReport:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return IngestionReport(
                source_path=str(path), status="error", error=str(exc)
            )
        return self.ingest_text(text, source_path=str(path))

    def ingest_text(
        self,
        text: str,
        *,
        source_path: str,
        source_type: SourceType | None = None,
    ) -> IngestionReport:
        h = content_hash_for(text)
        if existing := self._lookup_by_hash(h):
            return IngestionReport(
                source_path=source_path,
                status="skipped",
                document_id=existing,
            )

        st = source_type or _source_type_for_path(source_path)
        if st == "md":
            parsed = self.parser.parse_markdown(text, source_path=source_path)
        else:
            parsed = self.parser.parse_text(text, source_path=source_path, source_type=st)

        return self._ingest_parsed(parsed)

    def ingest_directory(
        self,
        root: Path | str,
        *,
        glob: str = "**/*.md",
    ) -> Iterator[IngestionReport]:
        root = Path(root)
        for path in sorted(root.glob(glob)):
            if path.is_file():
                yield self.ingest_file(path)

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------
    def _ingest_parsed(self, parsed: ParsedDocument) -> IngestionReport:
        doc_id = document_id_for(parsed.content_hash)
        is_update = self._existing_document_id_for_source(parsed.source_path) is not None
        if is_update:
            self.store.delete_by_source(parsed.source_path)

        outcome = self.extractor.extract(parsed)
        result = outcome.result

        doc = Document(
            id=doc_id,
            source_path=parsed.source_path,
            source_type=parsed.source_type,
            content_hash=parsed.content_hash,
            title=result.title or parsed.title,
            doc_type=_safe_doc_type(result.doc_type),
            summary=result.summary,
            raw_text=parsed.raw_text,
            language=_safe_language(result.language),
            created_at=_creation_date_from_frontmatter(parsed),
            metadata={"frontmatter": parsed.frontmatter} if parsed.frontmatter else {},
        )

        embed_text = _embedding_text(doc)
        try:
            [embedding] = self.llm.embed([embed_text])
        except Exception as exc:  # noqa: BLE001
            return IngestionReport(
                source_path=parsed.source_path,
                status="error",
                document_id=doc_id,
                error=f"embed failed: {type(exc).__name__}: {exc}",
                extraction_error=outcome.error,
            )

        self.store.upsert_document(doc, embedding=embedding)

        norm = normalize_extraction(result, document_id=doc_id)
        for ent in norm.entities:
            self.store.upsert_entity(ent)
        for tag in norm.tags:
            self.store.upsert_tag(tag)
        for link in norm.entity_links:
            self.store.link_document_entity(
                link.document_id,
                link.entity_id,
                mention_count=link.mention_count,
                contexts=link.contexts,
            )
        for link in norm.tag_links:
            self.store.link_document_tag(
                link.document_id,
                link.tag_id,
                confidence=link.confidence,
                source=link.source,
            )
        for todo in norm.todos:
            self.store.upsert_todo(todo)

        return IngestionReport(
            source_path=parsed.source_path,
            status="updated" if is_update else "created",
            document_id=doc_id,
            todos_added=len(norm.todos),
            entities_added=len(norm.entities),
            tags_added=len(norm.tags),
            extraction_error=outcome.error,
        )

    # ------------------------------------------------------------------
    # DB peeks
    # ------------------------------------------------------------------
    def _lookup_by_hash(self, content_hash: str) -> str | None:
        row = self.store.conn.execute(
            "SELECT id FROM documents WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return row["id"] if row else None

    def _existing_document_id_for_source(self, source_path: str) -> str | None:
        row = self.store.conn.execute(
            "SELECT id FROM documents WHERE source_path = ?", (source_path,)
        ).fetchone()
        return row["id"] if row else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _creation_date_from_frontmatter(parsed: ParsedDocument) -> str | None:
    """Pull a YYYY-MM-DD out of the frontmatter (date / created) or the
    filename if it begins with one. Used to seed documents.created_at."""
    for key in ("date", "created", "created_at"):
        raw = parsed.frontmatter.get(key)
        if not raw:
            continue
        if m := _DATE_RE.search(raw):
            return m.group(1)
    if m := _DATE_RE.search(Path(parsed.source_path).name):
        return m.group(1)
    return None


def _source_type_for_path(path: str) -> SourceType:
    suffix = Path(path).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix in {".txt", ""}:
        return "txt"
    if suffix == ".pdf":
        return "pdf"
    return "txt"


_DOC_TYPES = {"memo", "meeting", "journal", "reference", "spec", "other"}


def _safe_doc_type(value: str | None) -> DocType:
    if value in _DOC_TYPES:
        return value  # type: ignore[return-value]
    return "other"


_LANGUAGES = {"ja", "en", "mixed", "other"}


def _safe_language(value: str | None) -> Language:
    if value in _LANGUAGES:
        return value  # type: ignore[return-value]
    return "other"


def _embedding_text(doc: Document) -> str:
    """Title + summary makes for a stable, model-friendly embed input
    that does not blow up on very long raw_text fields."""
    parts: list[str] = []
    if doc.title:
        parts.append(doc.title)
    if doc.summary:
        parts.append(doc.summary)
    if not parts and doc.raw_text:
        parts.append(doc.raw_text[:512])
    return "\n\n".join(parts) or (doc.id or "empty")
