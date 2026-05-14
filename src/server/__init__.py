"""HTTP API for DocDB.

The server is a thin Flask layer over ``docdb.*``. It is intentionally
state-less: each request opens a SQLite connection via
``docdb.schema.connection.connection`` and closes it on teardown. There is
no shared mutable cache here — everything authoritative lives in SQLite.
"""

from server.app import create_app

__all__ = ["create_app"]
