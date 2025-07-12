# Personal RAG System

## プロジェクト構成

```
personal_rag/
├── src/
│   ├── server/           # バックエンド
│   │   ├── server.py     # Flaskサーバー
│   │   └── rag_system.py # RAGシステム本体
│   └── frontend/         # フロントエンド
│       ├── index.html    # メインUI
│       ├── script.js     # フロントエンドロジック
│       └── styles.css    # スタイリング
├── data/                 # ドキュメントデータ（自動作成）
├── storage/              # インデックスストレージ（自動作成）
├── pyproject.toml        # uv設定ファイル
├── uv.lock              # 依存関係ロック
├── rag_tutorial.py      # RAGチュートリアル
└── README.md            # このファイル
```

## セットアップ

### 1. 依存関係のインストール

```bash
# uvを使用した依存関係のインストール（推奨）
uv sync

# または従来の方法（Python仮想環境）
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install flask flask-cors python-dotenv requests
```

### 2. データディレクトリの準備

```bash
# データディレクトリを作成
mkdir -p data

# Markdownファイルをdataディレクトリに配置
# 例: data/sample.md
```

### 3. Ollamaのセットアップ

```bash
# Ollamaをインストール（まだの場合）
curl -fsSL https://ollama.ai/install.sh | sh

# 必要なモデルをプル
ollama pull hf.co/mmnga/sarashina2.2-3b-instruct-v0.1-gguf:latest
ollama pull nomic-embed-text
```

## 使用方法

### サーバーの起動

```bash
# uvを使用（全プラットフォーム共通・推奨）
uv run python src/server/server.py

# または従来の方法
python src/server/server.py
```

サーバーは `http://localhost:5000` で起動します。

### フロントエンドの使用

1. ブラウザで `http://localhost:5000` にアクセス
2. 検索ボックスに質問を入力
3. 「検索」ボタンをクリック
4. 回答と引用元が表示されます

### 機能

- **質問応答**: 自然言語での質問に対する回答
- **引用元表示**: 回答の根拠となる文書の引用
- **検索履歴**: 過去の検索クエリの履歴表示
- **レスポンシブデザイン**: モバイルデバイス対応

## API エンドポイント

### GET /api/health
サーバーの状態を確認

### POST /api/query
質問に対する回答を取得

リクエスト:
```json
{
  "query": "質問内容"
}
```

レスポンス:
```json
{
  "answer": "回答内容",
  "sources": [
    {
      "header": "セクション見出し",
      "content": "セクション内容",
      "doc_id": "ドキュメントID",
      "section_id": 1,
      "level": 2,
      "score": 0.95
    }
  ]
}
```

## テスト

### テストの実行（全プラットフォーム共通）

```bash
# 依存関係の同期
uv sync

# 全テストを実行
uv run pytest

# カバレッジ付きでテストを実行
uv run pytest --cov=src --cov-report=html --cov-report=term

# ユニットテストのみ実行
uv run pytest tests/test_rag_system.py tests/test_data_classes.py -v

# APIテストのみ実行
uv run pytest tests/test_server.py -v

# ファイル管理機能のテスト
uv run pytest tests/test_file_management.py -v

# フロントエンド統合テスト
uv run pytest tests/test_frontend.py -v

# 新機能のテスト
uv run pytest tests/test_file_management.py tests/test_frontend.py -v

# 失敗時即停止テスト
uv run pytest --maxfail=1 -x
```

### テスト構成

- `tests/test_rag_system.py`: RAGシステムのユニットテスト
- `tests/test_server.py`: APIサーバーのテスト
- `tests/test_data_classes.py`: データクラスのテスト
- `tests/conftest.py`: テスト用の共通設定とフィクスチャ

### カバレッジレポート

```bash
# カバレッジレポートを生成
uv run pytest --cov=src --cov-report=html --cov-report=term

# レポートをブラウザで表示（Windows）
start htmlcov/index.html

# レポートをブラウザで表示（Mac）
open htmlcov/index.html

# レポートをブラウザで表示（Linux）
xdg-open htmlcov/index.html
```

カバレッジレポートは `htmlcov/index.html` で確認できます。

### テスト機能

- **RAGシステム**: TODO管理、Markdown解析、文書インデックス化
- **APIエンドポイント**: 全API機能のテスト
- **データクラス**: TodoItem、MarkdownSectionの検証
- **エラーハンドリング**: 例外処理とエラーレスポンス
- **モックテスト**: 外部依存関係の分離

## 開発

### ファイル構成

- `src/server/server.py`: FlaskサーバーとAPIエンドポイント
- `src/server/rag_system.py`: RAGシステムの実装
- `src/frontend/index.html`: メインUI
- `src/frontend/script.js`: フロントエンドロジック
- `src/frontend/styles.css`: スタイリング

### カスタマイズ

1. **モデルの変更**: `src/server/rag_system.py`のモデル設定を変更
2. **UIの変更**: `src/frontend/`内のファイルを編集
3. **APIの拡張**: `src/server/server.py`にエンドポイントを追加

## トラブルシューティング

### よくある問題

1. **Ollamaモデルがない**: 必要なモデルをプルしてください
2. **ポート競合**: 他のサーバーが5000番ポートを使用していないか確認
3. **依存関係エラー**: requirements.txtの依存関係を確認・再インストール

### ログの確認

```bash
# サーバーログを確認
python src/server/server.py
```

## ライセンス

MIT License
