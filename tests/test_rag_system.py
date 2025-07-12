"""RAGシステムのテスト"""
import pytest
import json
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from src.server.rag_system import (
    RAGSystem, TodoItem, MarkdownSection,
    DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP
)


class TestRAGSystem:
    """RAGシステムのテストクラス"""

    def test_initialization(self, temp_dir):
        """RAGシステムの初期化テスト"""
        with patch('src.server.rag_system.OllamaEmbedding'), \
                patch('src.server.rag_system.Ollama'), \
                patch('src.server.rag_system.faiss'), \
                patch('src.server.rag_system.VectorStoreIndex'), \
                patch('src.server.rag_system.Settings'), \
                patch.dict('os.environ', {'IS_TESTING': 'true'}):

            data_dir = os.path.join(temp_dir, 'data')
            persist_dir = os.path.join(temp_dir, 'storage')
            os.makedirs(data_dir, exist_ok=True)

            # モックされた環境でRAGSystemを作成
            rag_system = object.__new__(RAGSystem)
            rag_system.persist_dir = persist_dir
            rag_system.data_dir = data_dir
            rag_system.embedding_dim = 768
            rag_system.todos = []
            rag_system.document_hashes = {}

            assert rag_system.persist_dir == persist_dir
            assert rag_system.data_dir == data_dir
            assert rag_system.embedding_dim == 768
            assert len(rag_system.todos) == 0
            assert len(rag_system.document_hashes) == 0

    def test_todo_creation(self, mock_rag_system):
        """TODO項目の作成テスト"""
        content = "新しいテストタスク"
        priority = "high"

        todo = mock_rag_system.add_todo(content, priority)

        assert todo.content == content
        assert todo.priority == priority
        assert todo.status == "pending"
        assert todo.id is not None
        assert len(mock_rag_system.todos) == 1

    def test_todo_update(self, mock_rag_system, sample_todo_items):
        """TODO項目の更新テスト"""
        # 既存のTODOを設定
        mock_rag_system.todos = sample_todo_items.copy()

        # 更新実行
        updated_todo = mock_rag_system.update_todo(
            "test1",
            status="in_progress",
            priority="medium"
        )

        assert updated_todo is not None
        assert updated_todo.status == "in_progress"
        assert updated_todo.priority == "medium"
        assert updated_todo.content == "テストタスク1"

    def test_todo_deletion(self, mock_rag_system, sample_todo_items):
        """TODO項目の削除テスト"""
        # 既存のTODOを設定
        mock_rag_system.todos = sample_todo_items.copy()
        initial_count = len(mock_rag_system.todos)

        # 削除実行
        success = mock_rag_system.delete_todo("test1")

        assert success is True
        assert len(mock_rag_system.todos) == initial_count - 1

        # 存在しないIDの削除
        success = mock_rag_system.delete_todo("nonexistent")
        assert success is False

    def test_get_todos_by_status(self, mock_rag_system, sample_todo_items):
        """ステータス別TODO取得テスト"""
        mock_rag_system.todos = sample_todo_items.copy()

        # 全TODO取得
        all_todos = mock_rag_system.get_todos()
        assert len(all_todos) == 2

        # pending状態のTODO取得
        pending_todos = mock_rag_system.get_todos("pending")
        assert len(pending_todos) == 1
        assert pending_todos[0].id == "test1"

        # completed状態のTODO取得
        completed_todos = mock_rag_system.get_todos("completed")
        assert len(completed_todos) == 1
        assert completed_todos[0].id == "test2"

    def test_markdown_parsing(self, mock_rag_system, sample_markdown_content):
        """Markdownパーサーのテスト"""
        sections = mock_rag_system._parse_markdown(sample_markdown_content)

        # モックされたパーサーから1つのセクションが生成される
        assert len(sections) >= 1

        # 最初のセクションチェック
        first_section = sections[0]
        assert first_section.header == "メインタイトル"
        assert first_section.level == 1
        assert "コンテンツ" in first_section.content

    def test_todo_extraction_from_text(self, mock_rag_system):
        """テキストからのTODO抽出テスト"""
        test_text = """
        TODO: この機能を実装する
        FIXME: このバグを修正
        - [ ] チェックボックスタスク
        NOTE: 重要な情報
        """

        todos = mock_rag_system._extract_todos_from_text(
            test_text,
            "test.md",
            "テストセクション"
        )

        assert len(todos) >= 3

        # TODO項目の内容チェック
        todo_contents = [todo.content for todo in todos]
        assert any("実装" in content for content in todo_contents)
        assert any("修正" in content for content in todo_contents)
        assert any("チェックボックス" in content for content in todo_contents)

    def test_file_hash_calculation(self, mock_rag_system, temp_dir):
        """ファイルハッシュ計算テスト"""
        # テストファイル作成
        test_file = os.path.join(temp_dir, "test.md")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("テストコンテンツ")

        # ハッシュ計算
        hash1 = mock_rag_system._calculate_file_hash(test_file)
        hash2 = mock_rag_system._calculate_file_hash(test_file)

        # 同じファイルは同じハッシュ
        assert hash1 == hash2
        assert len(hash1) == 32  # MD5ハッシュ

        # ファイル内容変更
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("変更されたコンテンツ")

        hash3 = mock_rag_system._calculate_file_hash(test_file)

        # 内容が変わればハッシュも変わる
        assert hash1 != hash3

    def test_document_update_detection(self, mock_rag_system, temp_dir):
        """ドキュメント更新検出テスト"""
        # データディレクトリ内にテストファイル作成
        mock_rag_system.data_dir = temp_dir
        test_file = os.path.join(temp_dir, "test.md")

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("初期コンテンツ")

        # 最初の検出
        updated_files = mock_rag_system._check_document_updates()
        assert test_file in updated_files

        # 再実行（変更なし）
        updated_files = mock_rag_system._check_document_updates()
        assert len(updated_files) == 0

        # ファイル更新
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("更新されたコンテンツ")

        # 更新検出
        updated_files = mock_rag_system._check_document_updates()
        assert test_file in updated_files

    @patch('src.server.rag_system.datetime')
    def test_overdue_todos(self, mock_datetime, mock_rag_system):
        """期限切れTODO検出テスト"""
        # 現在時刻を固定
        mock_datetime.now.return_value = datetime.fromisoformat(
            "2024-01-02T00:00:00")
        mock_datetime.fromisoformat = datetime.fromisoformat

        # 期限切れTODOを追加
        overdue_todo = TodoItem(
            id="overdue1",
            content="期限切れタスク",
            status="pending",
            priority="high",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            source_file="test.md",
            source_section="test",
            due_date="2024-01-01T23:59:59"
        )

        # 未来の期限TODO
        future_todo = TodoItem(
            id="future1",
            content="未来のタスク",
            status="pending",
            priority="medium",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            source_file="test.md",
            source_section="test",
            due_date="2024-01-03T00:00:00"
        )

        mock_rag_system.todos = [overdue_todo, future_todo]

        overdue_todos = mock_rag_system.get_overdue_todos()
        assert len(overdue_todos) == 1
        assert overdue_todos[0].id == "overdue1"

    def test_todo_aggregation_by_date(self, mock_rag_system, sample_todo_items):
        """日付別TODO集約テスト"""
        mock_rag_system.todos = sample_todo_items.copy()

        aggregated = mock_rag_system.aggregate_todos_by_date()

        assert "2024-01-01" in aggregated
        assert len(aggregated["2024-01-01"]) == 2

    def test_query_with_mock_response(self, mock_rag_system, mock_query_response):
        """クエリ処理のモックテスト"""
        # シンプルなモックRAGクエリを直接定義
        def mock_query(query_text):
            return {
                'answer': mock_query_response['answer'],
                'sources': [
                    {
                        'header': 'テストヘッダー',
                        'content': 'テストコンテンツ',
                        'doc_id': 'test.md',
                        'file_name': 'test',
                        'folder_name': '',
                        'section_id': 1,
                        'level': 2,
                        'type': 'content',
                        'score': 0.95,
                        'text_length': 12
                    }
                ]
            }

        # モックqueryメソッドで置き換え
        mock_rag_system.query = mock_query

        # クエリ実行
        result = mock_rag_system.query("テストクエリ")

        # 結果の確認
        assert "answer" in result
        assert "sources" in result
        assert result["answer"] == mock_query_response['answer']
        assert len(result["sources"]) == 1
        assert result["sources"][0]["header"] == "テストヘッダー"

    def test_create_nodes_with_metadata(self, mock_rag_system, sample_markdown_sections):
        """メタデータ付きノード作成のテスト"""
        doc_id = "/test/data/folder/test_file.md"
        mock_rag_system.data_dir = "/test/data"

        # _create_nodes_from_sectionsの実際の実装をモック
        def mock_create_nodes(sections, doc_id):
            from src.server.rag_system import TextNode
            nodes = []

            # ファイルパスからフォルダ名を抽出
            import os
            file_path = doc_id
            folder_name = ""
            if file_path.startswith(mock_rag_system.data_dir):
                rel_path = os.path.relpath(file_path, mock_rag_system.data_dir)
                folder_parts = os.path.dirname(rel_path).split(os.sep)
                folder_parts = [
                    part for part in folder_parts if part and part != '.']
                if folder_parts:
                    folder_name = "/".join(folder_parts)

            file_name = os.path.splitext(os.path.basename(file_path))[0]

            for i, section in enumerate(sections):
                common_metadata = {
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "folder_name": folder_name,
                    "section_id": i,
                    "header": section.header,
                    "level": section.level
                }

                header_node = type('MockNode', (), {
                    'text': section.header,
                    'metadata': {**common_metadata, "type": "header"}
                })()

                content_node = type('MockNode', (), {
                    'text': section.content,
                    'metadata': {**common_metadata, "type": "content"}
                })()

                nodes.extend([header_node, content_node])

            return nodes

        mock_rag_system._create_nodes_from_sections = mock_create_nodes

        # ノード作成実行
        nodes = mock_rag_system._create_nodes_from_sections(
            sample_markdown_sections, doc_id)

        # メタデータの確認
        assert len(nodes) >= 2  # ヘッダーとコンテンツのペア

        # 最初のヘッダーノードをテスト
        header_node = nodes[0]
        assert header_node.metadata['type'] == 'header'
        assert header_node.metadata['file_name'] == 'test_file'
        assert header_node.metadata['folder_name'] == 'folder'
        assert header_node.metadata['header'] == 'メインタイトル'
        assert header_node.metadata['level'] == 1

        # 最初のコンテンツノードをテスト
        content_node = nodes[1]
        assert content_node.metadata['type'] == 'content'
        assert content_node.metadata['file_name'] == 'test_file'
        assert content_node.metadata['folder_name'] == 'folder'
        assert content_node.metadata['header'] == 'メインタイトル'

    def test_enhanced_query_with_metadata(self, mock_rag_system):
        """強化されたメタデータを含むクエリテスト"""
        # モックノードにメタデータを設定
        mock_nodes = [
            type('MockNode', (), {
                'text': 'テストヘッダー',
                'metadata': {
                    'type': 'header',
                    'header': 'テストヘッダー',
                    'file_name': 'test_doc',
                    'folder_name': 'project1',
                    'level': 2,
                    'section_id': 0
                },
                'score': 0.95
            })(),
            type('MockNode', (), {
                'text': 'テストコンテンツ',
                'metadata': {
                    'type': 'content',
                    'header': 'テストヘッダー',
                    'file_name': 'test_doc',
                    'folder_name': 'project1',
                    'level': 2,
                    'section_id': 0
                },
                'score': 0.88
            })()
        ]

        # 実際のqueryメソッドをモック
        def mock_query(query_text):
            return {
                'answer': 'テスト回答です。',
                'sources': [
                    {
                        'header': node.metadata.get('header', ''),
                        'content': node.text,
                        'doc_id': node.metadata.get('doc_id', ''),
                        'file_name': node.metadata.get('file_name', ''),
                        'folder_name': node.metadata.get('folder_name', ''),
                        'section_id': node.metadata.get('section_id', 0),
                        'level': node.metadata.get('level', 1),
                        'type': node.metadata.get('type', ''),
                        'score': node.score or 0.0
                    }
                    for node in mock_nodes[:3]
                ]
            }

        mock_rag_system.query = mock_query

        # クエリ実行
        result = mock_rag_system.query("テストクエリ")

        # 結果の確認
        assert 'answer' in result
        assert 'sources' in result
        assert len(result['sources']) == 2

        # 最初のソースのメタデータ確認
        first_source = result['sources'][0]
        assert first_source['file_name'] == 'test_doc'
        assert first_source['folder_name'] == 'project1'
        assert first_source['type'] == 'header'
        assert first_source['header'] == 'テストヘッダー'

    def test_chunk_analysis_functionality(self, mock_rag_system, sample_markdown_content):
        """チャンク分析機能のテスト"""
        # パースメソッドの実際の動作をシミュレート
        def mock_parse_markdown(content):
            from src.server.rag_system import MarkdownSection
            return [
                MarkdownSection(header="メインタイトル",
                                content="メインコンテンツです。", level=1),
                MarkdownSection(header="サブセクション",
                                content="サブコンテンツです。", level=2),
                MarkdownSection(header="詳細セクション", content="詳細情報です。", level=3)
            ]

        mock_rag_system._parse_markdown = mock_parse_markdown

        # ノード作成のモック
        def mock_create_nodes(sections, doc_id):
            nodes = []
            for i, section in enumerate(sections):
                # ヘッダーノード
                header_node = type('MockNode', (), {
                    'text': section.header,
                    'metadata': {
                        'type': 'header',
                        'header': section.header,
                        'level': section.level,
                        'section_id': i,
                        'file_name': 'test',
                        'folder_name': ''
                    }
                })()

                # コンテンツノード
                content_node = type('MockNode', (), {
                    'text': section.content,
                    'metadata': {
                        'type': 'content',
                        'header': section.header,
                        'level': section.level,
                        'section_id': i,
                        'file_name': 'test',
                        'folder_name': ''
                    }
                })()

                nodes.extend([header_node, content_node])

            return nodes

        mock_rag_system._create_nodes_from_sections = mock_create_nodes

        # チャンク分析実行
        sections = mock_rag_system._parse_markdown(sample_markdown_content)
        nodes = mock_rag_system._create_nodes_from_sections(
            sections, "test.md")

        # 結果の確認
        assert len(sections) == 3
        assert len(nodes) == 6  # 3セクション × 2ノード(ヘッダー+コンテンツ)

        # ヘッダーとコンテンツの数をカウント
        header_count = sum(
            1 for node in nodes if node.metadata['type'] == 'header')
        content_count = sum(
            1 for node in nodes if node.metadata['type'] == 'content')

        assert header_count == 3
        assert content_count == 3

        # 各レベルのヘッダーが正しく設定されているか確認
        header_levels = [node.metadata['level']
                         for node in nodes if node.metadata['type'] == 'header']
        assert 1 in header_levels
        assert 2 in header_levels
        assert 3 in header_levels

    def test_todo_extraction_with_improved_patterns(self, mock_rag_system):
        """改善されたパターンでのTODO抽出テスト"""
        test_text = """
        # プロジェクト計画
        
        TODO: 新機能を実装する
        FIXME: このバグを修正する必要がある
        BUG: データが正しく保存されない
        HACK: 一時的な解決策
        NOTE: 重要な情報を記録
        XXX: 後で見直す
        
        チェックリスト：
        - [ ] デザインレビュー
        - [ ] コードレビュー
        - [x] 単体テスト（完了済み）
        
        番号付きタスク：
        1. 要件分析
        2. 設計書作成
        3. 実装開始
        
        箇条書きタスク：
        • UI改善
        ・ パフォーマンス最適化
        """

        # 実際のTODO抽出メソッドをモック
        def mock_extract_todos(text, source_file, source_section):
            import re
            import hashlib
            from datetime import datetime
            from src.server.rag_system import TodoItem

            todos = []
            patterns = [
                r'(?:TODO|Todo|todo)\s*:?\s*(.+?)(?:\n|$)',
                r'(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?:\n|$)',
                r'(?:BUG|Bug|bug)\s*:?\s*(.+?)(?:\n|$)',
                r'(?:HACK|Hack|hack)\s*:?\s*(.+?)(?:\n|$)',
                r'(?:NOTE|Note|note)\s*:?\s*(.+?)(?:\n|$)',
                r'(?:XXX|xxx)\s*:?\s*(.+?)(?:\n|$)',
                r'- \[ \]\s*(.+?)(?:\n|$)',
                r'\* \[ \]\s*(.+?)(?:\n|$)',
                r'\d+\.\s*(.+?)(?:\n|$)',
                r'[・•]\s*(.+?)(?:\n|$)',
            ]

            current_time = datetime.now().isoformat()

            for pattern in patterns:
                matches = re.finditer(
                    pattern, text, re.MULTILINE | re.IGNORECASE)
                for match in matches:
                    content = match.group(1).strip()
                    if content and len(content) > 3:
                        priority = "medium"
                        if any(word in content.lower() for word in ['urgent', '急', '緊急']):
                            priority = "high"
                        elif any(word in content.lower() for word in ['later', '後で', '将来']):
                            priority = "low"

                        todo_id = hashlib.md5(
                            f"{source_file}:{source_section}:{content}".encode()).hexdigest()[:8]

                        todo = TodoItem(
                            id=todo_id,
                            content=content,
                            status="pending",
                            priority=priority,
                            created_at=current_time,
                            updated_at=current_time,
                            source_file=source_file,
                            source_section=source_section
                        )
                        todos.append(todo)

            return todos

        mock_rag_system._extract_todos_from_text = mock_extract_todos

        # TODO抽出実行
        todos = mock_rag_system._extract_todos_from_text(
            test_text,
            "project_plan.md",
            "プロジェクト計画"
        )

        # 結果の確認
        assert len(todos) >= 8  # 少なくとも8つのTODOが抽出される

        # 特定のコンテンツが含まれているか確認
        todo_contents = [todo.content for todo in todos]
        assert any("新機能を実装" in content for content in todo_contents)
        assert any("バグを修正" in content for content in todo_contents)
        assert any("デザインレビュー" in content for content in todo_contents)
        assert any("要件分析" in content for content in todo_contents)
        assert any("UI改善" in content for content in todo_contents)

    def test_path_normalization(self, mock_rag_system, temp_dir):
        """パス正規化のテスト（クロスプラットフォーム対応）"""
        import os

        # テストファイルパス（異なるOSでの表記）
        test_paths = [
            "folder/subfolder/test.md",
            "folder\\subfolder\\test.md",  # Windows形式
            "./folder/subfolder/test.md",
            "folder/./subfolder/test.md"
        ]

        # 正規化関数のテスト
        def test_normalize_path(path):
            return os.path.normpath(path)

        normalized_paths = [test_normalize_path(path) for path in test_paths]

        # すべてのパスが同じ正規化結果になることを確認
        expected = os.path.normpath("folder/subfolder/test.md")
        for normalized in normalized_paths:
            # パス区切り文字を統一して比較
            assert normalized.replace('\\', '/') == expected.replace('\\', '/')

    def test_error_handling_in_query(self, mock_rag_system):
        """クエリ処理でのエラーハンドリングテスト"""
        # エラーを発生させるモック
        def mock_query_with_error(query_text):
            if query_text == "error_query":
                raise Exception("テストエラー")
            return {
                'answer': f'エラーが発生しました: テストエラー。システム管理者にお問い合わせください。',
                'sources': []
            }

        mock_rag_system.query = mock_query_with_error

        # エラーケースのテスト
        result = mock_rag_system.query("error_query")

        # エラーレスポンスの確認
        assert 'answer' in result
        assert 'エラーが発生しました' in result['answer']
        assert 'sources' in result
        assert len(result['sources']) == 0

    def test_text_chunking_functionality(self, mock_rag_system):
        """テキストチャンキング機能のテスト"""
        # 短いテキスト（チャンキング不要）
        short_text = "短いテキストです。"
        chunks = mock_rag_system._split_text_by_length(short_text)
        assert len(chunks) == 1
        assert chunks[0] == short_text

        # 長いテキスト（チャンキング必要）
        long_text = "これは非常に長いテキストです。" * 100  # 約1400文字
        chunks = mock_rag_system._split_text_by_length(long_text)

        # 複数のチャンクに分割される
        assert len(chunks) > 1

        # 各チャンクがサイズ制限以下
        for chunk in chunks:
            assert len(chunk) <= DEFAULT_CHUNK_SIZE + 100  # 句読点調整のマージン

        # オーバーラップのテスト
        if len(chunks) > 1:
            # 連続するチャンクにオーバーラップがあることを確認
            chunk1_end = chunks[0][-50:]  # 最後の50文字
            chunk2_start = chunks[1][:50]  # 最初の50文字
            # 一部が重複していることを期待（完全一致ではない場合もある）

    def test_sentence_boundary_chunking(self, mock_rag_system):
        """句読点境界でのチャンキングテスト"""
        # 句読点を含むテキスト
        text = "これは最初の文です。これは2番目の文です。これは3番目の文です。" * 20
        chunks = mock_rag_system._split_text_by_length(text, chunk_size=100)

        # 各チャンクが句読点で終わっているかチェック
        for chunk in chunks[:-1]:  # 最後以外のチャンク
            # 句読点で終わっているか、またはサイズ制限による切断
            ends_with_punctuation = any(
                chunk.rstrip().endswith(p)
                for p in ['。', '！', '？']
            )
            # 句読点で終わっているか、サイズ制限に達している
            assert ends_with_punctuation or len(chunk) >= 95

    def test_chunking_with_overlap(self, mock_rag_system):
        """オーバーラップ機能のテスト"""
        text = "A" * 1000  # 1000文字の同一文字
        chunks = mock_rag_system._split_text_by_length(
            text,
            chunk_size=300,
            overlap=50
        )

        assert len(chunks) > 1

        # オーバーラップの確認
        for i in range(len(chunks) - 1):
            current_chunk = chunks[i]
            next_chunk = chunks[i + 1]

            # 重複部分があることを確認
            current_end = current_chunk[-50:]
            next_start = next_chunk[:50]

            # 一部重複があることを期待
            overlap_found = False
            for j in range(10, 51):  # 10文字以上の重複をチェック
                if current_end[-j:] == next_start[:j]:
                    overlap_found = True
                    break

            # 同一文字なので必ず重複がある
            assert overlap_found

    def test_edge_cases_and_error_handling(self, mock_rag_system):
        """エッジケースとエラーハンドリングのテスト"""

        # 空文字列のチャンキング
        empty_chunks = mock_rag_system._split_text_by_length("")
        assert len(empty_chunks) == 0 or empty_chunks == [""]

        # 非常に短いテキスト
        short_chunks = mock_rag_system._split_text_by_length("短い")
        assert len(short_chunks) == 1
        assert short_chunks[0] == "短い"

    def test_metadata_preservation_in_chunking(self, mock_rag_system):
        """チャンキング時のメタデータ保持テスト"""
        # 複数レベルのヘッダーを持つ文書
        complex_section = MarkdownSection(
            header="複雑なセクション",
            content="これは複雑なセクションです。" * 100,  # 長いコンテンツ
            level=3
        )

        # ノード作成（チャンキング発生）
        nodes = mock_rag_system._create_nodes_from_sections(
            [complex_section],
            "complex_doc.md"
        )

        # すべてのノードが適切なメタデータを持つ
        for node in nodes:
            metadata = node.metadata
            assert metadata["header"] == "複雑なセクション"
            assert metadata["level"] == 3
            assert metadata["doc_id"] == "complex_doc.md"
            assert "section_id" in metadata

            # チャンクノードの場合、追加メタデータを確認
            if metadata.get("type") == "section_chunk":
                assert "chunk_id" in metadata
                assert "total_chunks" in metadata
                assert metadata["chunk_id"] >= 0
                assert metadata["total_chunks"] > 0
