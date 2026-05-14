from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path
from typing import Iterator
from contextlib import contextmanager

import sqlite_vec


_SCHEMA_RESOURCE = ("docdb.schema", "schema.sql")
_SEED_RESOURCE = ("docdb.schema", "seed.sql")


def _load_extensions(conn: sqlite3.Connection) -> None:
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def _apply_pragmas(conn: sqlite3.Connection, *, readonly: bool) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")


def get_connection(db_path: Path | str, *, readonly: bool = False) -> sqlite3.Connection:
    """Open a SQLite connection with sqlite-vec loaded and sensible PRAGMAs.

    The read-only flag opens the file via URI mode=ro and disables the WAL
    setup that would otherwise touch the database file.
    """
    db_path = Path(db_path)
    if readonly:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _load_extensions(conn)
    _apply_pragmas(conn, readonly=readonly)
    return conn


def _read_resource(resource: tuple[str, str]) -> str:
    package, name = resource
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")


def _read_schema_sql() -> str:
    return _read_resource(_SCHEMA_RESOURCE)


def _read_seed_sql() -> str:
    return _read_resource(_SEED_RESOURCE)


def init_db(db_path: Path | str) -> None:
    """Create the database file (if missing) and apply schema + seeds idempotently.

    schema.sql defines the table layout; seed.sql ships built-in type
    definitions (person/org/place/task/...). Both use INSERT OR IGNORE
    so re-running is safe and never clobbers user edits.
    """
    with get_connection(db_path) as conn:
        conn.executescript(_read_schema_sql())
        conn.executescript(_read_seed_sql())
        conn.commit()


@contextmanager
def connection(db_path: Path | str, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path, readonly=readonly)
    try:
        yield conn
    finally:
        conn.close()
