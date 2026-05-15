from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from docdb.config import Settings
from docdb.ingestion import DocumentStore, IngestionPipeline

from server.context import get_conn, get_llm

bp = Blueprint("ingest", __name__, url_prefix="/api")


@bp.post("/ingest")
def ingest_endpoint():
    payload = request.get_json(silent=True) or {}
    raw_path = payload.get("path")
    glob_pattern = payload.get("glob") or "**/*.md"

    settings: Settings = current_app.config["DOCDB_SETTINGS"]
    if raw_path:
        path = Path(raw_path)
    else:
        path = settings.data_dir

    if not path.exists():
        return jsonify({"error": f"path does not exist: {path}"}), 404

    llm = get_llm()
    conn = get_conn()
    pipeline = IngestionPipeline(
        store=DocumentStore(conn),
        llm=llm,
        entity_dedup_enabled=settings.entity_dedup_enabled,
        entity_dedup_distance=settings.entity_dedup_distance,
    )

    if path.is_file():
        reports = [pipeline.ingest_file(path)]
    else:
        reports = list(pipeline.ingest_directory(path, glob=glob_pattern))

    summary: dict[str, int] = {"created": 0, "updated": 0, "skipped": 0, "error": 0}
    for r in reports:
        summary[r.status] = summary.get(r.status, 0) + 1

    return jsonify(
        {
            "path": str(path),
            "glob": glob_pattern if path.is_dir() else None,
            "summary": summary,
            "reports": [asdict(r) for r in reports],
        }
    )
