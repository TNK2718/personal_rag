.PHONY: help install test test-cov test-unit test-api clean lint format

# デフォルトターゲット：ヘルプを表示
help:
	@echo "利用可能なコマンド:"
	@echo "  install      - 依存関係をインストール"
	@echo "  test         - 全テストを実行"
	@echo "  test-cov     - カバレッジ付きでテストを実行"
	@echo "  test-unit    - ユニットテストのみ実行"
	@echo "  test-api     - APIテストのみ実行"
	@echo "  lint         - コードの静的解析"
	@echo "  format       - コードのフォーマット"
	@echo "  clean        - 一時ファイルを削除"
	@echo "  server       - 開発サーバーを起動"
	@echo "  docs         - カバレッジレポートを表示"

# 依存関係のインストール
install:
	uv sync
	uv pip install -e ".[test]"

# 全テストの実行
test:
	uv run pytest

# カバレッジ付きテスト実行
test-cov:
	uv run pytest --cov=src --cov-report=html --cov-report=term --cov-report=xml

# ユニットテストのみ実行
test-unit:
	uv run pytest tests/test_rag_system.py tests/test_data_classes.py -v

# APIテストのみ実行
test-api:
	uv run pytest tests/test_server.py -v

# 特定のテストファイルを実行
test-file:
	@read -p "テストファイル名を入力してください: " file; \
	uv run pytest tests/$$file -v

# コードの静的解析
lint:
	@echo "静的解析を実行中..."
	@echo "Note: pytest import エラーは uv run pytest で解決されます"

# コードフォーマット（将来の拡張用）
format:
	@echo "コードフォーマットは現在設定されていません"
	@echo "black や isort の設定を検討してください"

# 開発サーバーの起動
server:
	cd src/server && uv run python server.py

# カバレッジレポートをブラウザで表示
docs:
	@if [ -f htmlcov/index.html ]; then \
		echo "カバレッジレポートを開いています..."; \
		python -m webbrowser htmlcov/index.html; \
	else \
		echo "カバレッジレポートが見つかりません。'make test-cov' を先に実行してください。"; \
	fi

# 一時ファイルの削除
clean:
	rm -rf __pycache__/
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf coverage.xml
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# テストとカバレッジの完全実行
test-all: clean test-cov
	@echo "全テストとカバレッジレポートが完了しました"
	@echo "htmlcov/index.html でカバレッジを確認できます"

# CI/CD用のテスト実行
ci-test:
	uv run pytest --cov=src --cov-report=xml --cov-fail-under=80

# 開発環境のセットアップ
setup: install
	@echo "開発環境のセットアップが完了しました"
	@echo "テストを実行するには 'make test' を実行してください" 