import pytest
import tempfile
import os
from unittest.mock import Mock, patch
from datetime import datetime

from src.server.todo_manager import TodoManager, TodoItem
from src.server.text_chunker import TextChunker
from src.server.rag_system import RAGSystem
from src.server.markdown_parser import MarkdownSection


class TestTodoRagIntegration:
    """TODO項目とRAGチャンクの統合テスト"""

    def setup_method(self):
        """各テストの前に実行される初期化処理"""
        self.temp_dir = tempfile.mkdtemp()
        self.persist_dir = tempfile.mkdtemp()
        self.todo_manager = TodoManager(self.temp_dir)
        self.text_chunker = TextChunker(
            chunk_size=800,
            chunk_overlap=100
        )

    def teardown_method(self):
        """各テストの後に実行されるクリーンアップ処理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        shutil.rmtree(self.persist_dir, ignore_errors=True)

    def test_todo_chunk_boundary_splitting(self):
        """TODOがある箇所でチャンクが分割されることを確認"""
        # Arrange
        text = """
        プロジェクトの概要について説明します。
        この機能は重要な役割を果たします。
        
        TODO: 機能Aの実装を完了させる
        
        機能Aの詳細仕様について説明します。
        この機能は以下の要件を満たす必要があります。
        
        FIXME: バグの修正が必要
        
        バグの詳細とその影響について記載します。
        """

        # Act
        chunks = self.text_chunker.split_text_with_todo_boundaries(text)

        # Assert
        assert len(chunks) >= 3  # TODO前、TODO後、FIXME前、FIXME後で分割される

        # TODOを含むチャンクは独立している
        todo_chunks = [chunk for chunk in chunks if 'TODO:' in chunk]
        assert len(todo_chunks) == 1

        # FIXMEを含むチャンクは独立している
        fixme_chunks = [chunk for chunk in chunks if 'FIXME:' in chunk]
        assert len(fixme_chunks) == 1

    def test_todo_chunk_relationship_creation(self):
        """TODOとRAGチャンクの関連付けが正しく作成されることを確認"""
        # Arrange
        text = """
        # プロジェクト計画
        
        プロジェクトの基本情報です。
        
        TODO: 機能Aの実装
        機能Aの詳細情報がここに記載されます。
        
        ## 次のステップ
        
        以下の作業を進めます。
        """

        # Act
        chunks_with_metadata = self.text_chunker.create_chunks_with_todo_metadata(
            text,
            file_path="test.md",
            section_id=1
        )

        # Assert
        todo_chunk = next(
            (chunk for chunk in chunks_with_metadata if 'TODO:' in chunk['text']),
            None
        )
        assert todo_chunk is not None
        assert todo_chunk['metadata']['has_todo'] is True
        assert todo_chunk['metadata']['todo_type'] == 'TODO'
        assert 'chunk_id' in todo_chunk['metadata']

    def test_todo_item_chunk_id_assignment(self):
        """TODO項目に関連チャンクIDが正しく割り当てられることを確認"""
        # Arrange
        text = "TODO: 機能Aの実装を完了させる\n機能Aの詳細説明"
        source_file = "test.md"
        source_section = "テストセクション"

        # Act
        todos = self.todo_manager.extract_todos_with_chunk_ids(
            text,
            source_file,
            source_section
        )

        # Assert
        assert len(todos) == 1
        todo = todos[0]
        assert hasattr(todo, 'related_chunk_ids')
        assert len(todo.related_chunk_ids) > 0
        assert todo.related_chunk_ids[0].startswith(f"{source_file}:section_")

    def test_chunk_metadata_todo_information(self):
        """チャンクメタデータにTODO情報が正しく格納されることを確認"""
        # Arrange
        text = """
        コンテキスト情報です。
        
        TODO: 重要な作業
        作業の詳細説明がここにあります。
        
        追加の情報です。
        """

        # Act
        chunks = self.text_chunker.create_chunks_with_todo_metadata(
            text,
            file_path="test.md",
            section_id=1
        )

        # Assert
        todo_chunk = next(
            (chunk for chunk in chunks if chunk['metadata'].get('has_todo')),
            None
        )
        assert todo_chunk is not None
        assert todo_chunk['metadata']['todo_content'] == "重要な作業"
        assert todo_chunk['metadata']['todo_type'] == "TODO"

    def test_multiple_todos_in_same_section(self):
        """同じセクション内に複数のTODOがある場合の処理を確認"""
        # Arrange
        text = """
        セクションの説明です。
        
        TODO: 最初の作業
        最初の作業の説明
        
        中間の説明文です。
        
        FIXME: 修正が必要な問題
        問題の詳細説明
        
        NOTE: 重要な注意事項
        注意事項の詳細
        """

        # Act
        chunks = self.text_chunker.create_chunks_with_todo_metadata(
            text,
            file_path="test.md",
            section_id=1
        )

        # Assert
        todo_chunks = [
            chunk for chunk in chunks if chunk['metadata'].get('has_todo')]
        assert len(todo_chunks) == 3

        todo_types = [chunk['metadata']['todo_type'] for chunk in todo_chunks]
        assert 'TODO' in todo_types
        assert 'FIXME' in todo_types
        assert 'NOTE' in todo_types

    def test_todo_context_search_preparation(self):
        """TODOコンテキスト検索のための準備データが正しく作成されることを確認"""
        # Arrange
        text = """
        # 機能開発
        
        機能の基本仕様です。
        
        TODO: APIエンドポイントの実装
        以下の仕様でAPIを実装する必要があります：
        - GET /api/users
        - POST /api/users
        
        ## 実装詳細
        
        具体的な実装方法について説明します。
        """

        # Act
        chunks = self.text_chunker.create_chunks_with_todo_metadata(
            text,
            file_path="features.md",
            section_id=1
        )

        # Assert
        todo_chunk = next(
            (chunk for chunk in chunks if chunk['metadata'].get('has_todo')),
            None
        )
        assert todo_chunk is not None

        # 検索用のコンテキスト情報が含まれている
        assert 'context_keywords' in todo_chunk['metadata']
        assert 'API' in todo_chunk['metadata']['context_keywords']
        assert 'エンドポイント' in todo_chunk['metadata']['context_keywords']

    def test_empty_text_handling(self):
        """空のテキストの処理を確認"""
        # Arrange
        text = ""

        # Act
        chunks = self.text_chunker.create_chunks_with_todo_metadata(
            text,
            file_path="empty.md",
            section_id=1
        )

        # Assert
        assert len(chunks) == 0

    def test_text_without_todos(self):
        """TODOを含まないテキストの処理を確認"""
        # Arrange
        text = """
        通常のテキストです。
        TODO という単語は含まれていますが、パターンではありません。
        これは普通の文章です。
        """

        # Act
        chunks = self.text_chunker.create_chunks_with_todo_metadata(
            text,
            file_path="normal.md",
            section_id=1
        )

        # Assert
        assert len(chunks) >= 1
        todo_chunks = [
            chunk for chunk in chunks if chunk['metadata'].get('has_todo')]
        assert len(todo_chunks) == 0

    def test_markdown_checkbox_todos(self):
        """Markdownチェックボックス形式のTODOの処理を確認"""
        # Arrange
        text = """
        タスクリスト：
        
        - [ ] 未完了のタスク1
        - [x] 完了済みのタスク
        - [ ] 未完了のタスク2
        
        以上がタスクリストです。
        """

        # Act
        chunks = self.text_chunker.create_chunks_with_todo_metadata(
            text,
            file_path="tasks.md",
            section_id=1
        )

        # Assert
        todo_chunks = [
            chunk for chunk in chunks if chunk['metadata'].get('has_todo')]
        assert len(todo_chunks) >= 2  # 未完了のタスクが2つ

        # 完了済みタスクも含む場合
        checkbox_chunks = [chunk for chunk in chunks if '- [' in chunk['text']]
        assert len(checkbox_chunks) >= 1

    def test_todo_priority_detection_in_chunks(self):
        """チャンク内でのTODO優先度検出を確認"""
        # Arrange
        text = """
        TODO: 緊急対応が必要な問題
        この問題は urgent に対応する必要があります。
        
        TODO: 後で対応する機能
        この機能は later に実装予定です。
        """

        # Act
        chunks = self.text_chunker.create_chunks_with_todo_metadata(
            text,
            file_path="priorities.md",
            section_id=1
        )

        # Assert
        todo_chunks = [
            chunk for chunk in chunks if chunk['metadata'].get('has_todo')]
        assert len(todo_chunks) == 2

        priorities = [chunk['metadata'].get(
            'todo_priority') for chunk in todo_chunks]
        assert 'high' in priorities
        assert 'low' in priorities
