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
    Relation,
    Tag,
    content_hash_for,
    document_id_for,
    entity_id_for,
    relation_id_for,
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


# Property-graph entities — built-in types (person / org / place / task /
# project / event) are loaded by ``init_db`` from ``seed.sql`` and referenced
# here by slug. Indices 0..2 are kept stable: existing tests reference
# ``SAMPLE_ENTITIES[0]`` (田中) and ``SAMPLE_ENTITIES[1]`` (プロジェクトA)
# by position, so new entities are appended.
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
    Entity(
        id=entity_id_for("person", "山田花子"),
        type_slug="person",
        canonical_name="山田花子",
        aliases=["山田花子さん", "山田"],
    ),
    Entity(
        id=entity_id_for("org", "株式会社サンプル"),
        type_slug="org",
        canonical_name="株式会社サンプル",
        aliases=["サンプル社"],
    ),
    Entity(
        id=entity_id_for("project", "次世代RAG基盤"),
        type_slug="project",
        canonical_name="次世代RAG基盤",
        fields={"status": "active"},
    ),
    Entity(
        id=entity_id_for("place", "東京本社"),
        type_slug="place",
        canonical_name="東京本社",
    ),
    Entity(
        id=entity_id_for("event", "2026年5月定例会"),
        type_slug="event",
        canonical_name="2026年5月定例会",
        fields={"start_at": "2026-05-12T10:00:00"},
    ),
]


def _rel(type_slug: str, src: Entity, tgt: Entity) -> Relation:
    return Relation(
        id=relation_id_for(type_slug, src.id, tgt.id),
        type_slug=type_slug,
        source_entity_id=src.id,
        target_entity_id=tgt.id,
    )


# Property-graph edges exercising the built-in relation types. Used by the
# ``populated_db`` fixture so that text2sql and agent tests can answer
# typical property-graph questions like 「山田花子さんの所属は？」.
SAMPLE_RELATIONS: list[Relation] = [
    # 山田花子 belongs_to 株式会社サンプル
    _rel("belongs_to", SAMPLE_ENTITIES[3], SAMPLE_ENTITIES[4]),
    # 株式会社サンプル located_in 東京本社
    _rel("located_in", SAMPLE_ENTITIES[4], SAMPLE_ENTITIES[6]),
    # 山田花子 member_of 次世代RAG基盤
    _rel("member_of", SAMPLE_ENTITIES[3], SAMPLE_ENTITIES[5]),
    # 山田花子 participated_in 2026年5月定例会
    _rel("participated_in", SAMPLE_ENTITIES[3], SAMPLE_ENTITIES[7]),
    # 設計レビュー実施 assigned_to 田中  (existing entities, exercises assigned_to)
    _rel("assigned_to", SAMPLE_ENTITIES[2], SAMPLE_ENTITIES[0]),
]


SAMPLE_TAGS: list[Tag] = [
    Tag(id=tag_id_for("契約"), canonical_name="契約", category="business"),
    Tag(id=tag_id_for("python"), canonical_name="python", category="tech"),
]
