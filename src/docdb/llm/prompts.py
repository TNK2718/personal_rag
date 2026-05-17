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
TEXT2SQL_PROMPT_MAX_BYTES = 30_000


EXTRACTION_SYSTEM_BASE = (
    "あなたは個人ノートから構造化メタデータを抽出するアシスタントです。\n"
    "次のルールに従い、必要なフィールドだけを正確に埋めてください。\n"
    "1. `doc_type` はメモ=memo / 会議=meeting / 日記=journal / 参考資料=reference / 仕様=spec / その他=other から1つ選ぶ。\n"
    "2. `title` は文書の主題を15字以内で要約。元タイトルがあればそのまま使う。\n"
    "3. `summary` は200字以内の日本語サマリ。冗長な前置きや感想は書かない。\n"
    "4. `language` は本文の主要言語を `ja` / `en` / `mixed` / `other` で表す。\n"
    "5. `tags` は3〜8個の短いカテゴリ語 (1〜2語) を小文字英数字または日本語で。\n"
    "6. 元の文書に存在しない情報を捏造しない。確信が持てないフィールドは空欄/空配列のままにする。\n"
    "\n"
    "# 出力 JSON は必ず次の shape に従う (下の値は仮置きの例。実際の値は本文から抽出する):\n"
    "{\n"
    '  "doc_type": "memo",\n'
    '  "title": "<ドキュメントタイトル>",\n'
    '  "summary": "<200字以内の日本語サマリ>",\n'
    '  "language": "ja",\n'
    '  "tags": ["<タグ1>", "<タグ2>"],\n'
    '  "entities": [\n'
    '    {"type": "person", "name": "<人物名>", "aliases": [], "fields": {}},\n'
    '    {"type": "task",   "name": "<タスク名>", "aliases": [], "fields": {"status": "pending"}}\n'
    '  ],\n'
    '  "relations": [\n'
    '    {"type": "assigned_to",\n'
    '     "source": {"type": "task",   "name": "<タスク名>"},\n'
    '     "target": {"type": "person", "name": "<人物名>"},\n'
    '     "fields": {}}\n'
    '  ]\n'
    "}\n"
    "\n"
    "形式の注意 (この通りに守らないと無視される):\n"
    "- 固有名は `name` キーに入れる。`canonical_name` などの別キーは使わない。\n"
    "- relation の `source` / `target` は **オブジェクト** `{\"type\":..., \"name\":...}` で渡す。\n"
    "  ID 文字列だけや、人物名だけの文字列を入れない。\n"
    "- 型固有のフィールド (task の `status` / `due_date` 等) は entity 直下ではなく\n"
    "  必ず `fields` オブジェクトの中に入れる。\n"
    "- `type` の値は下に列挙されている entity 型 / relation 型の slug のみ。それ以外は出力しない。\n"
    "- `tasks` や `events` のような独自の top-level 配列を勝手に追加しない。\n"
    "- **relation を書く前に、その `source` と `target` の (type, name) ペアが\n"
    "  上の `entities` 配列の中にも入っているか必ず確認する**。入っていなければ\n"
    "  先に `entities` 配列にその entity を追加してから relation を書く。\n"
    "  `entities` 配列に無い endpoint を参照した relation はパイプライン側で破棄される。"
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
    "6. ドキュメントを返すクエリには documents.id と title を含めると後工程が読みやすい。\n"
    "   entity を返すクエリには entities.id と canonical_name を含める。\n"
    "7. **entity 間の関係を辿るクエリは必ず `relations` テーブル経由で JOIN する。**\n"
    "   `entity_types` や `relation_types` は型カタログなので、ここに JOIN しても\n"
    "   個別のエンティティ・関係は出てこない。下の SQL 例を参照。\n"
    "8. 出力 JSON は {sql, reasoning} の 2 フィールドのみ。"
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


# Worked examples; gemma4:e2b (and other small models) otherwise invent
# nonsense JOINs like `entities.type_slug = relation_types.slug`.
# Each example is a canonical pattern; the LLM is expected to substitute
# names, type_slugs, and field keys appropriate to the user's question.
DOCDB_SCHEMA_EXAMPLES = """\
-- 例1) 人物名から所属組織を引く (entities → relations → entities の 3 テーブル JOIN)
SELECT org.id, org.canonical_name
FROM entities AS p
JOIN relations AS r  ON r.source_entity_id = p.id
JOIN entities AS org ON org.id = r.target_entity_id
WHERE p.type_slug = 'person'
  AND p.canonical_name LIKE '%山田花子%'
  AND r.type_slug = 'belongs_to'
LIMIT 10;

-- 例2) 未完了タスクの一覧 (json_extract で type 固有フィールドにアクセス)
SELECT id, canonical_name,
       json_extract(fields, '$.status')   AS status,
       json_extract(fields, '$.due_date') AS due_date
FROM entities
WHERE type_slug = 'task'
  AND json_extract(fields, '$.status') = 'pending'
ORDER BY json_extract(fields, '$.due_date')
LIMIT 50;

-- 例3) 「FluxSearch」を本文に含む文書 (FTS は documents_fts MATCH 経由)
SELECT d.id, d.title, d.doc_type
FROM documents_fts
JOIN documents d ON d.rowid = documents_fts.rowid
WHERE documents_fts MATCH 'FluxSearch'
LIMIT 20;

-- 例4) 特定の人物が言及されている文書 (entities → document_entities → documents)
SELECT d.id, d.title
FROM entities AS e
JOIN document_entities AS de ON de.entity_id = e.id
JOIN documents AS d          ON d.id = de.document_id
WHERE e.type_slug = 'person'
  AND e.canonical_name LIKE '%山田花子%'
LIMIT 20;
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
        "",
        "# SQL 例 (このパターンに従う)",
        DOCDB_SCHEMA_EXAMPLES,
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
# Lean prompt: routing + rules only. Two earlier sources of bloat are gone:
# (1) inline SQL schema in step 5 — `text_to_sql` injects its own schema,
#     and `execute_readonly_sql` is rarely needed; (2) the live entity /
#     relation type catalog that build_agent_system_prompt used to append
#     — the agent can call `describe_schema` on demand instead. Together
#     this cut the per-turn prompt+tools payload from ~8.2KB to ~2.7KB,
#     which keeps granite4.1:3b inside its coherence budget on Japanese
#     tool-call arguments (the model was previously emitting mixed-script
#     garbage like `相对ごかのリークティを列表します` under the larger prompt).
AGENT_SYSTEM_BASE = (
    "あなたは個人 Markdown メモを検索するエージェントです。\n"
    "提供されたツールのみを使い、ユーザーには日本語で簡潔に答えます。\n"
    "\n"
    "使うツールの選び方:\n"
    "1. デフォルトは `text_to_sql`。質問を日本語のままそのまま渡せば、内部で\n"
    "   SQL に変換してドキュメント・エンティティ・リレーションを横断検索する。\n"
    "   件数・条件・JOIN・期間絞り込みなど構造化問い合わせは全部これ。\n"
    "2. 本文中のフレーズや概念を意味検索したいときだけ `search_documents`。\n"
    "3. 既に id がわかっているなら `get_document` / `find_similar`。\n"
    "4. どんな entity 型・relation 型が登録されているか確かめたいときは\n"
    "   `describe_schema` (引数なし=サマリ、`kind` で絞り、`kind`+`slug` で詳細)。\n"
    "5. 自分で SELECT を書きたいときだけ `execute_readonly_sql`。\n"
    "\n"
    "ルール:\n"
    "- ツール結果に書かれていない情報を捏造しない。資料に無ければ「分かりません」と答える。\n"
    "- 回答末尾に出典を `[doc:document_id]` の形式で列挙する。\n"
    "- 不要なツール呼び出しを避け、十分な情報が揃ったら速やかに最終回答を返す。\n"
    "- ツールに渡す検索語や質問文はユーザーの言語 (日本語) のまま。\n"
    "  特に `text_to_sql` には質問をそのまま、訳さず・要約せず渡す。\n"
    "- JSON 文字列の中に日本語を書くときは、生の UTF-8 文字をそのまま入れる。\n"
    "  `\\uXXXX` のような Unicode エスケープ列は絶対に出力しない。"
)

# Single import surface: ``AGENT_SYSTEM`` is the agent's system prompt.
# There is no longer an assembler function — the prompt was previously
# augmented with a live type catalog, but that catalog overflowed
# granite4.1:3b's coherence budget. The catalog is now discovered on
# demand via the ``describe_schema`` tool.
AGENT_SYSTEM = AGENT_SYSTEM_BASE
