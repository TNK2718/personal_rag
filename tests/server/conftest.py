from __future__ import annotations

from pathlib import Path

import pytest

from docdb.config import Settings
from docdb.ingestion import DocumentStore
from docdb.llm.fake import FakeLLM
from docdb.schema.connection import connection, init_db

from server.app import create_app
from tests.docdb.fixtures import (
    SAMPLE_DOCS,
    SAMPLE_ENTITIES,
    SAMPLE_TAGS,
    SAMPLE_TODOS,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "docdb.sqlite", data_dir=tmp_path / "data")


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def seeded_db(settings: Settings) -> Settings:
    """Initialise the DB and seed with sample documents/entities/tags/todos."""
    init_db(settings.db_path)
    with connection(settings.db_path) as conn:
        store = DocumentStore(conn)
        embedding = [0.0] * 1024
        for doc in SAMPLE_DOCS:
            store.upsert_document(doc, embedding=embedding)
        for ent in SAMPLE_ENTITIES:
            store.upsert_entity(ent)
        for tag in SAMPLE_TAGS:
            store.upsert_tag(tag)
        for todo in SAMPLE_TODOS:
            store.upsert_todo(todo)
        # Link the project-A meeting to entity "プロジェクトA".
        store.link_document_entity(
            SAMPLE_DOCS[1].id, SAMPLE_ENTITIES[1].id, mention_count=3, contexts=["..."]
        )
        store.link_document_tag(
            SAMPLE_DOCS[0].id, SAMPLE_TAGS[0].id, confidence=0.9
        )
    return settings


@pytest.fixture
def app(seeded_db: Settings, fake_llm: FakeLLM):
    app = create_app(settings=seeded_db, llm_factory=lambda _s: fake_llm)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()
