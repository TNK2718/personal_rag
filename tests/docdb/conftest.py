from __future__ import annotations

from pathlib import Path

import pytest

from docdb.schema.connection import get_connection, init_db


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
