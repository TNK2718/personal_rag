"""Prompt strings and prompt builders.

Keeping all prompt text in one module makes it easy to A/B test
phrasings, run ``grep`` for vocabulary the LLM is being asked to use,
and audit the system for hidden behavioural instructions.

The instructions are written in Japanese first because the target
corpus (personal memos, meeting notes, journal entries) is primarily
Japanese. English content still flows through correctly — the LLM is
told to keep canonical names in their original script.

Stage 3 makes the extraction system prompt dynamic: every registered
entity type and relation type from the runtime registry is rendered
into the prompt with its label, description, fields_schema summary,
and free-form ``extraction_hint``. The base instructions
(``EXTRACTION_SYSTEM_BASE``) stay constant; what the LLM is allowed to
emit varies per call.
"""

from __future__ import annotations

from docdb.ingestion.parser import ParsedDocument
from docdb.typing.registry import EntityTypeDef, RelationTypeDef


EXTRACTION_PROMPT_MAX_BYTES = 30_000
AGENT_PROMPT_MAX_BYTES = 20_000
TEXT2SQL_PROMPT_MAX_BYTES = 30_000


EXTRACTION_SYSTEM_BASE = (
    "あなたは個人ノートから構造化メタデータを抽出するアシスタントです。\n"
    "次のルールに従い、必要なフィールドだけを正確に埋めてください。\n"
    "1. `doc_type` はメモ=memo / 会議=meeting / 日記=journal / 参考資料=reference / 仕様=spec / その他=other から1つ選ぶ。\n"
    "2. `title` は文書の主題を15字以内で要約。元タイトルがあればそのまま使う。\n"
    "3. `summary` は200字以内の日本語サマリ。冗長な前置きや感想は書かない。\n"
    "4. `language` は本文の主要言語を `ja` / `en` / `mixed` / `other` で表す。\n"
    "5. `tags` は3〜8個の短いカテゴリ語 (1〜2語) を小文字英数字または日本語で。\n"
    "6. 元の文書に存在しない情報を捏造しない。確信が持てないフィールドは空欄/空配列のままにする。"
)

# Kept for backwards-compat with tests that import the symbol directly.
EXTRACTION_SYSTEM = EXTRACTION_SYSTEM_BASE


def build_extraction_system_prompt(
    entity_types: list[EntityTypeDef],
    relation_types: list[RelationTypeDef],
    *,
    max_bytes: int = EXTRACTION_PROMPT_MAX_BYTES,
) -> str:
    """Assemble the full system prompt for the current type registry.

    The structure is: base rules → entity-type catalogue → relation-type
    catalogue → closing rule. Each catalogue entry advertises the slug,
    label, description, field summary, and the user-authored ``extraction_hint``
    so the LLM has both a schema and a usage cue.

    Hard-capped at ``max_bytes`` UTF-8 bytes; when the assembled prompt grows
    past the cap, types are dropped from the END (preserving builtins is the
    caller's responsibility for now — Stage 4 will add an "is_active" knob).
    """
    parts: list[str] = [EXTRACTION_SYSTEM_BASE, ""]

    if entity_types:
        parts.append("# 抽出できる entity 型 (slug : label)")
        for t in entity_types:
            parts.append(_render_entity_type(t))
        parts.append("")

    if relation_types and entity_types:
        # Relations only make sense when at least one entity type exists.
        parts.append("# 抽出できる relation 型 (slug : label)")
        for t in relation_types:
            parts.append(_render_relation_type(t))
        parts.append("")

    if entity_types:
        parts.append(
            "7. entities[] に登場する `type` は上記 entity 型の slug のみ。"
            "未登録の概念は entity として出力しない。"
        )
        if relation_types:
            parts.append(
                "8. relations[] の `source` / `target` は同じドキュメントの entities[] "
                "に出てくる (type, name) を指す。`source` は必須。"
                "`target` が本文から特定できない場合は `null` を入れる "
                "(該当 relation はパイプライン側で除外される)。"
                "endpoints を捏造しない。"
            )

    assembled = "\n".join(parts)
    encoded = assembled.encode("utf-8")
    if len(encoded) <= max_bytes:
        return assembled

    # Truncate by dropping trailing type catalogue entries until we fit.
    return _truncate_to_fit(parts, max_bytes)


def _render_entity_type(t: EntityTypeDef) -> str:
    head = f"- `{t.slug}` : {t.label}"
    if t.description:
        head += f" — {t.description}"
    lines = [head]
    if t.fields:
        for f in t.fields:
            spec = f"    * {f.name} ({f.type}"
            if getattr(f, "required", False):
                spec += ", required"
            options = getattr(f, "options", None)
            if options:
                spec += f", options={list(options)}"
            spec += ")"
            lines.append(spec)
    if t.extraction_hint:
        lines.append(f"    ヒント: {t.extraction_hint}")
    return "\n".join(lines)


def _render_relation_type(t: RelationTypeDef) -> str:
    head = f"- `{t.slug}` : {t.label}"
    endpoints = (
        f" ({t.source_type_slug or 'any'} → {t.target_type_slug or 'any'})"
    )
    head += endpoints
    if t.description:
        head += f" — {t.description}"
    lines = [head]
    if t.fields:
        for f in t.fields:
            spec = f"    * {f.name} ({f.type}"
            if getattr(f, "required", False):
                spec += ", required"
            options = getattr(f, "options", None)
            if options:
                spec += f", options={list(options)}"
            spec += ")"
            lines.append(spec)
    if t.extraction_hint:
        lines.append(f"    ヒント: {t.extraction_hint}")
    return "\n".join(lines)


def _truncate_to_fit(parts: list[str], max_bytes: int) -> str:
    """Drop trailing prompt sections until the encoded length fits."""
    parts = list(parts)
    while parts:
        out = "\n".join(parts + ["[... 型カタログを一部省略 ...]"])
        if len(out.encode("utf-8")) <= max_bytes:
            return out
        parts.pop()
    # Defensive: even the base block doesn't fit — return a clipped string.
    fallback = EXTRACTION_SYSTEM_BASE.encode("utf-8")[: max_bytes - 64]
    return fallback.decode("utf-8", errors="ignore") + "\n[... 省略 ...]"


def build_extraction_user_prompt(
    parsed: ParsedDocument,
    *,
    max_body_chars: int = 8000,
    system_prompt: str | None = None,
) -> str:
    """Render the document into the user-side prompt for extraction.

    Layout:
        <system instructions, registry-aware when system_prompt is supplied>
        <metadata hints from parsing>
        <document body, truncated to max_body_chars>
    """
    hints: list[str] = []
    if parsed.title:
        hints.append(f"既存タイトル候補: {parsed.title}")
    if parsed.source_path:
        hints.append(f"source_path: {parsed.source_path}")
    if parsed.frontmatter:
        kv = ", ".join(f"{k}={v}" for k, v in parsed.frontmatter.items())
        hints.append(f"frontmatter: {kv}")

    body = parsed.raw_text
    truncated = False
    if len(body) > max_body_chars:
        body = body[:max_body_chars]
        truncated = True

    header = system_prompt if system_prompt is not None else EXTRACTION_SYSTEM_BASE
    parts = [header, ""]
    if hints:
        parts.append("# 入力メタ情報")
        parts.extend(hints)
        parts.append("")
    parts.append("# 本文")
    parts.append(body)
    if truncated:
        parts.append(f"\n[... 末尾を {len(parsed.raw_text) - max_body_chars} 字省略 ...]")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Text2SQL
# ---------------------------------------------------------------------------
TEXT2SQL_SYSTEM = (
    "あなたは SQLite データベースに対する読み取り専用 SQL を生成するアシスタントです。\n"
    "次のルールに厳密に従ってください。\n"
    "1. 出力は単一の SELECT 文 (または WITH ... SELECT) のみ。\n"
    "2. INSERT / UPDATE / DELETE / DROP / ALTER / PRAGMA / ATTACH は禁止。\n"
    "3. 許可テーブルは documents / documents_fts / entities / entity_types / "
    "relations / relation_types / tags / document_entities / document_tags / "
    "document_relations / document_relation_mentions のみ。\n"
    "4. 件数が多くなり得るクエリには LIMIT を付ける (既定 50 件以内)。\n"
    "5. 日本語の全文検索は documents_fts MATCH を使う (3 文字以上必須)。\n"
    "6. 不要な列を SELECT しない。少なくとも documents.id, title を含めると後工程が読みやすい。\n"
    "7. 出力 JSON は {sql, reasoning} の 2 フィールドのみ。"
)

DOCDB_SCHEMA_SUMMARY = """\
-- documents(id TEXT PK, source_path, source_uri, source_type, title, doc_type,
--           author, created_at, summary, raw_text, content_hash UNIQUE,
--           language, metadata JSON, created_ts, updated_ts)
--   doc_type ∈ {memo, meeting, journal, reference, spec, other}
--   language ∈ {ja, en, mixed, other}
--   created_at: ISO date string (YYYY-MM-DD); may be NULL.
-- documents_fts(title, summary, raw_text)  -- FTS5, trigram tokenizer
--   usage: WHERE documents_fts MATCH '解約条項'
--   join : JOIN documents d ON d.rowid = documents_fts.rowid
-- entity_types(slug PK, label, fields_schema JSON, extraction_hint, is_builtin)
-- relation_types(slug PK, label, source_type_slug, target_type_slug, fields_schema JSON, ...)
-- entities(id PK, type_slug FK → entity_types.slug, canonical_name, aliases JSON,
--          description, fields JSON, created_ts, updated_ts)
--   filter examples: WHERE type_slug = 'task'
--                    AND json_extract(fields, '$.status') = 'pending'
-- entities_search(entity_id PK FK → entities.id, searchable_text)
--   content table for entities_fts; the store rebuilds it on upsert.
-- entities_fts(searchable_text)  -- FTS5, trigram tokenizer
--   usage: JOIN entities_search es ON es.entity_id = entities.id
--          JOIN entities_fts ON entities_fts.rowid = es.rowid
--          WHERE entities_fts MATCH '<キーワード>'
-- relations(id PK, type_slug FK → relation_types.slug, source_entity_id FK → entities.id,
--           target_entity_id FK → entities.id, fields JSON)
-- tags(id, canonical_name UNIQUE, aliases JSON, category)
-- document_entities(document_id, entity_id, mention_count, contexts JSON)
-- document_tags(document_id, tag_id, confidence, source)
-- document_relations(src_document_id, dst_document_id, relation_type, confidence, evidence)
--   note: doc-to-doc edges, distinct from `relations` (entity-graph edges).
-- document_relation_mentions(document_id, relation_id, contexts JSON)
--   note: provenance of entity-graph relations.
"""


def build_text2sql_user_prompt(
    question: str,
    *,
    entity_types: list[EntityTypeDef] = (),
    relation_types: list[RelationTypeDef] = (),
    max_bytes: int = TEXT2SQL_PROMPT_MAX_BYTES,
) -> str:
    """Assemble the text2sql user prompt, injecting the current type registry.

    Surfacing each type's ``fields_schema`` lets the LLM produce
    ``json_extract(entities.fields, '$.<key>')`` filters with real key names
    instead of guessing — small models otherwise emit broken empty-path
    SQL like ``fields->'$.'`` that SQLite silently evaluates to NULL.

    Hard-capped at ``max_bytes`` UTF-8 bytes; the type catalogue is the
    only section eligible for truncation — the question always survives.
    Mention resolution lives outside this builder: on the retry path
    ``run_text2sql`` rewrites the ``question`` in place to surface
    canonical names; the rewritten string flows in here unchanged.
    """
    catalog_parts: list[str] = [
        TEXT2SQL_SYSTEM,
        "",
        "# スキーマ",
        DOCDB_SCHEMA_SUMMARY,
    ]
    if entity_types:
        catalog_parts.append(
            "# 登録済み entity 型と fields キー (json_extract(fields, '$.<key>') で参照)"
        )
        for t in entity_types:
            catalog_parts.append(_render_entity_type(t))
        catalog_parts.append("")
    if relation_types:
        catalog_parts.append(
            "# 登録済み relation 型と fields キー"
        )
        for t in relation_types:
            catalog_parts.append(_render_relation_type(t))
        catalog_parts.append("")

    question_block = f"# 質問\n{question}\n"
    question_size = len(question_block.encode("utf-8"))
    # +1 for the newline we insert between catalog and question.
    catalog_budget = max(max_bytes - question_size - 1, 200)

    catalog_str = "\n".join(catalog_parts)
    if len(catalog_str.encode("utf-8")) > catalog_budget:
        catalog_str = _truncate_to_fit(catalog_parts, catalog_budget)
    return catalog_str + "\n" + question_block


# ---------------------------------------------------------------------------
# Search agent
# ---------------------------------------------------------------------------
AGENT_SYSTEM_BASE = (
    "あなたは個人 Markdown メモに対する検索エージェントです。\n"
    "提供されたツールのみを使って情報を探し、ユーザーの質問に日本語で簡潔に答えます。\n"
    "\n"
    "この個人ノートは property graph として SQLite に正規化されており、ドキュメント・\n"
    "エンティティ (人物・組織・タスク・場所など、`type_slug` でカテゴリ化) ・リレーションが\n"
    "テーブルとして引ける。**ほぼ全ての構造化問い合わせは SQL で表現できる**ため、\n"
    "デフォルトの経路は `text_to_sql` (LLM が schema 込みで SELECT を生成して実行する)。\n"
    "全文検索や entity の便利関数は、SQL では届きにくい場面の補助として位置づける。\n"
    "\n"
    "進め方:\n"
    "1. **デフォルト: `text_to_sql`**。質問が「件数」「条件指定」「型ベース (タスク・会議など)」\n"
    "   「JOIN (担当者・所属・親子)」「LIKE」「期間絞り込み」など SQL で表現できるなら、\n"
    "   まず `text_to_sql` に質問文をそのまま渡す。schema (テーブル定義 + 全 entity/relation\n"
    "   型の slug とフィールド) は内部で自動付与されるので、事前にスキーマを調べる必要はない。\n"
    "2. SQL では表現しづらい **自由語句の意味検索** (本文中のフレーズ・概念・言い換え)\n"
    "   が必要なときだけ `search_documents` を使う (3 文字以上; 既定で FTS+ベクトル融合、\n"
    "   純粋 FTS にしたいときだけ `hybrid=false`)。本文確認は `get_document`。\n"
    "3. 既に id を持っているなら `get_document` (本文)、`find_similar`\n"
    "   (類似ドキュメントの vec KNN) を直接呼ぶ。\n"
    "4. `text_to_sql` に渡す前にスキーマ (どんな型・フィールド・関係があるか) を\n"
    "   確かめたいときは `describe_schema` を呼ぶ (引数なしで summary、`kind` で絞り込み、\n"
    "   `kind`+`slug` で 1 型のフィールド詳細まで掘れる; 通常は下のカタログで十分)。\n"
    "5. 自分で書きたい SQL があるときだけ `execute_readonly_sql`\n"
    "   (テーブル: documents(id, title, raw_text, summary, doc_type, …)、\n"
    "   entities(id, type_slug, canonical_name, fields JSON, …)、relations(id, type_slug,\n"
    "   source_entity_id, target_entity_id, …)。`body` ではなく `raw_text`)。\n"
    "\n"
    "ルール:\n"
    "- ツール結果に書かれていない情報を捏造しない。資料に存在しなければ「分かりません」と答える。\n"
    "- 回答末尾に出典を `[doc:document_id]` の形式で列挙する。\n"
    "- 不要なツール呼び出しを避ける。十分な情報が揃ったら速やかに最終回答を返す。"
)

# Back-compat: external callers and existing tests import AGENT_SYSTEM directly.
AGENT_SYSTEM = AGENT_SYSTEM_BASE


def build_agent_system_prompt(
    entity_types: list[EntityTypeDef],
    relation_types: list[RelationTypeDef],
    *,
    max_bytes: int = AGENT_PROMPT_MAX_BYTES,
) -> str:
    """Assemble the agent system prompt with the live type catalogue appended.

    The agent only needs slug / label / short description to know which
    ``type_slug`` values to put in ``text_to_sql`` WHERE clauses (and to know
    a relation's endpoint types when planning a JOIN). Field schemas and
    extraction hints (used on the extraction side) are deliberately omitted
    to keep the prompt small at inference time; ``describe_schema`` is the
    drill-down path when the agent needs full ``fields_schema``.

    Hard-capped at ``max_bytes`` UTF-8 bytes; if the assembled prompt grows
    past the cap, trailing catalogue entries are dropped (same approach as
    ``build_extraction_system_prompt``).
    """
    parts: list[str] = [AGENT_SYSTEM_BASE, ""]

    if entity_types:
        parts.append("# 登録済みの entity 型 (slug : label)")
        for t in entity_types:
            parts.append(_render_entity_type_lite(t))
        parts.append("")

    if relation_types and entity_types:
        parts.append("# 登録済みの relation 型 (slug : label, source → target)")
        for t in relation_types:
            parts.append(_render_relation_type_lite(t))
        parts.append("")

    assembled = "\n".join(parts)
    if len(assembled.encode("utf-8")) <= max_bytes:
        return assembled

    return _truncate_to_fit(parts, max_bytes)


def _render_entity_type_lite(t: EntityTypeDef) -> str:
    head = f"- `{t.slug}` : {t.label}"
    if t.description:
        head += f" — {t.description}"
    return head


def _render_relation_type_lite(t: RelationTypeDef) -> str:
    endpoints = f"{t.source_type_slug or 'any'} → {t.target_type_slug or 'any'}"
    head = f"- `{t.slug}` : {t.label} ({endpoints})"
    if t.description:
        head += f" — {t.description}"
    return head
