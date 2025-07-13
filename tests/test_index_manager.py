"""IndexManagerのテスト"""
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from src.server.index_manager import IndexManager


class TestIndexManager:
    """IndexManagerのテストクラス"""

    @pytest.fixture
    def temp_dir(self):
        """一時ディレクトリを作成"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @pytest.fixture
    def mock_dependencies(self):
        """外部依存関係をモック"""
        with patch('src.server.index_manager.Ollama') as mock_ollama, \
                patch('src.server.index_manager.OllamaEmbedding') as mock_embed, \
                patch('src.server.index_manager.Settings') as mock_settings, \
                patch('src.server.index_manager.faiss') as mock_faiss, \
                patch('src.server.index_manager.VectorStoreIndex') as mock_index, \
                patch('src.server.index_manager.FaissVectorStore') as mock_store, \
                patch('src.server.index_manager.StorageContext') as mock_context, \
                patch('src.server.index_manager.load_index_from_storage') as mock_load:

            # FAISSインデックスのモック
            mock_faiss_instance = MagicMock()
            mock_faiss_instance.ntotal = 5
            mock_faiss.IndexFlatL2.return_value = mock_faiss_instance
            mock_faiss.read_index.return_value = mock_faiss_instance

            # VectorStoreIndexのモック
            mock_index_instance = MagicMock()
            mock_index.return_value = mock_index_instance
            mock_load.return_value = mock_index_instance

            # StorageContextのモック
            mock_context_instance = MagicMock()
            mock_context.from_defaults.return_value = mock_context_instance

            yield {
                'ollama': mock_ollama,
                'embed': mock_embed,
                'settings': mock_settings,
                'faiss': mock_faiss,
                'index': mock_index,
                'store': mock_store,
                'context': mock_context,
                'load': mock_load,
                'faiss_instance': mock_faiss_instance,
                'index_instance': mock_index_instance,
                'context_instance': mock_context_instance
            }

    def test_initialization(self, temp_dir, mock_dependencies):
        """IndexManagerの初期化テスト"""
        persist_dir = os.path.join(temp_dir, 'storage')
        embedding_dim = 768

        index_manager = IndexManager(persist_dir, embedding_dim)

        assert index_manager.persist_dir == persist_dir
        assert index_manager.embedding_dim == embedding_dim
        assert index_manager.faiss_index_path == os.path.join(
            persist_dir, "faiss_index.bin")

        # LLMとEmbeddingが設定される
        mock_dependencies['ollama'].assert_called_once()
        mock_dependencies['embed'].assert_called_once()

    def test_initialize_index_new(self, temp_dir, mock_dependencies):
        """新しいインデックス作成テスト"""
        persist_dir = os.path.join(temp_dir, 'storage')

        index_manager = IndexManager(persist_dir)
        index = index_manager.initialize_index()

        # 新しいインデックスが作成される
        assert index is not None
        mock_dependencies['faiss'].IndexFlatL2.assert_called_with(768)

    def test_initialize_index_existing(self, temp_dir, mock_dependencies):
        """既存インデックス読み込みテスト"""
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(persist_dir, exist_ok=True)

        # FAISSインデックスファイルを作成（空ファイル）
        faiss_path = os.path.join(persist_dir, "faiss_index.bin")
        with open(faiss_path, 'w') as f:
            f.write("dummy")

        index_manager = IndexManager(persist_dir)
        index = index_manager.initialize_index()

        # 既存インデックスが読み込まれる
        assert index is not None
        mock_dependencies['faiss'].read_index.assert_called_with(faiss_path)

    def test_add_documents(self, temp_dir, mock_dependencies):
        """ドキュメント追加テスト"""
        index_manager = IndexManager(temp_dir)

        # モックドキュメント
        mock_documents = [MagicMock(), MagicMock()]
        mock_index = MagicMock()

        # 型チェックを回避するため、anyを使用
        from typing import Any
        index_manager.add_documents(mock_index, mock_documents)  # type: ignore

        # ドキュメントがインデックスに追加される
        assert mock_index.insert.call_count == 2

    def test_add_documents_empty(self, temp_dir, mock_dependencies):
        """空のドキュメントリスト追加テスト"""
        index_manager = IndexManager(temp_dir)
        mock_index = MagicMock()

        index_manager.add_documents(mock_index, [])

        # 何も追加されない
        mock_index.insert.assert_not_called()

    def test_add_nodes(self, temp_dir, mock_dependencies):
        """ノード追加テスト"""
        index_manager = IndexManager(temp_dir)

        # モックノード
        mock_nodes = [MagicMock(), MagicMock(), MagicMock()]
        mock_index = MagicMock()

        # 型チェックを回避するため
        index_manager.add_nodes(mock_index, mock_nodes)  # type: ignore

        # ノードがインデックスに追加される
        assert mock_index.insert.call_count == 3

    def test_create_query_engine(self, temp_dir, mock_dependencies):
        """クエリエンジン作成テスト"""
        index_manager = IndexManager(temp_dir)
        mock_index = MagicMock()

        query_engine = index_manager.create_query_engine(mock_index, top_k=10)

        # クエリエンジンが作成される
        mock_index.as_query_engine.assert_called_once_with(
            similarity_top_k=10,
            response_mode="compact",
            streaming=False
        )
        assert query_engine is not None

    def test_create_retriever(self, temp_dir, mock_dependencies):
        """リトリーバー作成テスト"""
        index_manager = IndexManager(temp_dir)
        mock_index = MagicMock()

        retriever = index_manager.create_retriever(mock_index, top_k=8)

        # リトリーバーが作成される
        mock_index.as_retriever.assert_called_once_with(similarity_top_k=8)
        assert retriever is not None

    def test_get_index_stats(self, temp_dir, mock_dependencies):
        """インデックス統計情報取得テスト"""
        index_manager = IndexManager(temp_dir, embedding_dim=512)

        # モックインデックスとFAISSインデックス
        mock_index = MagicMock()
        mock_vector_store = MagicMock()
        mock_faiss_index = MagicMock()
        mock_faiss_index.ntotal = 100
        mock_vector_store.faiss_index = mock_faiss_index
        mock_index.storage_context.vector_store = mock_vector_store

        stats = index_manager.get_index_stats(mock_index)

        assert stats['total_documents'] == 100
        assert stats['total_nodes'] == 100
        assert stats['vector_dimension'] == 512
        assert stats['storage_path'] == temp_dir

    def test_get_index_stats_error(self, temp_dir, mock_dependencies):
        """インデックス統計情報取得エラーテスト"""
        index_manager = IndexManager(temp_dir)

        # エラーを発生させるモック
        mock_index = MagicMock()
        # storage_contextプロパティアクセス時にエラーを発生
        type(mock_index).storage_context = PropertyMock(
            side_effect=Exception("Test error"))

        stats = index_manager.get_index_stats(mock_index)

        # デフォルト値が返される
        assert stats['total_documents'] == 0
        assert stats['total_nodes'] == 0

    def test_refresh_index(self, temp_dir, mock_dependencies):
        """インデックスリフレッシュテスト"""
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(persist_dir, exist_ok=True)

        # FAISSインデックスファイルを作成
        faiss_path = os.path.join(persist_dir, "faiss_index.bin")
        with open(faiss_path, 'w') as f:
            f.write("dummy")

        index_manager = IndexManager(persist_dir)
        mock_old_index = MagicMock()

        new_index = index_manager.refresh_index(mock_old_index)

        # ファイルが削除され、新しいインデックスが作成される
        assert not os.path.exists(faiss_path)
        assert new_index is not None

    def test_delete_index(self, temp_dir, mock_dependencies):
        """インデックス削除テスト"""
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(persist_dir, exist_ok=True)

        # テストファイルを作成
        test_file = os.path.join(persist_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test")

        index_manager = IndexManager(persist_dir)
        index_manager.delete_index()

        # ディレクトリが削除される
        assert not os.path.exists(persist_dir)

    def test_is_index_empty_true(self, temp_dir, mock_dependencies):
        """空のインデックス判定テスト（空）"""
        index_manager = IndexManager(temp_dir)

        # 空のFAISSインデックスをモック
        mock_index = MagicMock()
        mock_vector_store = MagicMock()
        mock_faiss_index = MagicMock()
        mock_faiss_index.ntotal = 0
        # _faiss_index属性も設定
        mock_vector_store._faiss_index = mock_faiss_index
        mock_vector_store.faiss_index = mock_faiss_index
        mock_index.storage_context.vector_store = mock_vector_store

        is_empty = index_manager.is_index_empty(mock_index)

        assert is_empty is True

    def test_is_index_empty_false(self, temp_dir, mock_dependencies):
        """空のインデックス判定テスト（非空）"""
        index_manager = IndexManager(temp_dir)

        # 非空のFAISSインデックスをモック
        mock_index = MagicMock()
        mock_vector_store = MagicMock()
        mock_faiss_index = MagicMock()
        mock_faiss_index.ntotal = 10
        # _faiss_index属性も設定
        mock_vector_store._faiss_index = mock_faiss_index
        mock_vector_store.faiss_index = mock_faiss_index
        mock_index.storage_context.vector_store = mock_vector_store

        is_empty = index_manager.is_index_empty(mock_index)

        assert is_empty is False

    def test_is_index_empty_error(self, temp_dir, mock_dependencies):
        """空のインデックス判定エラーテスト"""
        index_manager = IndexManager(temp_dir)

        # エラーを発生させるモック
        mock_index = MagicMock()
        # storage_contextプロパティアクセス時にエラーを発生
        type(mock_index).storage_context = PropertyMock(
            side_effect=Exception("Test error"))

        is_empty = index_manager.is_index_empty(mock_index)

        # エラー時はTrueを返す
        assert is_empty is True

    def test_save_index(self, temp_dir, mock_dependencies):
        """インデックス保存テスト"""
        persist_dir = os.path.join(temp_dir, 'storage')
        index_manager = IndexManager(persist_dir)

        mock_faiss_index = MagicMock()
        mock_storage_context = MagicMock()

        index_manager._save_index(mock_faiss_index, mock_storage_context)

        # FAISSインデックスが保存される
        mock_dependencies['faiss'].write_index.assert_called_once()
        mock_storage_context.persist.assert_called_once_with(
            persist_dir=persist_dir)

        # ディレクトリが作成される
        assert os.path.exists(persist_dir)

    def test_load_index_missing_file(self, temp_dir, mock_dependencies):
        """存在しないFAISSファイルの読み込みテスト"""
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(persist_dir, exist_ok=True)

        index_manager = IndexManager(persist_dir)

        # FAISSファイルが存在しない場合、新しいインデックスが作成される
        index = index_manager._load_index()

        assert index is not None
        # 新しいインデックス作成が呼ばれる
        mock_dependencies['faiss'].IndexFlatL2.assert_called()

    def test_persist_index_without_faiss(self, temp_dir, mock_dependencies):
        """FAISSインデックスなしでの永続化テスト"""
        index_manager = IndexManager(temp_dir)

        # FAISS属性を持たないモックインデックス
        mock_index = MagicMock()
        mock_vector_store = MagicMock()
        del mock_vector_store.faiss_index  # 属性を削除
        mock_index.storage_context.vector_store = mock_vector_store

        # エラーなく完了する（警告メッセージが出力される）
        index_manager._persist_index(mock_index)
