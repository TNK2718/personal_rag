"""Ingestion pipeline scaffolding.

Phase 1 added DocumentStore (the writer). Phase 2 layers parsing,
LLM-based extraction, normalisation, and an orchestrator on top.
"""

from docdb.ingestion.parser import Parser, ParsedDocument, Section
from docdb.ingestion.store import DocumentStore

__all__ = ["DocumentStore", "Parser", "ParsedDocument", "Section"]
