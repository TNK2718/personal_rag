# Personal RAG System

ローカル Markdown コーパスに対する agentic RAG。
SQLite + FTS5 + sqlite-vec をストレージに、Ollama 経由の LLM を使った tool-calling エージェントで検索・回答する。

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
ollama pull qwen3:4b      # agent / extraction
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
npm install
npm run build           # dist/ に出力。Flask が serve する
```

## 起動

```bash
# バックエンド (ポート 5000)
uv run python -m server

# (任意) フロントエンドの開発サーバ (ポート 5173, /api/* を 5000 にプロキシ)
cd src/frontend && npm run dev
```

ブラウザで `http://localhost:5000` (本番ビルド) もしくは `http://localhost:5173` (開発) を開く。

## 画面

- **Dashboard**: 件数サマリ、doc_type 別内訳、最近のドキュメント、pending TODO
- **Ask**: 自然言語質問 → エージェント回答 + citations + tool trace
- **Documents**: 検索/フィルタ + 詳細 (raw Markdown レンダリング、紐づく todos / entities / tags / similar)
- **Todos**: status カンバン (drag & drop で更新)
- **Entities**: 検索 → エンティティ詳細 → 言及ドキュメント一覧
- **Ingest**: path / glob を指定して取り込みをトリガー

## API

すべて JSON。ベースは `/api`。

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/health` | 動作確認 |
| GET | `/api/stats` | 件数サマリ |
| GET | `/api/doc-types` | doc_type 件数 |
| GET | `/api/documents` | `?q=&doc_type=&date_from=&date_to=&limit=&offset=` |
| GET | `/api/documents/<id>` | 詳細 (todos / entities / tags 含む) |
| GET | `/api/documents/<id>/similar` | ベクトル類似 |
| POST | `/api/search` | `{query, top_k?, doc_type?, date_from?, date_to?, hybrid?}` |
| POST | `/api/ask` | `{question, max_iters?}` → agent 結果 (answer / citations / trace) |
| GET | `/api/entities` | `?q=&entity_type=&top_k=` |
| GET | `/api/entities/<id>/documents` | エンティティ言及ドキュメント |
| GET | `/api/todos` | `?status=&priority=&due_before=&source_document_id=` |
| PATCH | `/api/todos/<id>` | `{status?, priority?, due_date?, content?}` |
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
- フロントエンドは SWR で API キャッシュ、Markdown 表示は `marked`、Kanban は HTML5 DnD

## ライセンス

MIT License
