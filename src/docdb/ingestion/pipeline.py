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

Stage 3 reads the entity/relation type registry from the store
connection at construction time, hands it to the ``Extractor`` to build
the dynamic LLM schema and prompt, and merges deterministic-extractor
output before normalisation. Field-value validation against the
registered ``fields_schema`` runs at write time in ``DocumentStore``;
entities whose ``fields`` fail validation are reported as
``extraction_error`` notes on the ingestion report rather than crashing
the run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Literal

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
    document_id_for,
    content_hash_for,
)
from docdb.typing.deterministic import run_for_types
from docdb.typing.registry import (
    list_entity_types,
    list_relation_types,
    registry_hash,
)


Status = Literal["created", "updated", "skipped", "error"]


@dataclass
class IngestionReport:
    source_path: str
    status: Status
    document_id: str | None = None
    tags_added: int = 0
    error: str | None = None
    extraction_error: str | None = None  # non-fatal
    entities_added_by_type: dict[str, int] = field(default_factory=dict)
    relations_added: int = 0


@dataclass
class IngestionPipeline:
    store: DocumentStore
    llm: LLMProtocol
    parser: Parser = field(default_factory=Parser)
    extractor: Extractor | None = None
    extract_relations: bool = True

    def __post_init__(self) -> None:
        # The registry is read once at construction. Tests that mutate the
        # registry mid-run should build a fresh pipeline; ingest-dir from
        # the CLI is short-lived enough that staleness is not a concern.
        self._entity_types = list_entity_types(self.store.conn)
        self._relation_types = list_relation_types(self.store.conn)
        self._registry_hash = registry_hash(self.store.conn)
        self._entity_slugs = {t.slug for t in self._entity_types}
        self._relation_slugs = {t.slug for t in self._relation_types}

        if self.extractor is None:
            self.extractor = Extractor(
                self.llm,
                entity_types=self._entity_types,
                relation_types=self._relation_types,
                registry_hash=self._registry_hash,
            )

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

        # Merge deterministic extractor output into the LLM-emitted entities so
        # the normaliser's dedup logic catches duplicates without special-casing.
        det_entities = run_for_types(parsed.raw_text, sorted(self._entity_slugs))
        _attach_deterministic_entities(result, det_entities)

        doc = Document(
            id=doc_id,
            source_path=parsed.source_path,
            source_type=parsed.source_type,
            content_hash=parsed.content_hash,
            title=getattr(result, "title", None) or parsed.title,
            doc_type=_safe_doc_type(getattr(result, "doc_type", None)),
            summary=getattr(result, "summary", "") or "",
            raw_text=parsed.raw_text,
            language=_safe_language(getattr(result, "language", None)),
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

        norm = normalize_extraction(
            result,
            document_id=doc_id,
            entity_type_slugs=self._entity_slugs or None,
            relation_type_slugs=self._relation_slugs or None,
            extract_relations=self.extract_relations,
        )

        # Tags
        for tag in norm.tags:
            self.store.upsert_tag(tag)
        for link in norm.tag_links:
            self.store.link_document_tag(
                link.document_id,
                link.tag_id,
                confidence=link.confidence,
                source=link.source,
            )

        # Entities — write each through the store so field validation runs.
        per_type_counts: dict[str, int] = {}
        validation_errors: list[str] = []
        accepted_entity_ids: set[str] = set()
        for ent in norm.entities:
            try:
                self.store.upsert_entity(ent)
            except ValueError as exc:
                validation_errors.append(f"entity {ent.canonical_name!r}: {exc}")
                continue
            per_type_counts[ent.type_slug] = per_type_counts.get(ent.type_slug, 0) + 1
            accepted_entity_ids.add(ent.id)

        for link in norm.entity_links:
            if link.entity_id not in accepted_entity_ids:
                continue
            self.store.link_document_entity(
                link.document_id,
                link.entity_id,
                mention_count=link.mention_count,
                contexts=link.contexts,
            )

        # Relations — drop ones referencing entities that didn't make it.
        relations_added = 0
        for rel in norm.relations:
            if (
                rel.source_entity_id not in accepted_entity_ids
                or rel.target_entity_id not in accepted_entity_ids
            ):
                continue
            try:
                self.store.upsert_relation(rel)
            except ValueError as exc:
                validation_errors.append(f"relation {rel.id}: {exc}")
                continue
            relations_added += 1
        for link in norm.relation_links:
            self.store.link_document_relation(
                link.document_id, link.relation_id, contexts=link.contexts
            )

        # Surface non-fatal extraction notes (validation drops + normaliser drops)
        # on the report so the CLI / UI can show them.
        notes: list[str] = []
        if outcome.error:
            notes.append(outcome.error)
        notes.extend(validation_errors)
        for drop in norm.drops:
            notes.append(f"dropped {drop.kind}: {drop.reason}")

        return IngestionReport(
            source_path=parsed.source_path,
            status="updated" if is_update else "created",
            document_id=doc_id,
            tags_added=len(norm.tags),
            entities_added_by_type=per_type_counts,
            relations_added=relations_added,
            extraction_error="; ".join(notes) if notes else None,
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


def _attach_deterministic_entities(result, det_entities: list[dict]) -> None:
    """Merge deterministic-extractor entity dicts into the LLM result.

    The dynamic schema may not have an ``entities`` attribute (when no
    entity types are registered at all). When it does, append; the
    normaliser handles dedup by (type, canonical_name).
    """
    if not det_entities:
        return
    existing = getattr(result, "entities", None)
    if existing is None:
        # No entity types registered; deterministic output is useless here.
        return
    # ``entities`` is a list of pydantic instances. We append plain dicts
    # because the normaliser accepts either form (_safe_attr).
    existing.extend(det_entities)