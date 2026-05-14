from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, current_app, jsonify, request

from docdb.agent.loop import SearchAgent
from docdb.agent.toolbox import Toolbox
from docdb.config import Settings

from server.context import get_conn, get_llm

bp = Blueprint("ask", __name__, url_prefix="/api")


@bp.post("/ask")
def ask():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    settings: Settings = current_app.config["DOCDB_SETTINGS"]
    try:
        max_iters = max(1, min(int(payload.get("max_iters", settings.agent_max_iters)), 20))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid max_iters"}), 400

    conn = get_conn()
    llm = get_llm()
    toolbox = Toolbox(conn, llm, max_sql_limit=settings.sql_max_limit)
    agent = SearchAgent(toolbox=toolbox, llm=llm, max_iters=max_iters)
    result = agent.run(question)

    return jsonify(
        {
            "question": result.question,
            "answer": result.answer,
            "citations": [c.model_dump() for c in result.citations],
            "trace": [asdict(t) for t in result.trace],
            "iterations": result.iterations,
            "exhausted": result.exhausted,
            "error": result.error,
        }
    )
