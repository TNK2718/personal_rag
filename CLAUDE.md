# CLAUDE.md

このファイルは、Claude Code (claude.ai/code) がこのリポジトリのコードを操作する際のガイダンスを提供します。

## プロジェクト概要

ローカル Markdown コーパスに対する agentic RAG。
SQLite + FTS5 + sqlite-vec をストレージに、Ollama 経由の LLM を使った tool-calling エージェントで検索・回答する。

セットアップ・ディレクトリ構成・API 一覧は `README.md` を参照。

## 開発ガイドライン

- t-wada の推奨する方法に沿ったテスト駆動開発を行うこと
- Python は PEP 8、フロントエンドは TypeScript (React + Vite)
- 編集後はフォーマッターをかけること
- 機能変更後はテストを実行すること
  ```bash
  uv run pytest
  uv run pytest --cov=src --cov-report=html
  ```

## アーキテクチャ要点

- `src/docdb/` がコアパッケージ（ingestion / search / agent / llm / schema）
- `src/server/` は Flask HTTP API。状態を持たず、SQLite 接続はリクエストごとに開閉 (`src/server/context.py`)
- LLM は `LLMProtocol` 経由で抽象化、テストでは `FakeLLM` を注入
- 設定は `src/docdb/config.py` の `Settings` (pydantic-settings)。環境変数 `DOCDB_*` で上書き可

## 注意事項

- Ollama サーバが起動している必要がある
- データ (`data/`) とストレージ (`storage/`) ディレクトリは自動生成
- バックエンドは `http://localhost:5000`
