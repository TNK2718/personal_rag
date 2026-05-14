"""Ingestion pipeline scaffolding.

In Phase 1 only the storage layer (``DocumentStore``) lives here. The
parse/extract/normalise stages land in Phase 2.
"""

from docdb.ingestion.store import DocumentStore

__all__ = ["DocumentStore"]
