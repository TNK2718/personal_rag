"""Shared sample-data builders for DocDB tests.

The five sample documents below are intentionally small and mix
Japanese / English content. They give the search tests enough surface
to discriminate by full-text match, doc_type, date range, and vector
similarity without depending on a real embedding model.
"""

from __future__ import annotations

from docdb.models import (
    Document,
    Entity,
    Tag,
    content_hash_for,
    document_id_for,
    entity_id_for,
    tag_id_for,
)


def _doc(
    body: str,
    *,
    title: str,
    doc_type: str,
    created_at: str,
    source_path: str,
    summary: str = "",
) -> Document:
    h = content_hash_for(body)
    return Document(
        id=document_id_for(h),
        source_type="md",
        content_hash=h,
        source_path=source_path,
        title=title,
        doc_type=doc_type,
        created_at=created_at,
        summary=summary or body[:120],
        raw_text=body,
        language="ja",
    )


SAMPLE_DOCS: list[Document] = [
    _doc(
        "本契約の解約条項について説明する。解約は30日前の通知が必要。",
        title="契約解約条項メモ",
        doc_type="memo",
        created_at="2026-04-01",
        source_path="memo/2026-04-01-cancel.md",
    ),
    _doc(
        "プロジェクトAの議事録。参加者は田中、鈴木。次回までにTODO: 設計レビュー実施。",
        title="プロジェクトA定例",
        doc_type="meeting",
        created_at="2026-04-15",
        source_path="meeting/2026-04-15-projectA.md",
    ),
    _doc(
        "今日の日記。新しい技術書を読み始めた。Python の型ヒントについて学んだ。",
        title="技術書を読んだ日",
        doc_type="journal",
        created_at="2026-05-01",
        source_path="journal/2026-05-01.md",
    ),
    _doc(
        "システム仕様書: docdb の検索エージェントは3層構成 (Direct API / Text2SQL / Agentic)。",
        title="DocDB仕様",
        doc_type="spec",
        created_at="2026-05-10",
        source_path="spec/docdb-search.md",
    ),
    _doc(
        "古いメモ。2025年の年初に書いた目標リスト。健康と読書を増やす。",
        title="2025年目標",
        doc_type="memo",
        created_at="2025-01-05",
        source_path="memo/2025-01-05-goals.md",
    ),
]


# Property-graph entities — the seed types ``person`` / ``org`` / ``task``
# are loaded by ``init_db`` from ``seed.sql`` and referenced here by slug.
SAMPLE_ENTITIES: list[Entity] = [
    Entity(
        id=entity_id_for("person", "田中"),
        type_slug="person",
        canonical_name="田中",
        aliases=["田中さん"],
    ),
    Entity(
        id=entity_id_for("org", "プロジェクトA"),
        type_slug="org",
        canonical_name="プロジェクトA",
    ),
    Entity(
        id=entity_id_for("task", "設計レビュー実施"),
        type_slug="task",
        canonical_name="設計レビュー実施",
        fields={"status": "pending", "priority": "high"},
    ),
]


SAMPLE_TAGS: list[Tag] = [
    Tag(id=tag_id_for("契約"), canonical_name="契約", category="business"),
    Tag(id=tag_id_for("python"), canonical_name="python", category="tech"),
]
