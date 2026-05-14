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

- `src/docdb/` がコアパッケージ（ingestion / search / agent / llm / schema / typing）
- `src/server/` は Flask HTTP API。状態を持たず、SQLite 接続はリクエストごとに開閉 (`src/server/context.py`)
- LLM は `LLMProtocol` 経由で抽象化、テストでは `FakeLLM` を注入
- 設定は `src/docdb/config.py` の `Settings` (pydantic-settings)。環境変数 `DOCDB_*` で上書き可

## データモデル: property graph

- エンティティ型と関係型は `entity_types` / `relation_types` テーブルにランタイム保存され、Settings 画面または `/api/types/*` から CRUD できる
- 各型は `FieldSpec[]` (JSON、`docdb.typing.field_spec`) を持ち、ユーザー定義のスキーマでフィールドを宣言する
- インスタンスは `entities` / `relations` テーブル。`entities.type_slug` / `relations.type_slug` で型へ FK。`fields` JSON は書き込み時に store 層で `FieldSpec` に照らして検証される
- LLM 抽出 (`docdb.ingestion.extractor`) は `docdb.typing.dynamic_model.build_extraction_model` で型レジストリ依存の Pydantic クラスを動的生成し、prompt も `docdb.llm.prompts.build_extraction_system_prompt` で型カタログを差し込む

## 重要な制約

- **エンティティの書き込みは必ず `DocumentStore.upsert_entity` 経由で行う**。生 SQL で entities テーブルに insert すると `entities_search` シャドウが更新されず、FTS から漏れる。同じく fields_schema 違反も SQL 直書きでは検出できない (SQLite の `json_valid` は形式しか見ない)
- 型を削除する際、参照中の entities があると FK RESTRICT で 409 が返る。UI は事前に件数を見せて先に削除を促す方針 (silent cascade はしない)
- LLM プロンプトは `Settings.extraction_prompt_max_bytes` (デフォルト 30KB) で切られる。ユーザー定義型が多すぎる場合は末尾から省略
- 旧スキーマ (v1 / v2) からは clean start。`storage/` を削除して再 ingest が必要

## 注意事項

- Ollama サーバが起動している必要がある
- データ (`data/`) とストレージ (`storage/`) ディレクトリは自動生成
- バックエンドは `http://localhost:5000`
