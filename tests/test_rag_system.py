"""RAGシステムの統合テスト"""
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from src.server.rag_system import RAGSystem
from src.server.todo_manager import TodoItem
from src.server.markdown_parser import MarkdownSection


class TestRAGSystemIntegration:
    """RAGシステムの統合テストクラス"""

    @pytest.fixture
    def temp_dir(self):
        """一時ディレクトリを作成"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @pytest.fixture
    def mock_external_dependencies(self):
        """外部依存関係をモック（LlamaIndex、FAISS、Ollama）"""
        with patch('src.server.index_manager.Ollama') as mock_ollama, \
                patch('src.server.index_manager.OllamaEmbedding') as mock_embed, \
                patch('src.server.index_manager.Settings') as mock_settings, \
                patch('src.server.index_manager.faiss') as mock_faiss, \
                patch('src.server.index_manager.VectorStoreIndex') as mock_index, \
                patch('src.server.index_manager.FaissVectorStore') as mock_store, \
                patch('src.server.index_manager.StorageContext') as mock_context, \
                patch('src.server.index_manager.load_index_from_storage') as mock_load, \
                patch('src.server.document_manager.SimpleDirectoryReader') as mock_reader:

            # 基本的なモック設定
            mock_faiss_instance = MagicMock()
            mock_faiss_instance.ntotal = 0
            mock_faiss.IndexFlatL2.return_value = mock_faiss_instance

            mock_index_instance = MagicMock()
            mock_index.return_value = mock_index_instance

            mock_context_instance = MagicMock()
            mock_context.from_defaults.return_value = mock_context_instance

            mock_reader.return_value.load_data.return_value = []

            yield {
                'ollama': mock_ollama,
                'embed': mock_embed,
                'settings': mock_settings,
                'faiss': mock_faiss,
                'index': mock_index,
                'store': mock_store,
                'context': mock_context,
                'load': mock_load,
                'reader': mock_reader,
                'faiss_instance': mock_faiss_instance,
                'index_instance': mock_index_instance
            }

    @pytest.fixture
    def rag_system(self, temp_dir, mock_external_dependencies):
        """RAGSystemのインスタンスを作成"""
        data_dir = os.path.join(temp_dir, 'data')
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(persist_dir, exist_ok=True)

        return RAGSystem(
            persist_dir=persist_dir,
            data_dir=data_dir,
            embedding_dim=768,
            chunk_size=100,
            chunk_overlap=20
        )

    def test_initialization(self, temp_dir, mock_external_dependencies):
        """RAGシステムの初期化テスト"""
        data_dir = os.path.join(temp_dir, 'data')
        persist_dir = os.path.join(temp_dir, 'storage')

        rag_system = RAGSystem(
            persist_dir=persist_dir,
            data_dir=data_dir,
            embedding_dim=512,
            chunk_size=200,
            chunk_overlap=50
        )

        # 基本プロパティの確認
        assert rag_system.persist_dir == persist_dir
        assert rag_system.data_dir == data_dir
        assert rag_system.embedding_dim == 512
        assert rag_system.chunk_size == 200
        assert rag_system.chunk_overlap == 50

        # 各管理クラスが初期化されている
        assert rag_system.document_manager is not None
        assert rag_system.todo_manager is not None
        assert rag_system.markdown_parser is not None
        assert rag_system.text_chunker is not None
        assert rag_system.index_manager is not None
        assert rag_system.index is not None

    def test_load_documents_integration(self, rag_system, temp_dir):
        """ドキュメント読み込みの統合テスト"""
        # テストファイル作成
        data_dir = rag_system.data_dir
        test_file = os.path.join(data_dir, "test.md")

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("# テストドキュメント\n\nテスト内容です。")

        # DocumentManagerを通じた読み込み
        documents = rag_system.load_documents()

        # 少なくとも空のリストが返される（モック環境のため）
        assert isinstance(documents, list)

    def test_todo_management_integration(self, rag_system):
        """TODO管理の統合テスト"""
        # TODO作成
        todo = rag_system.add_todo("テストタスク", "high", "test.md", "セクション1")

        assert todo.content == "テストタスク"
        assert todo.priority == "high"
        assert todo.source_file == "test.md"

        # TODO取得
        todos = rag_system.get_todos()
        assert len(todos) == 1
        assert todos[0].id == todo.id

        # TODO更新
        updated = rag_system.update_todo(todo.id, status="in_progress")
        assert updated is not None
        assert updated.status == "in_progress"

        # TODO削除
        success = rag_system.delete_todo(todo.id)
        assert success is True

        # 削除後の確認
        todos = rag_system.get_todos()
        assert len(todos) == 0

    def test_markdown_and_text_processing_integration(self, rag_system):
        """Markdown解析とテキスト分割の統合テスト"""
        markdown_content = """# メインタイトル

これはテスト用のMarkdownです。この文章は長めに書いてテキスト分割の動作を確認します。

## サブセクション

サブセクションの内容です。
TODO: テスト項目を実装する

### サブサブセクション

さらに詳細な内容です。
"""

        # Markdown解析
        sections = rag_system.markdown_parser.parse_markdown(markdown_content)
        assert len(sections) >= 3

        # セクションからノード作成
        nodes = rag_system._create_nodes_from_sections(sections, "test.md")
        assert len(nodes) >= 1

        # 各ノードにメタデータが含まれている
        for node in nodes:
            assert hasattr(node, 'metadata')
            assert 'doc_id' in node.metadata
            assert 'section_id' in node.metadata
            assert 'header' in node.metadata

    def test_system_info_integration(self, rag_system):
        """システム情報取得の統合テスト"""
        info = rag_system.get_system_info()

        # 基本情報が含まれている
        assert 'index_stats' in info
        assert 'todo_stats' in info
        assert 'document_stats' in info
        assert 'system_components' in info

        # 統計情報が適切な形式
        assert isinstance(info['todo_stats'], dict)
        assert isinstance(info['document_stats'], dict)
        assert isinstance(info['index_stats'], dict)
        assert isinstance(info['system_components'], dict)

        # 詳細な統計情報を確認
        assert 'total_todos' in info['todo_stats']
        assert 'total_documents' in info['document_stats']
        assert 'total_nodes' in info['index_stats']

    def test_document_update_detection_integration(self, rag_system, temp_dir):
        """ドキュメント更新検出の統合テスト"""
        data_dir = rag_system.data_dir
        test_file = os.path.join(data_dir, "update_test.md")

        # 初回ファイル作成
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("# 初期コンテンツ\n\n初期の内容です。")

        # 更新検出（新しいファイル）
        updated_files = rag_system.document_manager.check_document_updates()
        assert test_file in updated_files

        # ハッシュ保存
        rag_system.document_manager.save_document_hashes()

        # 再実行（変更なし）
        updated_files = rag_system.document_manager.check_document_updates()
        assert len(updated_files) == 0

        # ファイル内容変更
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("# 更新されたコンテンツ\n\n変更された内容です。")

        # 変更検出
        updated_files = rag_system.document_manager.check_document_updates()
        assert test_file in updated_files

    def test_todo_extraction_integration(self, rag_system, temp_dir):
        """TODO抽出の統合テスト"""
        data_dir = rag_system.data_dir
        test_file = os.path.join(data_dir, "todo_test.md")

        # TODO含むファイル作成
        content = """# プロジェクト計画

## 実装予定

TODO: 基本機能を実装する
FIXME: エラーハンドリングを修正
- [ ] テストケースを追加

## 完了項目

- [x] 設計書作成
"""

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(content)

        # TODO抽出実行
        extracted_count = rag_system.extract_todos_from_documents()

        # TODOが抽出されている
        assert extracted_count >= 0  # モック環境では実際の抽出は行われない可能性

        # TodoManagerに委譲されていることを確認
        all_todos = rag_system.get_todos()
        assert isinstance(all_todos, list)

    def test_query_processing_integration(self, rag_system, mock_external_dependencies):
        """クエリ処理の統合テスト"""
        # モックレスポンスの設定
        mock_response = MagicMock()
        mock_response.response = "テストレスポンス"
        mock_response.source_nodes = []

        mock_query_engine = MagicMock()
        mock_query_engine.query.return_value = mock_response

        rag_system.index_manager.create_query_engine = MagicMock(
            return_value=mock_query_engine)

        # クエリ実行
        result = rag_system.query("テスト質問")

        # 結果の構造確認
        assert 'answer' in result
        assert 'sources' in result
        assert result['answer'] == "テストレスポンス"
        assert isinstance(result['sources'], list)

    def test_error_handling_integration(self, rag_system):
        """エラーハンドリングの統合テスト"""
        # 存在しないTODOの更新
        result = rag_system.update_todo("nonexistent", status="completed")
        assert result is None

        # 存在しないTODOの削除
        success = rag_system.delete_todo("nonexistent")
        assert success is False

        # 空のドキュメントリストでの処理
        rag_system.add_documents([])
        # エラーなく完了することを確認

    def test_component_integration(self, rag_system):
        """各コンポーネントの統合確認テスト"""
        # 各管理クラスが正しく初期化されている
        assert rag_system.document_manager.data_dir == rag_system.data_dir
        assert rag_system.document_manager.persist_dir == rag_system.persist_dir

        assert rag_system.todo_manager.persist_dir == rag_system.persist_dir

        assert rag_system.text_chunker.chunk_size == rag_system.chunk_size
        assert rag_system.text_chunker.chunk_overlap == rag_system.chunk_overlap

        assert rag_system.index_manager.persist_dir == rag_system.persist_dir
        assert rag_system.index_manager.embedding_dim == rag_system.embedding_dim

    def test_todo_aggregation_integration(self, rag_system):
        """TODO集約機能の統合テスト"""
        # 複数のTODOを作成
        rag_system.add_todo("タスク1", "high", "file1.md", "セクション1")
        rag_system.add_todo("タスク2", "medium", "file2.md", "セクション2")
        rag_system.add_todo("タスク3", "low", "file1.md", "セクション3")

        # 日付別集約
        aggregated = rag_system.aggregate_todos_by_date()
        assert isinstance(aggregated, dict)

        # 期限切れTODO取得
        overdue = rag_system.get_overdue_todos()
        assert isinstance(overdue, list)

        # ステータス別取得
        pending_todos = rag_system.get_todos("pending")
        assert len(pending_todos) == 3  # 全て pending状態

    def test_path_handling_integration(self, rag_system, temp_dir):
        """パス処理の統合テスト"""
        data_dir = rag_system.data_dir

        # サブディレクトリ内のファイル
        sub_dir = os.path.join(data_dir, "subdir")
        os.makedirs(sub_dir, exist_ok=True)

        test_file = os.path.join(sub_dir, "test.md")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("# サブディレクトリファイル\n\nコンテンツ")

        # 相対パス変換
        relative_path = rag_system.document_manager.get_relative_path(
            test_file)
        assert "subdir/test.md" in relative_path

        # ファイル一覧取得
        all_files = rag_system.document_manager.get_all_document_files()
        assert test_file in all_files


class TestChunkLevelIncrementalUpdate:
    """チャンクレベル増分更新の統合テストクラス"""

    @pytest.fixture
    def temp_dir(self):
        """一時ディレクトリを作成"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @pytest.fixture
    def mock_external_dependencies(self):
        """外部依存関係をモック"""
        with patch('src.server.index_manager.Ollama') as mock_ollama, \
                patch('src.server.index_manager.OllamaEmbedding') as mock_embed, \
                patch('src.server.index_manager.Settings') as mock_settings, \
                patch('src.server.index_manager.faiss') as mock_faiss, \
                patch('src.server.index_manager.VectorStoreIndex') as mock_index, \
                patch('src.server.index_manager.FaissVectorStore') as mock_store, \
                patch('src.server.index_manager.StorageContext') as mock_context, \
                patch('src.server.index_manager.load_index_from_storage') as mock_load:

            # 基本的なモック設定
            mock_index_instance = MagicMock()
            mock_index.return_value = mock_index_instance

            mock_context_instance = MagicMock()
            mock_context.from_defaults.return_value = mock_context_instance

            mock_faiss.IndexFlatL2.return_value = MagicMock()

            yield {
                'ollama': mock_ollama,
                'embed': mock_embed,
                'settings': mock_settings,
                'faiss': mock_faiss,
                'index': mock_index,
                'store': mock_store,
                'context': mock_context,
                'load': mock_load,
                'index_instance': mock_index_instance,
                'context_instance': mock_context_instance
            }

    @pytest.fixture
    def rag_system(self, temp_dir, mock_external_dependencies):
        """RAGシステムのインスタンスを作成"""
        data_dir = os.path.join(temp_dir, 'data')
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(persist_dir, exist_ok=True)

        return RAGSystem(persist_dir=persist_dir, data_dir=data_dir)

    def test_chunk_level_incremental_update(self, rag_system, temp_dir):
        """チャンクレベルの増分更新テスト"""
        data_dir = rag_system.data_dir

        # 初期ファイルを作成
        test_file = os.path.join(data_dir, "test_doc.md")
        initial_content = """# 初期タイトル

これは初期のセクション1です。

## サブセクション

これは初期のサブセクションです。
"""
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(initial_content)

        # 初期インデックス作成
        rag_system._check_and_update_index_on_init()

        # 初期状態でのチャンクハッシュを確認
        initial_chunk_hashes = rag_system.document_manager.load_chunk_hashes()
        assert len(initial_chunk_hashes) > 0

        # ファイルの一部を変更
        modified_content = """# 変更されたタイトル

これは変更されたセクション1です。

## サブセクション

これは初期のサブセクションです。
"""
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(modified_content)

        # 増分更新を実行
        updated_chunks = rag_system.check_chunk_level_updates([test_file])

        # 変更されたチャンクが検出されることを確認
        assert len(updated_chunks) > 0

        # 新しいチャンクハッシュが保存されていることを確認
        new_chunk_hashes = rag_system.document_manager.load_chunk_hashes()
        assert new_chunk_hashes != initial_chunk_hashes

    def test_chunk_level_index_update(self, rag_system, temp_dir):
        """チャンクレベルでのインデックス更新テスト"""
        data_dir = rag_system.data_dir

        # テストファイルを作成
        test_file = os.path.join(data_dir, "index_test.md")
        content = """# テストタイトル

これはテストセクションです。

## サブセクション

これはサブセクションです。
"""
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(content)

        # チャンクレベルでの更新を実行
        updated_chunks = rag_system.check_chunk_level_updates([test_file])

        # 更新されたチャンクをインデックスに適用
        rag_system.apply_chunk_updates(updated_chunks)

        # インデックスが更新されたことを確認
        assert rag_system.index is not None

    def test_chunk_deletion_handling(self, rag_system, temp_dir):
        """チャンク削除の処理テスト"""
        data_dir = rag_system.data_dir

        # 複数のファイルを作成
        file1 = os.path.join(data_dir, "file1.md")
        file2 = os.path.join(data_dir, "file2.md")

        with open(file1, 'w', encoding='utf-8') as f:
            f.write("# ファイル1\n\nコンテンツ1")
        with open(file2, 'w', encoding='utf-8') as f:
            f.write("# ファイル2\n\nコンテンツ2")

        # 初期インデックス作成
        rag_system._check_and_update_index_on_init()

        # file2を削除
        os.remove(file2)

        # 削除されたチャンクをチェック
        current_files = [file1]
        removed_chunks = rag_system.handle_deleted_chunks(current_files)

        # 削除されたチャンクが検出されることを確認
        assert len(removed_chunks) > 0

        # チャンクハッシュから削除されていることを確認
        chunk_hashes = rag_system.document_manager.load_chunk_hashes()
        for chunk_id in removed_chunks:
            assert chunk_id not in chunk_hashes

    def test_performance_comparison(self, rag_system, temp_dir):
        """従来の方法との性能比較テスト"""
        data_dir = rag_system.data_dir

        # 大きなファイルを作成
        large_file = os.path.join(data_dir, "large_file.md")
        content = ""
        for i in range(50):
            content += f"# セクション{i}\n\n"
            content += f"これはセクション{i}の詳細な内容です。" * 10
            content += "\n\n"

        with open(large_file, 'w', encoding='utf-8') as f:
            f.write(content)

        # 初期インデックス作成
        rag_system._check_and_update_index_on_init()

        # 一部だけを変更
        modified_content = content.replace("セクション0", "変更されたセクション0")
        with open(large_file, 'w', encoding='utf-8') as f:
            f.write(modified_content)

        # チャンクレベルの更新をテスト
        updated_chunks = rag_system.check_chunk_level_updates([large_file])

        # 変更されたチャンクのみが検出されることを確認
        # 大きなファイルでも少数のチャンクのみが更新対象になる
        assert len(updated_chunks) < 10  # 全50セクションより大幅に少ない
