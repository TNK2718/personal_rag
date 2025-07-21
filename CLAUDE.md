# CLAUDE.md

このファイルは、Claude Code (claude.ai/code) がこのリポジトリのコードを操作する際のガイダンスを提供します。

## プロジェクト概要

このプロジェクトは、Ollamaを使用したPersonal RAG（Retrieval-Augmented Generation）システムです。
FlaskバックエンドとフロントエンドUIを組み合わせた動的なRAGシステムを提供します。

## 主要機能
* markdown形式のメモ書き(data/ or memo/に格納を想定)に対するRAG
* 軽量モデル(Sarashina 3B)で日本語にフォーカスしたローカルRAG。メモ書きから文脈を考慮したRAG
* markdownにフォーカスしたRAG。見出しやTODO記載等からメタデータを構成し、メタデータを検索時に考慮
* クエリをAgenticにrewrite. メタデータによるフィルタを文脈に応じてAgenticに構成
* RAGの参照箇所の提示
* 日付を考慮したメモ内のTODO事項の集約とTODOリストの作成・永続化
* 朝9:00に昨日のサマリーとTODO事項のリマインド

## 開発環境

- Python 3.10以上
- Windows環境
- uv（Python パッケージマネージャー）
- Ollama（ローカルLLM）
- Flask（Webフレームワーク）
- FAISS（ベクトル検索）
- LlamaIndex（RAGフレームワーク）

### 依存関係のインストール
```bash
uv sync
```

### サーバーの起動
```bash
uv run python src/server/server.py
```

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
├── data/                 # ドキュメントデータ
├── storage/              # インデックスストレージ
├── pyproject.toml        # uv設定ファイル
└── rag_tutorial.py      # RAGチュートリアル
```

## 開発ガイドライン
t-wadaの推奨する方法に沿ったテスト駆動開発を行うこと

### コードスタイル
- Python: PEP 8に従う
- JavaScript: ES6+を使用
- HTML/CSS: セマンティックHTMLとレスポンシブデザイン
- 編集したらフォーマッターをかけて下さい

### 主要なファイル

1. **src/server/rag_system.py**: RAGシステムの核となるクラス
2. **src/server/server.py**: FlaskサーバーとAPIエンドポイント
3. **src/frontend/**: フロントエンドUI（HTML/CSS/JavaScript）

### API エンドポイント

- `GET /api/health`: サーバー状態確認
- `POST /api/query`: 質問応答API

### テストとデバッグ

- 機能変更をしたらテストを実行してください
- uv run pytest --cov=src --cov-report=html
- サーバーログは標準出力に表示
- ブラウザの開発者ツールでフロントエンドデバッグ
- `http://localhost:5000`でローカルテスト
- t-wadaの推奨する方法に沿ったテスト

## 注意事項

- データディレクトリ（data/）とストレージディレクトリ（storage/）は自動生成
- Ollamaサーバーが起動している必要があります
- ポート5000が使用可能である必要があります
- Cloud Shell環境では外部からのアクセスにポート転送が必要な場合があります
