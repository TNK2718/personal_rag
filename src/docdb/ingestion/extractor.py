"""LLM-driven metadata extraction.

Takes a ``ParsedDocument`` and asks an ``LLMProtocol`` to fill an
``ExtractionResult``. The schema lives in ``docdb.models`` and is what
instructor will request from the underlying model.

The extractor is intentionally thin:
    * one LLM call per document (a single document = one ingestion unit)
    * input truncated to ``max_input_chars`` so prompts stay bounded
    * recovery: on any LLM error, return an empty ``ExtractionResult``
      together with the error message in ``last_error`` so the pipeline
      can still write the raw document without losing the source

That last point matters: if the LLM is unavailable, the ingestion
pipeline degrades to "raw text + embedding only" rather than failing
the whole ingest.
"""

from __future__ import annotations

from dataclasses import dataclass

from docdb.ingestion.parser import ParsedDocument
from docdb.llm.base import LLMProtocol
from docdb.llm.prompts import build_extraction_user_prompt
from docdb.models import ExtractionResult


@dataclass
class ExtractionOutcome:
    result: ExtractionResult
    prompt: str
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class Extractor:
    def __init__(
        self,
        llm: LLMProtocol,
        *,
        max_input_chars: int = 8000,
    ) -> None:
        self.llm = llm
        self.max_input_chars = max_input_chars

    def extract(self, parsed: ParsedDocument) -> ExtractionOutcome:
        prompt = build_extraction_user_prompt(
            parsed, max_body_chars=self.max_input_chars
        )
        try:
            result = self.llm.extract(prompt, ExtractionResult)
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            return ExtractionOutcome(
                result=ExtractionResult(
                    title=parsed.title or "",
                    summary="",
                ),
                prompt=prompt,
                error=f"{type(exc).__name__}: {exc}",
            )

        # Fill blanks from the parsed document so we never lose the
        # original title when the LLM omits it.
        if not result.title and parsed.title:
            result.title = parsed.title
        return ExtractionOutcome(result=result, prompt=prompt)
