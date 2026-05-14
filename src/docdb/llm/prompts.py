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
