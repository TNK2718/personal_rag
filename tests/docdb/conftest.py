from __future__ import annotations

from pathlib import Path

import pytest

from docdb.ingestion.store import DocumentStore
from docdb.llm.fake import FakeLLM
from docdb.schema.connection import get_connection, init_db

from tests.docdb.fixtures import (
    SAMPLE_DOCS,
    SAMPLE_ENTITIES,
    SAMPLE_TAGS,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "docdb.sqlite"
    init_db(path)
    return path


@pytest.fixture
def conn(db_path: Path):
    c = get_connection(db_path)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def populated_db(db_path: Path, fake_llm: FakeLLM):
    """Connection over a DB pre-populated with SAMPLE_DOCS/ENTITIES/TAGS/TODOS.

    Embeddings are derived from each document's title via FakeLLM, so the
    cosine ordering is deterministic and the same across test runs.
    """
    c = get_connection(db_path)
    store = DocumentStore(c)
    titles = [d.title or d.id for d in SAMPLE_DOCS]
    embeddings = fake_llm.embed(titles)
    for doc, emb in zip(SAMPLE_DOCS, embeddings):
        store.upsert_document(doc, embedding=emb)
    for ent in SAMPLE_ENTITIES:
        store.upsert_entity(ent)
    for tag in SAMPLE_TAGS:
        store.upsert_tag(tag)
    # Link the meeting doc to the 田中 entity and the python tag.
    store.link_document_entity(SAMPLE_DOCS[1].id, SAMPLE_ENTITIES[0].id)
    store.link_document_tag(SAMPLE_DOCS[2].id, SAMPLE_TAGS[1].id)
    try:
        yield c
    finally:
        c.close()
