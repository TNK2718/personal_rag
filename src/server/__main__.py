"""Run the dev server: ``uv run python -m server``."""

from __future__ import annotations

import os

from server.app import create_app


def main() -> None:
    app = create_app()
    host = os.environ.get("DOCDB_HOST", "127.0.0.1")
    port = int(os.environ.get("DOCDB_PORT", "5000"))
    debug = os.environ.get("DOCDB_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
