import pytest
import tempfile
import os
from src.server.rag_system import RAGSystem
from src.server.todo_manager import TodoItem
from datetime import datetime


class TestTodoDeduplication:
    """TODO重複除去のテストクラス"""

    def setup_method(self):
        """テストメソッドごとの初期設定"""
        # 一時ディレクトリを作成
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.temp_dir, "data")
        self.storage_dir = os.path.join(self.temp_dir, "storage")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.storage_dir, exist_ok=True)
        
        # RAGSystemインスタンスを作成
        self.rag_system = RAGSystem(
            data_dir=self.data_dir,
            persist_dir=self.storage_dir
        )

    def test_normalize_todo_content(self):
        """TODO内容の正規化をテスト"""
        test_cases = [
            ("TODO: テスト実装", "テスト実装"),
            ("Todo: テスト実装", "テスト実装"),
            ("todo: テスト実装", "テスト実装"),
            ("FIXME: バグ修正", "バグ修正"),
            ("- [ ] チェックボックスタスク", "チェックボックスタスク"),
            ("- [x] 完了タスク", "完了タスク"),
            ("  TODO:   空白が   多い   ", "空白が 多い"),
            ("  - リストアイテム  ", "リストアイテム"),
        ]
        
        for input_content, expected in test_cases:
            result = self.rag_system._normalize_todo_content(input_content)
            assert result == expected.lower(), f"Input: '{input_content}' -> Expected: '{expected.lower()}', Got: '{result}'"

    def test_deduplicate_todos_basic(self):
        """基本的な重複除去をテスト"""
        current_time = datetime.now().isoformat()
        
        # チャンクTODO
        chunk_todos = [
            TodoItem(
                id="chunk1",
                content="テスト実装",
                status="pending",
                priority="high",
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            )
        ]
        
        # テキストTODO（重複）
        text_todos = [
            TodoItem(
                id="text1",
                content="TODO: テスト実装",  # 同じ内容だが形式が異なる
                status="pending",
                priority="medium",
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            ),
            TodoItem(
                id="text2",
                content="新しいタスク",  # 重複ではない
                status="pending",
                priority="medium",
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            )
        ]
        
        result = self.rag_system._deduplicate_todos(chunk_todos, text_todos)
        
        # 重複除去により2つのユニークなTODOが残るべき
        assert len(result) == 2
        
        # チャンクTODOが優先されるべき
        assert result[0].id == "chunk1"
        assert result[1].id == "text2"

    def test_deduplicate_todos_empty_lists(self):
        """空リストの重複除去をテスト"""
        result = self.rag_system._deduplicate_todos([], [])
        assert len(result) == 0

    def test_deduplicate_todos_chunk_priority(self):
        """チャンクTODOが優先されることをテスト"""
        current_time = datetime.now().isoformat()
        
        chunk_todos = [
            TodoItem(
                id="chunk1",
                content="重要なタスク",
                status="pending",
                priority="high",  # チャンクの方が高優先度
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            )
        ]
        
        text_todos = [
            TodoItem(
                id="text1",
                content="TODO: 重要なタスク",  # 同じ内容
                status="pending",
                priority="low",  # テキストの方が低優先度
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            )
        ]
        
        result = self.rag_system._deduplicate_todos(chunk_todos, text_todos)
        
        # チャンクTODOが選ばれ、高優先度が保持されるべき
        assert len(result) == 1
        assert result[0].id == "chunk1"
        assert result[0].priority == "high"

    def test_deduplicate_todos_various_prefixes(self):
        """様々なプレフィックスの重複除去をテスト"""
        current_time = datetime.now().isoformat()
        
        chunk_todos = [
            TodoItem(
                id="chunk1",
                content="実装タスク",
                status="pending",
                priority="medium",
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            )
        ]
        
        text_todos = [
            TodoItem(
                id="text1",
                content="TODO: 実装タスク",
                status="pending",
                priority="medium",
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            ),
            TodoItem(
                id="text2",
                content="FIXME: 実装タスク",
                status="pending",
                priority="medium",
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            ),
            TodoItem(
                id="text3",
                content="- [ ] 実装タスク",
                status="pending",
                priority="medium",
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            ),
            TodoItem(
                id="text4",
                content="別のタスク",
                status="pending",
                priority="medium",
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            )
        ]
        
        result = self.rag_system._deduplicate_todos(chunk_todos, text_todos)
        
        # 同じ内容の3つは重複として除去、2つのユニークなTODOが残るべき
        assert len(result) == 2
        assert result[0].id == "chunk1"  # チャンクが優先
        assert result[1].id == "text4"   # 別のタスクは残る

    def test_deduplicate_todos_short_content_filter(self):
        """短すぎる内容のTODOがフィルタされることをテスト"""
        current_time = datetime.now().isoformat()
        
        chunk_todos = [
            TodoItem(
                id="chunk1",
                content="OK",  # 短すぎる（3文字以下）
                status="pending",
                priority="medium",
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            )
        ]
        
        text_todos = [
            TodoItem(
                id="text1",
                content="適切な長さのタスク",
                status="pending",
                priority="medium",
                created_at=current_time,
                updated_at=current_time,
                source_file="test.md",
                source_section="section1"
            )
        ]
        
        result = self.rag_system._deduplicate_todos(chunk_todos, text_todos)
        
        # 短すぎるTODOは除去され、1つだけ残るべき
        assert len(result) == 1
        assert result[0].id == "text1"

    def teardown_method(self):
        """テストメソッドごとのクリーンアップ"""
        # 一時ディレクトリを削除
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)