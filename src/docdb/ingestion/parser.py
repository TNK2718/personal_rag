"""Source-file parsing for the ingestion pipeline.

This module is pure: no LLM, no DB, no network. Given a file (or raw
text + source hints) it produces a ``ParsedDocument`` — the input that
the rest of the pipeline (extractor → normaliser → store) consumes.

Currently supported:
    * Markdown (with optional YAML-ish frontmatter)
    * Plain text

Other formats (PDF, DOCX, …) are reserved for the optional
``[ingestion]`` extra and live behind separate adapters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from docdb.models import (
    ExtractedTodo,
    SourceType,
    content_hash_for,
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Section:
    header: str
    level: int  # 1..6
    body: str


@dataclass
class ParsedDocument:
    source_path: str
    source_type: SourceType
    raw_text: str
    content_hash: str
    title: str | None = None
    frontmatter: dict[str, str] = field(default_factory=dict)
    sections: list[Section] = field(default_factory=list)

    @property
    def body_without_frontmatter(self) -> str:
        """Convenience accessor used by the extractor."""
        return self.raw_text


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Regex TODO fallback. Each pattern's first capture group is the TODO body.
# Order matters: the first match wins per line.
_TODO_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^\s*[-*]\s+\[ \]\s+(.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*[-*]\s+\[x\]\s+(.+?)\s*$", re.IGNORECASE),  # marked done
    re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\s*[:：]?\s*(.+?)\s*$", re.IGNORECASE),
)
_DONE_PATTERN = re.compile(r"^\s*[-*]\s+\[x\]\s+", re.IGNORECASE)

_HIGH_PRIORITY = ("urgent", "asap", "急", "緊急", "至急")
_LOW_PRIORITY = ("later", "後で", "将来", "いつか")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
class Parser:
    """Stateless parsing entry point.

    Methods are pure and side-effect-free. The parser is a class rather
    than free functions so that callers can substitute a different
    parser in future (e.g. for org-mode) without changing the pipeline.
    """

    # -- Top-level dispatch ------------------------------------------------
    def parse_file(self, path: Path | str) -> ParsedDocument:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        source_type = _source_type_for(path)
        if source_type == "md":
            return self.parse_markdown(text, source_path=str(path))
        return self.parse_text(text, source_path=str(path), source_type=source_type)

    # -- Markdown ----------------------------------------------------------
    def parse_markdown(self, text: str, *, source_path: str) -> ParsedDocument:
        frontmatter, body = _split_frontmatter(text)
        sections = list(_split_sections(body))
        title = _infer_title(frontmatter, sections, source_path)
        return ParsedDocument(
            source_path=source_path,
            source_type="md",
            raw_text=text,
            content_hash=content_hash_for(text),
            title=title,
            frontmatter=frontmatter,
            sections=sections,
        )

    # -- Plain text --------------------------------------------------------
    def parse_text(
        self,
        text: str,
        *,
        source_path: str,
        source_type: SourceType = "txt",
    ) -> ParsedDocument:
        title = _first_nonblank_line(text) or Path(source_path).stem
        return ParsedDocument(
            source_path=source_path,
            source_type=source_type,
            raw_text=text,
            content_hash=content_hash_for(text),
            title=title,
            frontmatter={},
            sections=[Section(header=title, level=1, body=text)] if text.strip() else [],
        )

    # -- Regex TODO fallback ----------------------------------------------
    def extract_todos_regex(self, text: str) -> list[ExtractedTodo]:
        """Best-effort TODO extraction without an LLM.

        Used by the offline mode (``--no-llm``) and as a sanity check
        against LLM hallucinations. Completed checkbox items are
        skipped because the new pipeline records pending TODOs only.
        """
        out: list[ExtractedTodo] = []
        for line in text.splitlines():
            if _DONE_PATTERN.match(line):
                continue
            for pat in _TODO_PATTERNS:
                match = pat.search(line)
                if not match:
                    continue
                content = match.group(1).strip()
                if not content or len(content) < 3:
                    break
                out.append(
                    ExtractedTodo(
                        content=content,
                        priority=_infer_priority(content),
                    )
                )
                break
        return _dedup_preserving_order(out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _source_type_for(path: Path) -> SourceType:
    suffix = path.suffix.lower()
    mapping: dict[str, SourceType] = {
        ".md": "md",
        ".markdown": "md",
        ".txt": "txt",
        ".pdf": "pdf",
        ".docx": "docx",
        ".pptx": "pptx",
        ".xlsx": "xlsx",
        ".html": "html",
        ".htm": "html",
    }
    return mapping.get(suffix, "txt")


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end():]
    fm: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm, body


def _split_sections(body: str) -> Iterable[Section]:
    """Split the body on Markdown headers, yielding ``Section`` rows.

    Lines preceding the first header (preamble) are emitted as a
    level-0 section named ``"__preamble__"`` so callers can still see
    them without losing their position.
    """
    lines = body.splitlines()
    current_header: str | None = None
    current_level = 0
    current_body: list[str] = []

    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            if current_header is not None or current_body:
                yield Section(
                    header=current_header or "__preamble__",
                    level=current_level,
                    body="\n".join(current_body).strip(),
                )
            current_header = m.group(2).strip()
            current_level = len(m.group(1))
            current_body = []
        else:
            current_body.append(line)

    if current_header is not None or current_body:
        yield Section(
            header=current_header or "__preamble__",
            level=current_level,
            body="\n".join(current_body).strip(),
        )


def _infer_title(
    frontmatter: dict[str, str],
    sections: list[Section],
    source_path: str,
) -> str | None:
    if "title" in frontmatter and frontmatter["title"]:
        return frontmatter["title"]
    for s in sections:
        if s.level == 1 and s.header != "__preamble__":
            return s.header
    for s in sections:
        if s.header != "__preamble__":
            return s.header
    return Path(source_path).stem or None


def _first_nonblank_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _infer_priority(content: str) -> str:
    lower = content.lower()
    if any(word in lower for word in _HIGH_PRIORITY):
        return "high"
    if any(word in lower for word in _LOW_PRIORITY):
        return "low"
    return "medium"


def _dedup_preserving_order(items: list[ExtractedTodo]) -> list[ExtractedTodo]:
    seen: set[str] = set()
    out: list[ExtractedTodo] = []
    for it in items:
        key = it.content.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
