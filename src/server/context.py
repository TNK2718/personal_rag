"""Per-request resource accessors.

Kept separate from ``server.app`` to avoid the circular import that
otherwise arises between the app factory and the route blueprints.
"""

from __future__ import annotations

import sqlite3

from flask import current_app, g

from docdb.config import Settings
from docdb.llm.base import LLMProtocol
from docdb.schema.connection import get_connection


def get_conn() -> sqlite3.Connection:
    if "docdb_conn" not in g:
        settings: Settings = current_app.config["DOCDB_SETTINGS"]
        g.docdb_conn = get_connection(settings.db_path)
    return g.docdb_conn


def get_llm() -> LLMProtocol:
    if "docdb_llm" not in g:
        settings: Settings = current_app.config["DOCDB_SETTINGS"]
        factory = current_app.config["DOCDB_LLM_FACTORY"]
        g.docdb_llm = factory(settings)
    return g.docdb_llm
