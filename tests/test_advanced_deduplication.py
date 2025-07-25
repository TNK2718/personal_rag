import pytest
import tempfile
import os
from datetime import datetime
from src.server.rag_system import RAGSystem
from src.server.todo_manager import TodoItem


class TestAdvancedDeduplication:
    """高度な重複除去のテストクラス"""

    def setup_method(self):
        """テストメソッドごとの初期設定"""
        # 一時ディレクトリを作成
        self.temp_data_dir = tempfile.mkdtemp()
        self.temp_storage_dir = tempfile.mkdtemp()
        
        # RAGSystemインスタンスを作成
        self.rag_system = RAGSystem(
            data_dir=self.temp_data_dir,
            persist_dir=self.temp_storage_dir
        )

    def test_normalize_todo_content_edge_cases(self):
        """正規化処理のエッジケースをテスト"""
        test_cases = [
            # 基本的なケース
            ("TODO: テスト実装", "テスト実装"),
            ("Todo: テスト実装", "テスト実装"),
            ("todo: テスト実装", "テスト実装"),
            
            # マークダウンチェックボックス
            ("- [ ] テスト実装", "テスト実装"),
            ("- [x] テスト実装", "テスト実装"),
            ("- テスト実装", "テスト実装"),
            ("* テスト実装", "テスト実装"),
            
            # スペースの処理
            ("  TODO:   テスト   実装  ", "テスト 実装"),
            ("\tTODO:\tテスト\t実装\t", "テスト 実装"),
            
            # 複数のプレフィックス候補（段階的に除去される）
            ("TODO: FIXME: テスト実装", "テスト実装"),  # 両方のプレフィックスが段階的に除去
            ("- [ ] TODO: テスト実装", "テスト実装"),   # チェックボックス+TODOの両方が除去
            
            # 句読点の違い（末尾の句読点は除去される）
            ("テスト実装。", "テスト実装"),
            ("テスト実装", "テスト実装"),
            
            # 全角・半角の違い（全角スペースは半角に変換される）
            ("テスト実装　完了", "テスト実装 完了"),
            ("テスト実装 完了", "テスト実装 完了"),
        ]
        
        for input_content, expected in test_cases:
            result = self.rag_system._normalize_todo_content(input_content)
            assert result == expected.lower(), f"Input: '{input_content}' -> Expected: '{expected.lower()}', Got: '{result}'"

    def test_subtle_content_differences(self):
        """微妙な内容の違いによる重複テスト"""
        current_time = datetime.now().isoformat()
        
        # 似ているが異なるTODO
        todos = [
            TodoItem(
                id="1", content="API実装", status="pending", priority="medium",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
            TodoItem(
                id="2", content="TODO: API実装", status="pending", priority="medium",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
            TodoItem(
                id="3", content="- [ ] API実装", status="pending", priority="medium",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
            TodoItem(
                id="4", content="API実装を行う", status="pending", priority="medium",  # 異なる内容
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
        ]
        
        # 重複除去を実行
        result = self.rag_system._deduplicate_todos(todos[:3], [todos[3]])
        
        # 2つのTODOが残るべき（"API実装" と "API実装を行う"）
        assert len(result) == 2
        
        # 内容を確認
        contents = [self.rag_system._normalize_todo_content(todo.content) for todo in result]
        assert "api実装" in contents
        assert "api実装を行う" in contents

    def test_complex_markdown_patterns(self):
        """複雑なマークダウンパターンの重複除去をテスト"""
        current_time = datetime.now().isoformat()
        
        todos = [
            TodoItem(
                id="1", content="- [ ] データベース設計", status="pending", priority="high",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
            TodoItem(
                id="2", content="* [ ] データベース設計", status="pending", priority="medium",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
            TodoItem(
                id="3", content="TODO: データベース設計", status="pending", priority="low",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
            TodoItem(
                id="4", content="データベース設計", status="pending", priority="medium",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
        ]
        
        # 重複除去を実行
        result = self.rag_system._deduplicate_todos(todos[:2], todos[2:])
        
        # 1つのTODOだけが残るべき
        assert len(result) == 1
        # 最初に追加されたTODO（チャンクTODO）が優先されるべき
        assert result[0].priority == "high"  # 最初のTODOの優先度

    def test_whitespace_and_punctuation_variations(self):
        """空白文字と句読点のバリエーションをテスト"""
        current_time = datetime.now().isoformat()
        
        todos = [
            TodoItem(
                id="1", content="ユーザー認証機能を実装する。", status="pending", priority="high",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
            TodoItem(
                id="2", content="TODO: ユーザー認証機能を実装する", status="pending", priority="medium",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
            TodoItem(
                id="3", content="  ユーザー認証機能を実装する  ", status="pending", priority="low",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
        ]
        
        # 正規化結果を確認
        normalized_contents = [self.rag_system._normalize_todo_content(todo.content) for todo in todos]
        print(f"Normalized contents: {normalized_contents}")
        
        # すべて同じ正規化結果になるべき（句読点の違いは許容）
        # しかし現在の実装では句読点は保持されるため、異なる扱いになる可能性がある
        
        result = self.rag_system._deduplicate_todos([todos[0]], todos[1:])
        
        # 句読点の違いにより、複数が残る可能性がある
        # これが問題の一因かもしれない
        print(f"Result count: {len(result)}")
        for todo in result:
            print(f"Content: '{todo.content}' -> Normalized: '{self.rag_system._normalize_todo_content(todo.content)}'")

    def test_japanese_character_variations(self):
        """日本語文字のバリエーションをテスト"""
        current_time = datetime.now().isoformat()
        
        todos = [
            TodoItem(
                id="1", content="テスト用データを作成", status="pending", priority="high",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
            TodoItem(
                id="2", content="テスト用データを作成する", status="pending", priority="medium",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
            TodoItem(
                id="3", content="テスト用のデータを作成", status="pending", priority="low",
                created_at=current_time, updated_at=current_time,
                source_file="test.md", source_section="section1"
            ),
        ]
        
        # これらは実際には異なる内容として扱われるべき
        result = self.rag_system._deduplicate_todos([todos[0]], todos[1:])
        
        # 3つすべてが残るべき（内容が微妙に異なるため）
        assert len(result) == 3

    def teardown_method(self):
        """テストメソッドごとのクリーンアップ"""
        import shutil
        shutil.rmtree(self.temp_data_dir, ignore_errors=True)
        shutil.rmtree(self.temp_storage_dir, ignore_errors=True)