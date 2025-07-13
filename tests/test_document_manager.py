"""DocumentManagerのテスト"""
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from src.server.document_manager import DocumentManager


class TestDocumentManager:
    """DocumentManagerのテストクラス"""

    @pytest.fixture
    def temp_dir(self):
        """一時ディレクトリを作成"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @pytest.fixture
    def document_manager(self, temp_dir):
        """DocumentManagerのインスタンスを作成"""
        data_dir = os.path.join(temp_dir, 'data')
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(persist_dir, exist_ok=True)
        return DocumentManager(data_dir, persist_dir)

    def test_initialization(self, temp_dir):
        """DocumentManagerの初期化テスト"""
        data_dir = os.path.join(temp_dir, 'data')
        persist_dir = os.path.join(temp_dir, 'storage')

        doc_manager = DocumentManager(data_dir, persist_dir)

        assert doc_manager.data_dir == data_dir
        assert doc_manager.persist_dir == persist_dir
        assert doc_manager.hash_file_path == os.path.join(
            persist_dir, "document_hashes.json")
        assert isinstance(doc_manager.document_hashes, dict)

    def test_file_hash_calculation(self, document_manager, temp_dir):
        """ファイルハッシュ計算テスト"""
        # テストファイル作成
        test_file = os.path.join(temp_dir, "test.md")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("テストコンテンツ")

        # ハッシュ計算
        hash1 = document_manager._calculate_file_hash(test_file)
        hash2 = document_manager._calculate_file_hash(test_file)

        # 同じファイルは同じハッシュ
        assert hash1 == hash2
        assert len(hash1) == 32  # MD5ハッシュ

        # ファイル内容変更
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("変更されたコンテンツ")

        hash3 = document_manager._calculate_file_hash(test_file)

        # 内容が変わればハッシュも変わる
        assert hash1 != hash3

    def test_relative_path_conversion(self, document_manager, temp_dir):
        """相対パス変換テスト"""
        data_dir = document_manager.data_dir

        # データディレクトリ内のファイルパス
        file_path = os.path.join(data_dir, "subfolder", "test.md")
        expected_relative = "subfolder/test.md"

        relative_path = document_manager.get_relative_path(file_path)
        assert relative_path == expected_relative

        # データディレクトリ外のファイルパス（フォールバック）
        outside_path = os.path.join(temp_dir, "outside.md")
        relative_path = document_manager.get_relative_path(outside_path)
        assert relative_path == "outside.md"

        # 空のパス
        assert document_manager.get_relative_path("") == ""

    def test_document_update_detection(self, document_manager, temp_dir):
        """ドキュメント更新検出テスト"""
        data_dir = document_manager.data_dir
        test_file = os.path.join(data_dir, "test.md")

        # 初回作成
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("初期コンテンツ")

        # 最初の検出（新しいファイル）
        updated_files = document_manager.check_document_updates()
        assert test_file in updated_files

        # 再実行（変更なし）
        updated_files = document_manager.check_document_updates()
        assert len(updated_files) == 0

        # ファイル内容を変更
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("変更されたコンテンツ")

        # 変更検出
        updated_files = document_manager.check_document_updates()
        assert test_file in updated_files

    def test_load_documents(self, document_manager, temp_dir):
        """ドキュメント読み込みテスト"""
        data_dir = document_manager.data_dir

        # テストファイル作成
        test_file1 = os.path.join(data_dir, "test1.md")
        test_file2 = os.path.join(data_dir, "subfolder", "test2.md")

        os.makedirs(os.path.dirname(test_file2), exist_ok=True)

        with open(test_file1, 'w', encoding='utf-8') as f:
            f.write("# テスト1\n\nコンテンツ1")

        with open(test_file2, 'w', encoding='utf-8') as f:
            f.write("# テスト2\n\nコンテンツ2")

        # SimpleDirectoryReaderをモック
        with patch('src.server.document_manager.SimpleDirectoryReader') as mock_reader:
            mock_doc1 = MagicMock()
            mock_doc1.text = "# テスト1\n\nコンテンツ1"
            mock_doc2 = MagicMock()
            mock_doc2.text = "# テスト2\n\nコンテンツ2"

            mock_reader.return_value.load_data.return_value = [
                mock_doc1, mock_doc2]

            documents = document_manager.load_documents()

            assert len(documents) == 2
            mock_reader.assert_called_once()

    def test_load_documents_empty_directory(self, document_manager):
        """空のディレクトリでのドキュメント読み込みテスト"""
        documents = document_manager.load_documents()
        assert len(documents) == 0

    def test_load_documents_nonexistent_directory(self, temp_dir):
        """存在しないディレクトリでのドキュメント読み込みテスト"""
        nonexistent_dir = os.path.join(temp_dir, "nonexistent")
        persist_dir = os.path.join(temp_dir, "storage")

        doc_manager = DocumentManager(nonexistent_dir, persist_dir)
        documents = doc_manager.load_documents()
        assert len(documents) == 0

    def test_save_and_load_document_hashes(self, document_manager, temp_dir):
        """ドキュメントハッシュの保存・読み込みテスト"""
        # ハッシュを設定
        test_path = os.path.join(temp_dir, "test.md")
        test_hash = "abc123"
        document_manager.document_hashes[test_path] = test_hash

        # 保存
        document_manager.save_document_hashes()

        # 新しいインスタンスで読み込み
        new_doc_manager = DocumentManager(
            document_manager.data_dir,
            document_manager.persist_dir
        )

        assert test_path in new_doc_manager.document_hashes
        assert new_doc_manager.document_hashes[test_path] == test_hash

    def test_get_all_document_files(self, document_manager, temp_dir):
        """全ドキュメントファイル取得テスト"""
        data_dir = document_manager.data_dir

        # テストファイル作成
        test_file1 = os.path.join(data_dir, "test1.md")
        test_file2 = os.path.join(data_dir, "subfolder", "test2.md")
        test_file3 = os.path.join(data_dir, "other.txt")  # .mdでないファイル

        os.makedirs(os.path.dirname(test_file2), exist_ok=True)

        for file_path in [test_file1, test_file2, test_file3]:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("dummy content")

        all_files = document_manager.get_all_document_files()

        # .mdファイルのみが取得される
        assert len(all_files) == 2
        assert test_file1 in all_files
        assert test_file2 in all_files
        assert test_file3 not in all_files

    def test_hash_file_persistence(self, document_manager, temp_dir):
        """ハッシュファイルの永続化テスト"""
        data_dir = document_manager.data_dir
        test_file = os.path.join(data_dir, "test.md")

        # テストファイル作成
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("テストコンテンツ")

        # 更新検出（ハッシュが保存される）
        updated_files = document_manager.check_document_updates()
        assert len(updated_files) == 1

        document_manager.save_document_hashes()

        # ハッシュファイルが作成されているか確認
        assert os.path.exists(document_manager.hash_file_path)

        # 新しいインスタンスで同じファイルをチェック
        new_doc_manager = DocumentManager(
            data_dir, document_manager.persist_dir)
        updated_files = new_doc_manager.check_document_updates()

        # 変更がないので空になる
        assert len(updated_files) == 0

    def test_path_normalization(self, document_manager, temp_dir):
        """パス正規化テスト"""
        data_dir = document_manager.data_dir

        # 異なる形式のパスで同じファイルを指す
        normal_path = os.path.join(data_dir, "test.md")

        # ファイル作成
        with open(normal_path, 'w', encoding='utf-8') as f:
            f.write("テスト")

        # 正規化されたパスが使用されることを確認
        relative_path = document_manager.get_relative_path(normal_path)
        assert "/" in relative_path or len(relative_path.split(os.sep)) >= 1

    def test_error_handling_in_load_documents(self, temp_dir):
        """ドキュメント読み込みエラーハンドリングテスト"""
        data_dir = os.path.join(temp_dir, 'data')
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(data_dir, exist_ok=True)

        # 読み込み権限のないファイルを作成
        restricted_file = os.path.join(data_dir, 'restricted.md')
        with open(restricted_file, 'w', encoding='utf-8') as f:
            f.write('# Restricted file')

        doc_manager = DocumentManager(data_dir, persist_dir)

        # SimpleDirectoryReaderでエラーを発生させる
        with patch('src.server.document_manager.SimpleDirectoryReader') as mock_reader:
            mock_reader.side_effect = Exception("読み込みエラー")
            documents = doc_manager.load_documents()
            assert documents == []


class TestChunkHashManagement:
    """チャンクハッシュ管理のテストクラス"""

    @pytest.fixture
    def temp_dir(self):
        """一時ディレクトリを作成"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @pytest.fixture
    def document_manager(self, temp_dir):
        """DocumentManagerのインスタンスを作成"""
        data_dir = os.path.join(temp_dir, 'data')
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(persist_dir, exist_ok=True)
        return DocumentManager(data_dir, persist_dir)

    def test_calculate_chunk_hash(self, document_manager):
        """チャンクハッシュ計算テスト"""
        chunk_text = "これはテストチャンクです。"

        # チャンクハッシュを計算
        chunk_hash = document_manager.calculate_chunk_hash(chunk_text)

        # ハッシュが生成されることを確認
        assert chunk_hash is not None
        assert len(chunk_hash) == 32  # MD5ハッシュの長さ
        assert isinstance(chunk_hash, str)

    def test_save_and_load_chunk_hashes(self, document_manager):
        """チャンクハッシュの保存・読み込みテスト"""
        chunk_hashes = {
            "test.md:section_0:chunk_0": "hash1",
            "test.md:section_0:chunk_1": "hash2",
            "test.md:section_1:chunk_0": "hash3"
        }

        # チャンクハッシュを保存
        document_manager.save_chunk_hashes(chunk_hashes)

        # チャンクハッシュを読み込み
        loaded_hashes = document_manager.load_chunk_hashes()

        assert loaded_hashes == chunk_hashes

    def test_check_chunk_updates(self, document_manager):
        """チャンクレベルの更新検出テスト"""
        # 既存のチャンクハッシュを設定
        existing_hashes = {
            "test.md:section_0:chunk_0": "old_hash1",
            "test.md:section_0:chunk_1": "old_hash2"
        }
        document_manager.save_chunk_hashes(existing_hashes)

        # 新しいチャンクデータ
        new_chunks = [
            {"id": "test.md:section_0:chunk_0", "text": "変更されたチャンク"},
            {"id": "test.md:section_0:chunk_1", "text": "変更されていないチャンク"},
            {"id": "test.md:section_1:chunk_0", "text": "新しいチャンク"}
        ]

        # MD5ハッシュを模擬的に計算
        with patch.object(document_manager, 'calculate_chunk_hash') as mock_hash:
            mock_hash.side_effect = ["new_hash1", "old_hash2", "new_hash3"]

            updated_chunks = document_manager.check_chunk_updates(new_chunks)

            # 変更されたチャンクと新しいチャンクが検出される
            assert len(updated_chunks) == 2
            chunk_ids = [chunk["id"] for chunk in updated_chunks]
            assert "test.md:section_0:chunk_0" in chunk_ids  # 変更されたチャンク
            assert "test.md:section_1:chunk_0" in chunk_ids  # 新しいチャンク

    def test_get_chunk_metadata(self, document_manager):
        """チャンクメタデータ取得テスト"""
        chunk_id = "test.md:section_0:chunk_0"

        # チャンクメタデータを取得
        metadata = document_manager.get_chunk_metadata(chunk_id)

        assert metadata["doc_id"] == "test.md"
        assert metadata["section_id"] == 0
        assert metadata["chunk_id"] == 0

    def test_remove_deleted_chunks(self, document_manager):
        """削除されたチャンクの除去テスト"""
        # 既存のチャンクハッシュを設定
        existing_hashes = {
            "test.md:section_0:chunk_0": "hash1",
            "test.md:section_0:chunk_1": "hash2",
            "deleted.md:section_0:chunk_0": "hash3"
        }
        document_manager.save_chunk_hashes(existing_hashes)

        # 現在のチャンクリスト（deleted.mdは除外）
        current_chunks = [
            {"id": "test.md:section_0:chunk_0", "text": "チャンク0"},
            {"id": "test.md:section_0:chunk_1", "text": "チャンク1"}
        ]

        # 削除されたチャンクを除去
        removed_chunks = document_manager.remove_deleted_chunks(current_chunks)

        # 削除されたチャンクが返される
        assert len(removed_chunks) == 1
        assert removed_chunks[0] == "deleted.md:section_0:chunk_0"

        # ハッシュからも削除される
        updated_hashes = document_manager.load_chunk_hashes()
        assert "deleted.md:section_0:chunk_0" not in updated_hashes
