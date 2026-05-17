"""Route registration."""

from __future__ import annotations

from flask import Flask

from server.routes import (
    ask,
    documents,
    entities,
    health,
    ingest,
    relations,
    search,
    stats,
    types,
)


def register_routes(app: Flask) -> None:
    app.register_blueprint(health.bp)
    app.register_blueprint(stats.bp)
    app.register_blueprint(documents.bp)
    app.register_blueprint(entities.bp)
    app.register_blueprint(relations.bp)
    app.register_blueprint(relations.edges_bp)
    app.register_blueprint(types.bp)
    app.register_blueprint(search.bp)
    app.register_blueprint(ask.bp)
    app.register_blueprint(ingest.bp)
