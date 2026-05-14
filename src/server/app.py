"""Flask app factory."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

from flask import Flask, g, jsonify, send_from_directory
from flask_cors import CORS

from docdb.config import Settings, get_settings
from docdb.llm.base import LLMProtocol
from docdb.llm.client import LLM
from docdb.schema.connection import init_db


LLMFactory = Callable[[Settings], LLMProtocol]


def create_app(
    *,
    settings: Settings | None = None,
    llm_factory: LLMFactory | None = None,
    frontend_dist: Path | None = None,
) -> Flask:
    """Build a Flask app bound to the given Settings.

    ``llm_factory`` lets tests inject a ``FakeLLM`` without monkey-patching.
    ``frontend_dist`` enables SPA serving when the React build output exists.
    """
    settings = settings or get_settings()
    llm_factory = llm_factory or (lambda s: LLM(s))

    if frontend_dist is None:
        candidate = Path(__file__).resolve().parents[1] / "frontend" / "dist"
        if candidate.is_dir():
            frontend_dist = candidate

    static_folder = str(frontend_dist) if frontend_dist else None
    app = Flask(
        __name__,
        static_folder=static_folder,
        static_url_path="" if static_folder else None,
    )
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    app.config["DOCDB_SETTINGS"] = settings
    app.config["DOCDB_LLM_FACTORY"] = llm_factory

    init_db(settings.db_path)

    @app.teardown_appcontext
    def _close_conn(_exc: BaseException | None) -> None:
        conn: sqlite3.Connection | None = g.pop("docdb_conn", None)
        if conn is not None:
            conn.close()

    @app.errorhandler(404)
    def _not_found(err):  # noqa: ANN001
        # API routes return JSON; static/SPA fallback handled below.
        from flask import request

        if request.path.startswith("/api/"):
            return jsonify({"error": "not found"}), 404
        if frontend_dist is not None:
            index = frontend_dist / "index.html"
            if index.is_file():
                return send_from_directory(frontend_dist, "index.html")
        return jsonify({"error": "not found"}), 404

    from server.routes import register_routes  # local import avoids cycle

    register_routes(app)

    if frontend_dist is not None:
        @app.route("/")
        def _root():  # type: ignore[no-redef]
            return send_from_directory(frontend_dist, "index.html")

    return app
