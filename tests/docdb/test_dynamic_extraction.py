"""Tests for the Stage 3 dynamic-extraction surface.

Covers:
- build_extraction_model: dynamic schema includes the right ``entities`` and
  ``relations`` shape, with type slugs constrained to a Literal.
- build_extraction_system_prompt: every registered slug + extraction_hint
  appears, and the 30KB cap truncates rather than crashing.
- Normalizer + pipeline: unknown-type entities and unresolved relations are
  dropped (with diagnostic notes); valid ones are written.
- Deterministic task_checkbox extractor: pulls Markdown ``- [ ]`` items and
  feeds them to the pipeline so `task` entities are created without an LLM.
- extract_relations flag short-circuits relation writes.
"""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import BaseModel, ValidationError

from docdb.ingestion.normalizer import (
    NormalizationDrop,
    normalize_extraction,
)
from docdb.ingestion.pipeline import IngestionPipeline
from docdb.ingestion.store import DocumentStore
from docdb.llm.fake import FakeLLM
from docdb.llm.prompts import (
    EXTRACTION_PROMPT_MAX_BYTES,
    build_extraction_system_prompt,
)
from docdb.models import ExtractionResult, entity_id_for, relation_id_for
from docdb.typing.deterministic import task_checkbox
from docdb.typing.dynamic_model import build_extraction_model, clear_cache
from docdb.typing.registry import (
    EntityTypeDef,
    RelationTypeDef,
    list_entity_types,
    list_relation_types,
    registry_hash,
    upsert_entity_type,
)


# ---------------------------------------------------------------------------
# Dynamic Pydantic model
# ---------------------------------------------------------------------------
class TestBuildExtractionModel:
    def setup_method(self) -> None:
        clear_cache()

    def test_no_entity_types_returns_bare_extraction_result(self) -> None:
        Model = build_extraction_model(
            entity_type_slugs=[], relation_type_slugs=[], registry_hash="empty"
        )
        assert Model is ExtractionResult

    def test_with_entity_types_extends_result(self) -> None:
        Model = build_extraction_model(
            entity_type_slugs=["person", "task"],
            relation_type_slugs=["assigned_to"],
            registry_hash="abc123",
        )
        assert issubclass(Model, ExtractionResult)
        assert "entities" in Model.model_fields
        assert "relations" in Model.model_fields

    def test_entity_type_field_is_literal_constrained(self) -> None:
        Model = build_extraction_model(
            entity_type_slugs=["person"],
            relation_type_slugs=[],
            registry_hash="lit-test",
        )
        # Valid slug works.
        ok = Model(entities=[{"type": "person", "name": "Alice"}])
        assert ok.entities[0].type == "person"  # type: ignore[attr-defined]
        # Unknown slug raises ValidationError thanks to the Literal.
        with pytest.raises(ValidationError):
            Model(entities=[{"type": "alien", "name": "x"}])

    def test_cache_reuses_same_class_for_same_hash(self) -> None:
        A = build_extraction_model(
            entity_type_slugs=["person"], relation_type_slugs=[], registry_hash="hash-A"
        )
        B = build_extraction_model(
            entity_type_slugs=["person"], relation_type_slugs=[], registry_hash="hash-A"
        )
        assert A is B

    def test_distinct_registry_hash_yields_distinct_class(self) -> None:
        A = build_extraction_model(
            entity_type_slugs=["person"], relation_type_slugs=[], registry_hash="hash-A"
        )
        B = build_extraction_model(
            entity_type_slugs=["person"], relation_type_slugs=[], registry_hash="hash-B"
        )
        assert A is not B


# ---------------------------------------------------------------------------
# Dynamic system prompt
# ---------------------------------------------------------------------------
class TestBuildExtractionSystemPrompt:
    def test_mentions_every_registered_slug(self, conn: sqlite3.Connection) -> None:
        entity_types = list_entity_types(conn)
        relation_types = list_relation_types(conn)
        prompt = build_extraction_system_prompt(entity_types, relation_types)
        for t in entity_types:
            assert t.slug in prompt
        for t in relation_types:
            assert t.slug in prompt

    def test_includes_extraction_hint(self, conn: sqlite3.Connection) -> None:
        task = next(t for t in list_entity_types(conn) if t.slug == "task")
        prompt = build_extraction_system_prompt([task], [])
        assert task.extraction_hint is not None
        # Some prefix of the hint should appear (it can be long).
        assert task.extraction_hint[:20] in prompt

    def test_includes_task_field_summary(self, conn: sqlite3.Connection) -> None:
        task = next(t for t in list_entity_types(conn) if t.slug == "task")
        prompt = build_extraction_system_prompt([task], [])
        assert "status" in prompt
        assert "priority" in prompt
        assert "due_date" in prompt

    def test_empty_registry_returns_base_only(self) -> None:
        prompt = build_extraction_system_prompt([], [])
        assert "doc_type" in prompt
        assert "entities[]" not in prompt
        assert "relations[]" not in prompt

    def test_relation_types_are_only_shown_when_entity_types_exist(self) -> None:
        rel = RelationTypeDef.model_validate(
            {"slug": "manages", "label": "管理", "fields_schema": []}
        )
        prompt = build_extraction_system_prompt([], [rel])
        # No entity types → the relation-type catalog header is omitted, and
        # this specific slug is not rendered. (The static JSON-shape example
        # in EXTRACTION_SYSTEM_BASE legitimately mentions the seeded
        # `assigned_to` slug as a placeholder, so we pick a different slug
        # for this assertion.)
        assert "# 抽出できる relation 型" not in prompt
        assert "manages" not in prompt

    def test_byte_cap_truncates_rather_than_crashes(self, conn: sqlite3.Connection) -> None:
        entity_types = list_entity_types(conn)
        relation_types = list_relation_types(conn)
        prompt = build_extraction_system_prompt(
            entity_types, relation_types, max_bytes=600
        )
        assert len(prompt.encode("utf-8")) <= 700  # cap + small truncation marker
        assert "省略" in prompt

    def test_default_cap_is_30kb(self) -> None:
        assert EXTRACTION_PROMPT_MAX_BYTES == 30_000


# ---------------------------------------------------------------------------
# Normalizer: unknown-type drop + unresolved-relation drop
# ---------------------------------------------------------------------------
class TestNormalizerStage3:
    def _make_payload(
        self,
        entities: list[dict] | None = None,
        relations: list[dict] | None = None,
    ) -> BaseModel:
        Model = build_extraction_model(
            entity_type_slugs=["person", "task"],
            relation_type_slugs=["assigned_to"],
            registry_hash="norm-test",
        )
        return Model(entities=entities or [], relations=relations or [])

    def test_drops_unknown_type_entity_with_diagnostic(self) -> None:
        # Build a "stricter-LLM-bypassed" model that allows the ghost type so
        # we can feed it through normaliser; the normaliser must drop it because
        # ``entity_type_slugs`` (the registry) does not include 'ghost'.
        LooseModel = build_extraction_model(
            entity_type_slugs=["person", "ghost"],
            relation_type_slugs=[],
            registry_hash="drop-test",
        )
        result = LooseModel(
            entities=[
                {"type": "person", "name": "Alice"},
                {"type": "ghost", "name": "ナナミ"},
            ]
        )
        norm = normalize_extraction(
            result,
            document_id="doc-1",
            entity_type_slugs={"person", "task"},  # registry; ghost is unknown
        )
        assert len(norm.entities) == 1
        assert norm.entities[0].canonical_name == "Alice"
        assert any(d.kind == "unknown_entity_type" for d in norm.drops)

    def test_resolves_relation_by_type_and_name(self) -> None:
        payload = self._make_payload(
            entities=[
                {"type": "task", "name": "design review",
                 "fields": {"status": "pending", "priority": "high"}},
                {"type": "person", "name": "Alice"},
            ],
            relations=[
                {"type": "assigned_to",
                 "source": {"type": "task", "name": "design review"},
                 "target": {"type": "person", "name": "Alice"}},
            ],
        )
        norm = normalize_extraction(
            payload,
            document_id="doc-1",
            entity_type_slugs={"person", "task"},
            relation_type_slugs={"assigned_to"},
        )
        assert len(norm.relations) == 1
        rel = norm.relations[0]
        assert rel.source_entity_id == entity_id_for("task", "design review")
        assert rel.target_entity_id == entity_id_for("person", "Alice")
        # Deterministic relation id.
        assert rel.id == relation_id_for(
            "assigned_to", rel.source_entity_id, rel.target_entity_id
        )

    def test_drops_relation_with_unresolved_source(self) -> None:
        payload = self._make_payload(
            entities=[{"type": "person", "name": "Alice"}],
            relations=[
                {"type": "assigned_to",
                 "source": {"type": "task", "name": "missing-task"},
                 "target": {"type": "person", "name": "Alice"}},
            ],
        )
        norm = normalize_extraction(
            payload,
            document_id="doc-1",
            entity_type_slugs={"person", "task"},
            relation_type_slugs={"assigned_to"},
        )
        assert norm.relations == []
        assert any(d.kind == "unresolved_relation" for d in norm.drops)

    def test_relation_with_null_target_is_accepted_then_dropped(self) -> None:
        # Regression: small LLMs honestly emit ``target: null`` when the source
        # text does not name a counterpart. Pydantic must accept the payload so
        # that the rest of the extraction (entities!) survives; the normaliser
        # then drops the dangling relation as ``unresolved_relation``.
        Model = build_extraction_model(
            entity_type_slugs=["person", "task"],
            relation_type_slugs=["assigned_to"],
            registry_hash="null-target-test",
        )
        payload = Model(
            entities=[
                {"type": "task", "name": "write spec",
                 "fields": {"status": "pending", "priority": "medium"}},
                {"type": "person", "name": "Tanaka"},
            ],
            relations=[
                {"type": "assigned_to",
                 "source": {"type": "task", "name": "write spec"},
                 "target": None},
            ],
        )
        # Sanity: schema accepted the null target rather than raising.
        assert payload.relations[0].target is None

        norm = normalize_extraction(
            payload,
            document_id="doc-1",
            entity_type_slugs={"person", "task"},
            relation_type_slugs={"assigned_to"},
        )
        # The orphan relation is dropped, but both entities survive — that is
        # the whole point of allowing null targets at the schema layer.
        assert norm.relations == []
        assert any(d.kind == "unresolved_relation" for d in norm.drops)
        assert {e.canonical_name for e in norm.entities} == {"write spec", "Tanaka"}

    def test_extract_relations_false_skips_relations(self) -> None:
        payload = self._make_payload(
            entities=[
                {"type": "task", "name": "x", "fields": {"status": "pending", "priority": "medium"}},
                {"type": "person", "name": "y"},
            ],
            relations=[
                {"type": "assigned_to",
                 "source": {"type": "task", "name": "x"},
                 "target": {"type": "person", "name": "y"}},
            ],
        )
        norm = normalize_extraction(
            payload,
            document_id="doc-1",
            entity_type_slugs={"person", "task"},
            relation_type_slugs={"assigned_to"},
            extract_relations=False,
        )
        assert norm.entities, "entities still produced"
        assert norm.relations == []


# ---------------------------------------------------------------------------
# Deterministic extractor
# ---------------------------------------------------------------------------
class TestTaskCheckbox:
    def test_pulls_pending_checkbox_with_priority(self) -> None:
        text = "- [ ] urgent: 設計レビュー\n- [x] 終わったやつ\n- [ ] 普通のタスク\n"
        out = task_checkbox(text)
        contents = {item["name"]: item["fields"]["priority"] for item in out}
        assert contents == {"urgent: 設計レビュー": "high", "普通のタスク": "medium"}

    def test_skips_too_short_entries(self) -> None:
        assert task_checkbox("- [ ] ab\n") == []

    def test_deduplicates_identical_bodies(self) -> None:
        out = task_checkbox("- [ ] 同じタスク\nTODO: 同じタスク\n")
        assert len(out) == 1


# ---------------------------------------------------------------------------
# End-to-end pipeline integration
# ---------------------------------------------------------------------------
class TestPipelineStage3:
    def test_ingest_creates_task_entity_via_deterministic_extractor(self, conn) -> None:
        # LLM script: empty extraction. Deterministic extractor finds the TODO.
        fake = FakeLLM(extract_responses=[ExtractionResult(title="t")])
        pipeline = IngestionPipeline(store=DocumentStore(conn), llm=fake)
        report = pipeline.ingest_text(
            "# メモ\n- [ ] 緊急の設計レビュー\n",
            source_path="memo/x.md",
        )
        assert report.status == "created"
        assert report.entities_added_by_type.get("task") == 1

        # The task entity exists with the deterministic priority inference.
        row = conn.execute(
            "SELECT canonical_name, json_extract(fields, '$.priority') AS prio "
            "FROM entities WHERE type_slug = 'task'"
        ).fetchone()
        assert row["canonical_name"] == "緊急の設計レビュー"
        assert row["prio"] == "high"

    def test_pipeline_writes_relation_when_payload_resolves(self, conn) -> None:
        Model = build_extraction_model(
            entity_type_slugs=["person", "task"],
            relation_type_slugs=["assigned_to"],
            registry_hash=registry_hash(conn),
        )
        scripted = Model(
            title="t",
            entities=[
                {"type": "task", "name": "code review",
                 "fields": {"status": "pending", "priority": "high"}},
                {"type": "person", "name": "Alice"},
            ],
            relations=[
                {"type": "assigned_to",
                 "source": {"type": "task", "name": "code review"},
                 "target": {"type": "person", "name": "Alice"}},
            ],
        )
        fake = FakeLLM(extract_responses=[scripted])
        pipeline = IngestionPipeline(store=DocumentStore(conn), llm=fake)
        report = pipeline.ingest_text("本文", source_path="memo/r.md")
        assert report.relations_added == 1

        row = conn.execute(
            "SELECT type_slug FROM relations WHERE type_slug = 'assigned_to'"
        ).fetchone()
        assert row is not None

    def test_extract_relations_false_pipeline_writes_no_relations(self, conn) -> None:
        Model = build_extraction_model(
            entity_type_slugs=["person", "task"],
            relation_type_slugs=["assigned_to"],
            registry_hash=registry_hash(conn),
        )
        scripted = Model(
            title="t",
            entities=[
                {"type": "task", "name": "x",
                 "fields": {"status": "pending", "priority": "medium"}},
                {"type": "person", "name": "y"},
            ],
            relations=[
                {"type": "assigned_to",
                 "source": {"type": "task", "name": "x"},
                 "target": {"type": "person", "name": "y"}},
            ],
        )
        fake = FakeLLM(extract_responses=[scripted])
        pipeline = IngestionPipeline(
            store=DocumentStore(conn), llm=fake, extract_relations=False
        )
        report = pipeline.ingest_text("本文", source_path="memo/n.md")
        assert report.relations_added == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM relations").fetchone()["n"] == 0

    def test_validation_error_reports_extraction_warning(self, conn) -> None:
        """An LLM-emitted entity with a bad enum value lands as a non-fatal note."""
        Model = build_extraction_model(
            entity_type_slugs=["person", "task"],
            relation_type_slugs=["assigned_to"],
            registry_hash=registry_hash(conn),
        )
        scripted = Model(
            title="t",
            entities=[
                # Bad status → upsert_entity raises ValueError, pipeline records it.
                {"type": "task", "name": "broken",
                 "fields": {"status": "definitely_not_a_status", "priority": "medium"}},
            ],
        )
        fake = FakeLLM(extract_responses=[scripted])
        pipeline = IngestionPipeline(store=DocumentStore(conn), llm=fake)
        report = pipeline.ingest_text("本文", source_path="memo/v.md")
        assert report.status == "created"
        assert report.entities_added_by_type == {}
        assert report.extraction_error and "broken" in report.extraction_error
