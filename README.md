# Personal RAG System

ローカル Markdown コーパスに対する agentic RAG。
SQLite + FTS5 + sqlite-vec をストレージに、Ollama 経由の LLM を使った tool-calling エージェントで検索・回答する。

**property-graph データモデル**: ドキュメント、タグ、ユーザー定義の **entity 型 / relation 型** を持つ。型と各型のフィールドスキーマは Settings 画面または `/api/types/*` から動的に追加・編集でき、LLM 抽出も登録済みの型に追従する。「TODO」「人物」「組織」などはすべて seed として用意された型の 1 種類で、ハードコードはされていない。

## プロジェクト構成

```
personal_rag/
├── src/
│   ├── docdb/            # コア RAG パッケージ (ingestion, search, agent, llm, schema)
│   ├── server/           # Flask HTTP API
│   │   ├── app.py
│   │   ├── __main__.py
│   │   ├── context.py
│   │   └── routes/
│   └── frontend/         # React + Vite フロントエンド (TypeScript / CSS Modules)
├── data/                 # Markdown コーパス (ingest 対象)
├── storage/              # SQLite データベース
├── tests/
│   ├── docdb/
│   └── server/
└── pyproject.toml
```

## セットアップ

### 1. Python 依存

```bash
uv sync --extra test --extra ingestion
```

### 2. Ollama (ローカル LLM / embedding)

```bash
ollama pull granite4.1:3b  # agent / extraction (default)
ollama pull bge-m3        # embeddings (1024 dims)
```

利用モデルは環境変数 (`DOCDB_AGENT_MODEL`, `DOCDB_EMBED_MODEL` など) で差し替え可能。

### 3. DB 初期化とコーパス取り込み

```bash
uv run docdb init
uv run docdb ingest-dir ./data
```

### 4. フロントエンドビルド

```bash
cd src/frontend
pnpm install
pnpm build              # dist/ に出力。Flask が serve する
```

## 起動

```bash
# バックエンド (ポート 5000)
uv run python -m server

# (任意) フロントエンドの開発サーバ (ポート 5173, /api/* を 5000 にプロキシ)
cd src/frontend && pnpm dev
```

ブラウザで `http://localhost:5000` (本番ビルド) もしくは `http://localhost:5173` (開発) を開く。

## 画面

- **Dashboard**: 件数サマリ、doc_type 別内訳、entity 型別件数、最近のドキュメント、`task` 型 entity の一覧
- **Ask**: 自然言語質問 → エージェント回答 + citations + tool trace
- **Documents**: 検索/フィルタ + 詳細 (raw Markdown レンダリング、紐づく entities / tags / similar)
- **Entities**: 型チップで切り替え → 動的フィールド付きで一覧/詳細/編集。`/entities?type=task` で旧 TODO ビューに相当
- **Settings**: entity 型 / relation 型の登録・編集 (フィールドスキーマと LLM 抽出ヒントを編集可能)
- **Ingest**: path / glob を指定して取り込みをトリガー

## API

すべて JSON。ベースは `/api`。

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/health` | 動作確認 |
| GET | `/api/stats` | 件数サマリ + entities_by_type / relations_total |
| GET | `/api/doc-types` | doc_type 件数 |
| GET | `/api/documents` | `?q=&doc_type=&date_from=&date_to=&limit=&offset=` |
| GET | `/api/documents/<id>` | 詳細 (entities / tags 含む) |
| GET | `/api/documents/<id>/similar` | ベクトル類似 |
| POST | `/api/search` | `{query, top_k?, doc_type?, date_from?, date_to?, hybrid?}` |
| POST | `/api/ask` | `{question, max_iters?}` → agent 結果 (answer / citations / trace) |
| GET / POST | `/api/types/entities` | エンティティ型一覧 / 新規作成 |
| GET / PUT / DELETE | `/api/types/entities/<slug>` | エンティティ型詳細 / 更新 / 削除 |
| GET / POST | `/api/types/relations` | 関係型一覧 / 新規作成 |
| GET / PUT / DELETE | `/api/types/relations/<slug>` | 関係型詳細 / 更新 / 削除 |
| GET | `/api/entities` | `?q=&type_slug=&top_k=` |
| POST | `/api/entities` | `{type_slug, canonical_name, aliases?, description?, fields?}` |
| GET / PATCH / DELETE | `/api/entities/<id>` | 詳細 / 部分更新 / 削除 |
| GET | `/api/entities/<id>/documents` | エンティティ言及ドキュメント |
| GET / POST | `/api/relations` | `?type_slug=&source_entity_id=&target_entity_id=&top_k=` / 新規 |
| PATCH / DELETE | `/api/relations/<id>` | fields 更新 / 削除 |
| POST | `/api/ingest` | `{path?, glob?}` → IngestionReport[] |

## テスト

```bash
uv run pytest                       # 全テスト
uv run pytest tests/server --no-cov # API のみ
uv run pytest --cov=src --cov-report=html
```

## 開発のポイント

- バックエンドは状態を持たず、SQLite 接続をリクエストごとに開閉する (`src/server/context.py`)
- LLM は `LLMProtocol` 経由で抽象化されており、テストでは `FakeLLM` を注入
- フロントエンドは SWR で API キャッシュ。型レジストリは `src/frontend/src/api/useTypes.ts` の共有 SWR キャッシュから配給される
- 動的なエンティティフォームは `DynamicForm` (フィールドスキーマ → 入力ウィジェット) と `FieldSpecEditor` (スキーマ自体の編集) の 2 段構え
- LLM 抽出スキーマとシステムプロンプトは `docdb.typing.dynamic_model` と `docdb.llm.prompts.build_extraction_system_prompt` で登録済みの型から動的に組み立てる
- `docdb.typing.deterministic.task_checkbox` のような per-type 決定的抽出を毎ファイルで併走させ、LLM 結果とマージしてから normaliser に渡している

## アップグレード

旧スキーマ (v1 / v2) のデータベースから v3 (property graph) へは clean-start。

```bash
rm -rf storage/ data/
uv run docdb init
uv run docdb ingest-dir ./data
```

既存の `todos` 行は読み込まれない点に注意 (Stage 2 で `todos` テーブルが削除されたため)。手動で再入力するか、再 ingest で `task_checkbox` 決定的抽出に拾わせる。

## ライセンス

MIT License
