"""Prompt strings and prompt builders.

Keeping all prompt text in one module makes it easy to A/B test
phrasings, run ``grep`` for vocabulary the LLM is being asked to use,
and audit the system for hidden behavioural instructions.

The instructions are written in Japanese first because the target
corpus (personal memos, meeting notes, journal entries) is primarily
Japanese. English content still flows through correctly — the LLM is
told to keep canonical names in their original script.
"""

from __future__ import annotations

from docdb.ingestion.parser import ParsedDocument


EXTRACTION_SYSTEM = (
    "あなたは個人ノートから構造化メタデータを抽出するアシスタントです。\n"
    "次のルールに従い、必要なフィールドだけを正確に埋めてください。\n"
    "1. `doc_type` はメモ=memo / 会議=meeting / 日記=journal / 参考資料=reference / 仕様=spec / その他=other から1つ選ぶ。\n"
    "2. `title` は文書の主題を15字以内で要約。元タイトルがあればそのまま使う。\n"
    "3. `summary` は200字以内の日本語サマリ。冗長な前置きや感想は書かない。\n"
    "4. `language` は本文の主要言語を `ja` / `en` / `mixed` / `other` で表す。\n"
    "5. `entities` は固有名詞(人物・組織・製品・技術・場所)を抽出。`entity_type` を必ず付ける。\n"
    "   - 個人名は原文の表記を `name` に入れ、別表記を `aliases` に。\n"
    "   - 一般名詞 (例: 会議, 部屋) は entity ではなくタグにする。\n"
    "6. `tags` は3〜8個の短いカテゴリ語 (1〜2語) を小文字英数字または日本語で。\n"
    "7. `todos` は本文に書かれた未完了の TODO/作業項目のみを抽出。完了済み (例: [x]) は含めない。\n"
    "   - `priority` は緊急/asap/急 → high、後で/将来/later → low、それ以外は medium。\n"
    "   - 日付 (締切/期限/まで) があれば `due_date` を ISO 形式 (YYYY-MM-DD) で入れる。\n"
    "8. 元の文書に存在しない情報を捏造しない。確信が持てないフィールドは空欄/空配列のままにする。"
)


def build_extraction_user_prompt(
    parsed: ParsedDocument,
    *,
    max_body_chars: int = 8000,
) -> str:
    """Render the document into the user-side prompt for extraction.

    Layout:
        <system instructions>
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

    parts = [
        EXTRACTION_SYSTEM,
        "",
    ]
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
    "3. 許可テーブルは documents / documents_fts / entities / tags / "
    "document_entities / document_tags / document_relations / todos のみ。\n"
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
-- entities(id, canonical_name, entity_type, aliases JSON, description, metadata JSON)
--   entity_type ∈ {person, org, product, tech, place, other}
-- tags(id, canonical_name UNIQUE, aliases JSON, category)
-- document_entities(document_id, entity_id, mention_count, contexts JSON)
-- document_tags(document_id, tag_id, confidence, source)
-- document_relations(src_document_id, dst_document_id, relation_type, confidence, evidence)
-- todos(id, content, status, priority, due_date, source_document_id,
--       source_section, created_at, updated_at)
--   status ∈ {pending, in_progress, completed, cancelled}
--   priority ∈ {high, medium, low}
"""


def build_text2sql_user_prompt(question: str) -> str:
    return (
        f"{TEXT2SQL_SYSTEM}\n\n"
        "# スキーマ\n"
        f"{DOCDB_SCHEMA_SUMMARY}\n"
        "# 質問\n"
        f"{question}\n"
    )


# ---------------------------------------------------------------------------
# Search agent
# ---------------------------------------------------------------------------
AGENT_SYSTEM = (
    "あなたは個人 Markdown メモに対する検索エージェントです。\n"
    "提供されたツールのみを使って情報を探し、ユーザーの質問に日本語で簡潔に答えます。\n"
    "\n"
    "進め方:\n"
    "1. まず `search_documents` で広く検索する (3 文字以上の語を使う; 日本語FTS5の制約)。\n"
    "2. 言い換えや同義語が重要な質問では `hybrid=true` を渡す。\n"
    "3. 関連文書が見つかったら `get_document` で本文を確認する。\n"
    "4. 集計や横断条件には `execute_readonly_sql` を使う (SELECT のみ実行可能)。\n"
    "5. 人物・組織についての質問は `search_entities` → `get_entity_documents` の順に辿る。\n"
    "6. TODO リスト系の質問は `list_todos` を使う。\n"
    "\n"
    "ルール:\n"
    "- ツール結果に書かれていない情報を捏造しない。資料に存在しなければ「分かりません」と答える。\n"
    "- 回答末尾に出典を `[doc:document_id]` の形式で列挙する。\n"
    "- 不要なツール呼び出しを避ける。十分な情報が揃ったら速やかに最終回答を返す。"
)
