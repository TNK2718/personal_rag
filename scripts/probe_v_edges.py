"""One-shot probe: does the LLM produce `v_edges` SQL for graph questions?

Runs a small set of natural-language questions through `run_text2sql`,
prints the validated SQL and rows, and tallies how often the view shows
up. Requires Ollama with the configured agent model.
"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "src")

import docdb.ingestion  # noqa: F401  (registers extractor)
from docdb.config import get_settings
from docdb.llm.client import LLM
from docdb.schema.connection import get_connection
from docdb.search.text2sql import run_text2sql


QUESTIONS = [
    # Q1-Q3: phrasing that aligns with the extracted (and sometimes
    # mislabelled) edges actually in DB — used to gauge whether the LLM
    # picks v_edges AND produces executable SQL.
    "ACMEはどこに所属していますか?",                 # belongs_to(ACME → 東京都港区)
    "田中太郎は誰と participated_in 関係にありますか?",  # participated_in(田中→山田)
    "person タイプの src を持つ edge を全部出して",        # explicit v_edges shape
]


def main() -> int:
    settings = get_settings()
    llm = LLM(settings)
    conn = get_connection(settings.db_path)
    try:
        hits = 0
        for q in QUESTIONS:
            print("=" * 70)
            print("Q:", q)
            t0 = time.perf_counter()
            r = run_text2sql(conn, q, llm)
            elapsed = time.perf_counter() - t0
            sql = r.validated_sql or r.sql or "<none>"
            print(f"SQL ({elapsed:.1f}s):")
            print("  " + sql.replace("\n", "\n  "))
            uses_v_edges = "v_edges" in sql
            if uses_v_edges:
                hits += 1
            print(f"uses v_edges: {uses_v_edges}")
            if r.error:
                print("error:", r.error)
            print("rows:", r.rows[:5])
        print("=" * 70)
        print(f"v_edges hits: {hits}/{len(QUESTIONS)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
