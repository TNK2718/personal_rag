"""Ingestion pipeline scaffolding.

Phase 1 added DocumentStore (the writer). Phase 2 layers parsing,
LLM-based extraction, normalisation, and an orchestrator on top.
"""

from docdb.ingestion.extractor import Extractor, ExtractionOutcome
from docdb.ingestion.normalizer import (
    DocumentEntityLink,
    DocumentTagLink,
    NormalizedExtraction,
    canonicalize_entity_name,
    canonicalize_tag_name,
    extract_due_date,
    normalize_extraction,
)
from docdb.ingestion.parser import Parser, ParsedDocument, Section
from docdb.ingestion.pipeline import IngestionPipeline, IngestionReport
from docdb.ingestion.store import DocumentStore

__all__ = [
    "DocumentStore",
    "DocumentEntityLink",
    "DocumentTagLink",
    "Extractor",
    "ExtractionOutcome",
    "IngestionPipeline",
    "IngestionReport",
    "NormalizedExtraction",
    "Parser",
    "ParsedDocument",
    "Section",
    "canonicalize_entity_name",
    "canonicalize_tag_name",
    "extract_due_date",
    "normalize_extraction",
]
