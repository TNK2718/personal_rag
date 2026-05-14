"""Tool-calling agent loop.

The agent treats the LLM as a planner and the Toolbox as the only way
to touch the DB. Loop semantics, kept deliberately small:

1. Send messages + tool schemas to ``LLM.chat_with_tools``.
2. If the response contains tool calls, dispatch each through the
   toolbox, append the assistant message + tool result messages, and
   loop.
3. If the response is plain text (no tool calls), that is the final
   answer.
4. Stop after ``max_iters`` iterations and mark ``exhausted=True``.

Two things the loop owns beyond plain dispatch:

* **Citation collection** — every tool result is scanned for
  ``document_id`` keys (nested or flat). Those IDs are unique-ified
  and resolved via ``get_document`` so the caller gets a list of
  ``Citation`` objects regardless of whether the LLM remembered to
  cite them in prose.
* **Trace** — one ``AgentTrace`` record per tool call, with the
  iteration index, arguments, and a result preview, so the CLI / UI
  can show what the agent did.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from docdb.agent.toolbox import Toolbox
from docdb.llm.base import LLMProtocol
from docdb.llm.prompts import AGENT_SYSTEM
from docdb.models import Citation
from docdb.search.direct import get_document


# ---------------------------------------------------------------------------
# Output records
# ---------------------------------------------------------------------------
@dataclass
class AgentTrace:
    iteration: int
    tool: str
    arguments: dict[str, Any]
    result_preview: str = ""
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class AgentResult:
    question: str
    answer: str = ""
    citations: list[Citation] = field(default_factory=list)
    trace: list[AgentTrace] = field(default_factory=list)
    iterations: int = 0
    exhausted: bool = False
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
@dataclass
class SearchAgent:
    toolbox: Toolbox
    llm: LLMProtocol
    max_iters: int = 8
    system_prompt: str = AGENT_SYSTEM

    def run(self, question: str) -> AgentResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": question},
        ]
        trace: list[AgentTrace] = []
        cited_doc_ids: list[str] = []  # ordered, deduplicated
        seen_doc_ids: set[str] = set()

        for iteration in range(1, self.max_iters + 1):
            try:
                response = self.llm.chat_with_tools(
                    messages, tools=self.toolbox.openai_tools()
                )
            except Exception as exc:  # noqa: BLE001
                return AgentResult(
                    question=question,
                    iterations=iteration - 1,
                    trace=trace,
                    error=f"llm error: {type(exc).__name__}: {exc}",
                )

            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []

            if not tool_calls:
                return AgentResult(
                    question=question,
                    answer=(message.content or "").strip(),
                    citations=self._resolve_citations(cited_doc_ids),
                    trace=trace,
                    iterations=iteration,
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in tool_calls
                    ],
                }
            )

            for call in tool_calls:
                inv = self.toolbox.invoke(call.function.name, call.function.arguments)
                preview = (
                    inv.result_json
                    if inv.succeeded and inv.result_json is not None
                    else json.dumps({"error": inv.error}, ensure_ascii=False)
                )
                if len(preview) > 500:
                    preview = preview[:500] + "…"

                trace.append(
                    AgentTrace(
                        iteration=iteration,
                        tool=call.function.name,
                        arguments=inv.arguments,
                        result_preview=preview,
                        error=inv.error,
                    )
                )

                for doc_id in _extract_document_ids(inv.result):
                    if doc_id and doc_id not in seen_doc_ids:
                        seen_doc_ids.add(doc_id)
                        cited_doc_ids.append(doc_id)

                tool_content = (
                    inv.result_json
                    if inv.succeeded
                    else json.dumps({"error": inv.error}, ensure_ascii=False)
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.function.name,
                        "content": tool_content,
                    }
                )

        return AgentResult(
            question=question,
            citations=self._resolve_citations(cited_doc_ids),
            trace=trace,
            iterations=self.max_iters,
            exhausted=True,
        )

    # ------------------------------------------------------------------
    def _resolve_citations(self, doc_ids: list[str]) -> list[Citation]:
        out: list[Citation] = []
        for doc_id in doc_ids:
            doc = get_document(self.toolbox.conn, doc_id)
            if doc is None:
                continue
            out.append(
                Citation(
                    document_id=doc.id,
                    title=doc.title,
                    snippet=(doc.summary or doc.raw_text or "")[:160] or None,
                    source_path=doc.source_path,
                    doc_type=doc.doc_type,
                )
            )
        return out


# ---------------------------------------------------------------------------
# document_id harvesting
# ---------------------------------------------------------------------------
def _extract_document_ids(value: Any) -> Iterable[str]:
    """Walk ``value`` recursively and yield every ``document_id``-shaped value.

    Also recognises the ``"id"`` key on documents-shaped dicts that we
    return from ``get_document``. We treat any string starting with
    ``doc-`` as a document id even when the surrounding key is just
    ``"id"``.
    """
    if isinstance(value, str):
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "document_id" and isinstance(v, str):
                yield v
            elif k == "id" and isinstance(v, str) and v.startswith("doc-"):
                yield v
            else:
                yield from _extract_document_ids(v)
        return
    if isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _extract_document_ids(v)
