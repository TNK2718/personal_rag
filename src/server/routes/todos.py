from __future__ import annotations

from flask import Blueprint, jsonify, request

from docdb.models import now_iso

from server.context import get_conn

bp = Blueprint("todos", __name__, url_prefix="/api/todos")


_ALLOWED_STATUS = {"pending", "in_progress", "completed", "cancelled"}
_ALLOWED_PRIORITY = {"high", "medium", "low"}


@bp.get("")
def list_todos():
    conn = get_conn()
    status = request.args.get("status") or None
    priority = request.args.get("priority") or None
    due_before = request.args.get("due_before") or None
    source_document_id = request.args.get("source_document_id") or None
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 500))
    except ValueError:
        return jsonify({"error": "invalid limit"}), 400

    if status is not None and status not in _ALLOWED_STATUS:
        return jsonify({"error": f"invalid status: {status}"}), 400
    if priority is not None and priority not in _ALLOWED_PRIORITY:
        return jsonify({"error": f"invalid priority: {priority}"}), 400

    sql = (
        "SELECT t.*, d.title AS source_title, d.source_path AS source_path "
        "FROM todos AS t "
        "LEFT JOIN documents AS d ON d.id = t.source_document_id "
        "WHERE 1=1"
    )
    params: list = []
    if status is not None:
        sql += " AND t.status = ?"
        params.append(status)
    if priority is not None:
        sql += " AND t.priority = ?"
        params.append(priority)
    if due_before is not None:
        sql += " AND (t.due_date IS NOT NULL AND t.due_date <= ?)"
        params.append(due_before)
    if source_document_id is not None:
        sql += " AND t.source_document_id = ?"
        params.append(source_document_id)
    sql += (
        " ORDER BY t.status, COALESCE(t.due_date, '9999-99-99') ASC, "
        " CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
        " t.created_at DESC LIMIT ?"
    )
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.patch("/<todo_id>")
def update_todo(todo_id: str):
    conn = get_conn()
    payload = request.get_json(silent=True) or {}

    fields: list[str] = []
    params: list = []

    if "status" in payload:
        if payload["status"] not in _ALLOWED_STATUS:
            return jsonify({"error": f"invalid status: {payload['status']}"}), 400
        fields.append("status = ?")
        params.append(payload["status"])
    if "priority" in payload:
        if payload["priority"] not in _ALLOWED_PRIORITY:
            return jsonify({"error": f"invalid priority: {payload['priority']}"}), 400
        fields.append("priority = ?")
        params.append(payload["priority"])
    if "due_date" in payload:
        due = payload["due_date"]
        if due is not None and not isinstance(due, str):
            return jsonify({"error": "due_date must be a string or null"}), 400
        fields.append("due_date = ?")
        params.append(due)
    if "content" in payload:
        content = (payload["content"] or "").strip()
        if not content:
            return jsonify({"error": "content cannot be empty"}), 400
        fields.append("content = ?")
        params.append(content)

    if not fields:
        return jsonify({"error": "no updatable fields supplied"}), 400

    fields.append("updated_at = ?")
    params.append(now_iso())
    params.append(todo_id)

    with conn:
        cur = conn.execute(
            f"UPDATE todos SET {', '.join(fields)} WHERE id = ?", params
        )
        if cur.rowcount == 0:
            return jsonify({"error": "todo not found"}), 404
        row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return jsonify(dict(row))
