from __future__ import annotations

from flask import Blueprint, jsonify

bp = Blueprint("health", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})
