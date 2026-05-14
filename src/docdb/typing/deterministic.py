"""Per-entity-type "deterministic extractors" — pure-text rules.

The runtime registry now drives LLM extraction, but some entity types
have shapes that are also recoverable by deterministic regex (e.g.
Markdown ``- [ ]`` checkboxes for the seed ``task`` type). These
extractors run before/after the LLM call and let an offline ingest, or
the LLM-shy parts of a partly-LLM-driven ingest, still produce useful
rows.

How types opt in
----------------

For now, an entity type opts in by name: this module exposes a
``DETERMINISTIC_EXTRACTORS`` mapping keyed by ``entity_types.slug``. The
seed ``task`` type is registered out of the box. Stage 4 may add an
explicit ``deterministic_extractor`` column / FieldSpec attribute so
user-defined types can plug in as well.

Each extractor is a callable ``(text: str) -> list[dict]`` returning
LLM-shaped entity dicts (``{"type": slug, "name": ..., "fields": ...}``).
The pipeline merges these into the LLM output before normalisation, so
the normaliser's dedup logic catches duplicates without special-casing.
"""

from __future__ import annotations

import re
from typing import Callable


_TODO_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^\s*[-*]\s+\[ \]\s+(.+?)\s*$", re.IGNORECASE),
    re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\s*[:：]?\s*(.+?)\s*$", re.IGNORECASE),
)
_DONE_PATTERN = re.compile(r"^\s*[-*]\s+\[x\]\s+", re.IGNORECASE)

_HIGH_PRIORITY = ("urgent", "asap", "急", "緊急", "至急")
_LOW_PRIORITY = ("later", "後で", "将来", "いつか")

_MIN_CONTENT_LEN = 3


def task_checkbox(text: str) -> list[dict]:
    """Extract pending ``- [ ]`` checkbox items and TODO/FIXME-marked lines.

    Returns LLM-shaped entity dicts targeting the seed ``task`` type:
    ``{"type": "task", "name": <body>, "fields": {"status": "pending",
    "priority": <high|medium|low>}}``.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if _DONE_PATTERN.match(line):
            continue
        for pat in _TODO_PATTERNS:
            match = pat.search(line)
            if not match:
                continue
            content = match.group(1).strip()
            if len(content) < _MIN_CONTENT_LEN:
                break
            key = content.lower()
            if key in seen:
                break
            seen.add(key)
            out.append(
                {
                    "type": "task",
                    "name": content,
                    "aliases": [],
                    "fields": {
                        "status": "pending",
                        "priority": _infer_priority(content),
                    },
                }
            )
            break
    return out


def _infer_priority(content: str) -> str:
    lower = content.lower()
    if any(word in lower for word in _HIGH_PRIORITY):
        return "high"
    if any(word in lower for word in _LOW_PRIORITY):
        return "low"
    return "medium"


DETERMINISTIC_EXTRACTORS: dict[str, Callable[[str], list[dict]]] = {
    "task": task_checkbox,
}


def run_for_types(text: str, type_slugs: list[str]) -> list[dict]:
    """Run every deterministic extractor whose slug is registered.

    Called from the ingestion pipeline once per document so the union of
    LLM-emitted and deterministic entities flows into normalisation.
    """
    out: list[dict] = []
    for slug in type_slugs:
        extractor = DETERMINISTIC_EXTRACTORS.get(slug)
        if extractor is None:
            continue
        out.extend(extractor(text))
    return out
