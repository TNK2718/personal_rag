# PLAN — text2sql 用 `v_edges` view 追加 (Stage 6 A1)

> 本ファイルは次のセッションへの引き継ぎ用。実装が終わったら削除すること。

## 背景

直近 3 コミット (`ee0e995`, `4644858`, `b23f814`) で：

- agent_model を `granite4.1:3b` → `gemma4:e2b` に切替（granite ファミリーは日本語 tool-call が構造的に壊れる、確定）
- extraction / text2sql / agent の各プロンプトに worked example を投入

その後、text2sql の最後の弱点として **「small model が `entities` を `relation_types` に誤って JOIN する」** 問題が残っていた。`b23f814` で 4 例の worked example を入れて直したが、根本的には **schema 形状そのものが LLM に対して読みづらい**（`type_slug` という同名カラムが entity / relation 両方にある、3 テーブル JOIN 必須）。

3 案検討した中で **A1 案: graph-shape の view を 1 つ追加するだけ** を採用。理由：

- view 1 つで text_to_sql の認知負荷をほぼ全部消せる（`SELECT tgt_name FROM v_edges WHERE src_name LIKE ... AND edge_type='belongs_to'` で済む）
- backend Python / frontend TS / HTTP API 一切無変更（カラム rename は scope 199 occurrences で半日仕事 = 別 stage）
- 既存テーブルは normalize 状態を維持。view は読み取り専用補助

## スコープ

**IN**:
- `src/docdb/schema/schema.sql` に `CREATE VIEW IF NOT EXISTS v_edges` を 1 つ追加
- `src/docdb/search/text2sql.py` の `ALLOWED_TABLES` に `v_edges` 追加
- `src/docdb/llm/prompts.py` の `DOCDB_SCHEMA_SUMMARY` に v_edges の説明を追加
- `src/docdb/llm/prompts.py` の `DOCDB_SCHEMA_EXAMPLES` 例 1 を `v_edges` 経由に書き換え (古い 3-テーブル JOIN 例も残すか、置換するか要判断)
- `src/docdb/llm/prompts.py` の `TEXT2SQL_SYSTEM` rule #7 を「graph 探索は v_edges」に微調整
- テスト追加: `v_edges` が schema 初期化後に存在することと、典型クエリが期待行を返すこと
- 既存テストの追従: `test_schema_summary_documents_every_allowed_table` は `v_edges` の追加に対応

**OUT** (将来の別 stage):
- カラム rename (A2 / A3 案) — backend + frontend + API contract に波及するので別 PR
- 各 entity 型ごとの view (C 案) — 動的型 registry と密結合で複雑
- 各 relation 型ごとの view (B 案) — 型数が増えると view 爆発、まずは単一 `v_edges` で十分

## 実装手順

### Step 1: schema に view を追加

`src/docdb/schema/schema.sql` の relations テーブル定義（line 104-120 付近）の **直後** に追加：

```sql
-- ============================================================
-- Convenience view for text2sql / LLM-facing graph traversal.
-- Denormalises an edge with both endpoints' display name and type,
-- so an LLM can express "find X related to Y" with a single FROM
-- clause instead of the entities→relations→entities 3-table JOIN.
-- Read-only by construction (sqlite views).
-- ============================================================
CREATE VIEW IF NOT EXISTS v_edges AS
SELECT r.id                  AS edge_id,
       r.type_slug            AS edge_type,
       rt.label               AS edge_label,
       src.id                 AS src_id,
       src.type_slug          AS src_type,
       src.canonical_name     AS src_name,
       tgt.id                 AS tgt_id,
       tgt.type_slug          AS tgt_type,
       tgt.canonical_name     AS tgt_name,
       r.fields               AS edge_fields,
       r.created_ts           AS edge_created_ts
FROM relations    AS r
JOIN entities     AS src ON src.id = r.source_entity_id
JOIN entities     AS tgt ON tgt.id = r.target_entity_id
LEFT JOIN relation_types AS rt ON rt.slug = r.type_slug;
```

注意点：
- 既存の `schema_version` を bump する必要なし（view は idempotent な `IF NOT EXISTS`）
- ただし **既存 DB に view を後から足したい場合は `storage/` を消して `docdb init` し直すのが clean start**。CLAUDE.md の「v1/v2 から clean start」方針に合致。マイグレーション機構は実装していないので新規生成のみ対応

### Step 2: ALLOWED_TABLES に追加

`src/docdb/search/text2sql.py` line 49-63:

```python
ALLOWED_TABLES: set[str] = {
    "documents",
    "documents_fts",
    "entities",
    "entity_types",
    "entities_search",
    "entities_fts",
    "relations",
    "relation_types",
    "tags",
    "document_entities",
    "document_tags",
    "document_relations",
    "document_relation_mentions",
    "v_edges",                  # ← 追加
}
```

`sql_guard.validate_readonly_sql` は ALLOWED_TABLES に対する allowlist チェック。view 名を加えるだけで FROM v_edges が通る。

### Step 3: DOCDB_SCHEMA_SUMMARY に v_edges を追記

`src/docdb/llm/prompts.py` line 247 付近の DOCDB_SCHEMA_SUMMARY ブロック末尾に追加：

```
-- v_edges (VIEW): graph 探索専用。1 つの edge を src/tgt の名前と型ごと展開済み。
--   columns: edge_id, edge_type, edge_label, src_id, src_type, src_name,
--            tgt_id, tgt_type, tgt_name, edge_fields, edge_created_ts
--   usage: WHERE edge_type = 'belongs_to' AND src_name LIKE '%山田%'
--   note: relations → entities × 2 を JOIN 済み。これ 1 本で entity 間関係を辿れる。
```

### Step 4: DOCDB_SCHEMA_EXAMPLES 例 1 を書き換え

`src/docdb/llm/prompts.py` の DOCDB_SCHEMA_EXAMPLES 例 1 を、3-テーブル JOIN から v_edges 経由に置換：

```
-- 例1) 人物名から所属組織を引く (v_edges 経由 — 3 テーブル JOIN 不要)
SELECT tgt_id, tgt_name
FROM v_edges
WHERE src_type   = 'person'
  AND src_name LIKE '%山田花子%'
  AND edge_type  = 'belongs_to'
LIMIT 10;
```

例 4（document_entities 経由）は触らず残す。

### Step 5: TEXT2SQL_SYSTEM rule #7 を微調整

`src/docdb/llm/prompts.py` の rule #7 を：

```
"7. **entity 間の関係を辿るクエリは `v_edges` view を使う。** `entities → relations\n"
"   → entities` の 3 テーブル JOIN は v_edges 1 本で書ける。`entity_types` /\n"
"   `relation_types` は型カタログなので、ここに JOIN しても個別のエンティティ・\n"
"   関係は出てこない。下の SQL 例を参照。\n"
```

### Step 6: テスト追加

`tests/docdb/test_property_graph_agent.py` または `tests/docdb/test_schema.py` に：

```python
def test_v_edges_view_exists_and_is_queryable(conn) -> None:
    # シード後の clean DB で v_edges が view として存在し、SELECT 可能。
    rows = conn.execute(
        "SELECT name, type FROM sqlite_master "
        "WHERE name='v_edges' AND type='view'"
    ).fetchall()
    assert len(rows) == 1

def test_v_edges_returns_endpoints_for_seeded_edge(conn) -> None:
    # ２つの person + 1 つの belongs_to relation を入れて、v_edges 経由で取れる。
    store = DocumentStore(conn)
    p1 = Entity(id=entity_id_for("person", "alice"), type_slug="person", canonical_name="Alice")
    org = Entity(id=entity_id_for("org", "Acme"), type_slug="org", canonical_name="Acme")
    store.upsert_entity(p1)
    store.upsert_entity(org)
    rel = Relation(
        id=relation_id_for("belongs_to", p1.id, org.id),
        type_slug="belongs_to",
        source_entity_id=p1.id,
        target_entity_id=org.id,
    )
    store.upsert_relation(rel)
    rows = conn.execute(
        "SELECT src_name, tgt_name, edge_type FROM v_edges "
        "WHERE src_name = 'Alice' AND edge_type = 'belongs_to'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["tgt_name"] == "Acme"
```

### Step 7: 既存テストの追従

- `test_schema_summary_documents_every_allowed_table` (in `tests/docdb/test_property_graph_agent.py`):
  ALLOWED_TABLES に v_edges を入れたので DOCDB_SCHEMA_SUMMARY にも v_edges 記述があれば pass。Step 3 で追記済みなら OK
- `test_every_allowed_table_actually_exists_after_init_db`:
  v_edges を view として作っていれば pass

両方 `sqlite_master` から table と view を両方拾う作りなのでそのまま通るはず（test_every_... の方は要確認）

## 検証手順

```bash
# Schema reset + 再 ingest
rm -rf storage && uv run docdb init && uv run docdb ingest-dir data

# テスト
uv run pytest

# Integration probe (v_edges が生成 SQL に出るか)
uv run python -c "
import sys, json; sys.path.insert(0,'src'); sys.stdout.reconfigure(encoding='utf-8')
import docdb.ingestion
from docdb.config import get_settings
from docdb.llm.client import LLM
from docdb.search.text2sql import run_text2sql
from docdb.schema.connection import connection
with connection(get_settings().db_path) as c:
    r = run_text2sql(c, '山田花子さんの所属は？', LLM(get_settings()))
print('SQL :', r.validated_sql)
print('ROWS:', r.rows)
"
```

## 受け入れ基準

1. `pytest` 全 pass (現状 355)
2. 上記 integration probe で生成 SQL に `v_edges` が出現 + ROWS が `[{'tgt_name': 'ACME 株式会社', ...}]` を返す
3. Flask サーバー再起動後、`POST /api/ask {"question":"山田花子さんの所属は？"}` で正答 + citation

## 想定される落とし穴

- `connection.py:_apply_pragmas` で `PRAGMA foreign_keys = ON` が有効。view は FK 関係に直接影響しないが、CASCADE delete で relations が消えた時に view も自動で空になる挙動を確認しておく
- view の `LEFT JOIN relation_types` は `r.type_slug` が orphan な場合に edge_label を NULL で返す。これは正しい挙動（relation_types 行が削除されても edge 自体は残し得る、というのが store 層の今の挙動）
- gemma が v_edges を覚えるかは prompt 例次第。例 1 を v_edges 経由に書き換えれば transfer する見込み。書き換え後初回の probe で必ず確認すること

## 推定工数

30〜45 分（実装 + テスト追加 + 検証 + commit）

## 関連

- 直前 commit: `b23f814`, `4644858`, `ee0e995`
- 議論ログ: `memory/project_granite_tool_call_garble.md`
- 既存 worked examples: `src/docdb/llm/prompts.py` の `DOCDB_SCHEMA_EXAMPLES`
- 別 stage 候補（やらない）: カラム rename (A2/A3)、entity 型ごと view (C)、relation 型ごと view (B)
