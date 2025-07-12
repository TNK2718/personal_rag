"""TodoManagerのテスト"""
import os
import tempfile
import pytest
from datetime import datetime, timedelta

from src.server.todo_manager import TodoManager, TodoItem


class TestTodoManager:
    """TodoManagerのテストクラス"""

    @pytest.fixture
    def temp_dir(self):
        """一時ディレクトリを作成"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @pytest.fixture
    def todo_manager(self, temp_dir):
        """TodoManagerのインスタンスを作成"""
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(persist_dir, exist_ok=True)
        return TodoManager(persist_dir)

    @pytest.fixture
    def sample_todo_items(self):
        """サンプルTODO項目を作成"""
        current_time = datetime.now().isoformat()
        tomorrow = (datetime.now() + timedelta(days=1)).isoformat()
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()

        return [
            TodoItem(
                id="test1",
                content="テストタスク1",
                status="pending",
                priority="high",
                created_at=current_time,
                updated_at=current_time,
                source_file="test1.md",
                source_section="セクション1",
                due_date=tomorrow
            ),
            TodoItem(
                id="test2",
                content="テストタスク2",
                status="completed",
                priority="medium",
                created_at=current_time,
                updated_at=current_time,
                source_file="test2.md",
                source_section="セクション2",
                due_date=yesterday
            ),
            TodoItem(
                id="test3",
                content="テストタスク3",
                status="in_progress",
                priority="low",
                created_at=current_time,
                updated_at=current_time,
                source_file="test3.md",
                source_section="セクション3"
            )
        ]

    def test_initialization(self, temp_dir):
        """TodoManagerの初期化テスト"""
        persist_dir = os.path.join(temp_dir, 'storage')

        todo_manager = TodoManager(persist_dir)

        assert todo_manager.persist_dir == persist_dir
        assert todo_manager.todo_file_path == os.path.join(
            persist_dir, "todos.json")
        assert isinstance(todo_manager.todos, list)
        assert len(todo_manager.todos) == 0

    def test_todo_creation(self, todo_manager):
        """TODO項目の作成テスト"""
        content = "新しいテストタスク"
        priority = "high"
        source_file = "test.md"
        source_section = "テストセクション"

        todo = todo_manager.add_todo(
            content, priority, source_file, source_section)

        assert todo.content == content
        assert todo.priority == priority
        assert todo.status == "pending"
        assert todo.source_file == source_file
        assert todo.source_section == source_section
        assert todo.id is not None
        assert len(todo_manager.todos) == 1

    def test_todo_update(self, todo_manager, sample_todo_items):
        """TODO項目の更新テスト"""
        todo_manager.todos = sample_todo_items.copy()

        # テスト対象のTODOを更新
        updated_todo = todo_manager.update_todo(
            "test1",
            status="in_progress",
            priority="medium"
        )

        assert updated_todo is not None
        assert updated_todo.status == "in_progress"
        assert updated_todo.priority == "medium"
        assert updated_todo.content == "テストタスク1"

        # 存在しないIDで更新
        result = todo_manager.update_todo("nonexistent", status="completed")
        assert result is None

    def test_todo_deletion(self, todo_manager, sample_todo_items):
        """TODO項目の削除テスト"""
        todo_manager.todos = sample_todo_items.copy()
        initial_count = len(todo_manager.todos)

        # 削除実行
        success = todo_manager.delete_todo("test1")

        assert success is True
        assert len(todo_manager.todos) == initial_count - 1

        # 存在しないIDの削除
        success = todo_manager.delete_todo("nonexistent")
        assert success is False

    def test_get_todos_by_status(self, todo_manager, sample_todo_items):
        """ステータス別TODO取得テスト"""
        todo_manager.todos = sample_todo_items.copy()

        # 全TODO取得
        all_todos = todo_manager.get_todos()
        assert len(all_todos) == 3

        # pending状態のTODO取得
        pending_todos = todo_manager.get_todos("pending")
        assert len(pending_todos) == 1
        assert pending_todos[0].id == "test1"

        # completed状態のTODO取得
        completed_todos = todo_manager.get_todos("completed")
        assert len(completed_todos) == 1
        assert completed_todos[0].id == "test2"

        # in_progress状態のTODO取得
        in_progress_todos = todo_manager.get_todos("in_progress")
        assert len(in_progress_todos) == 1
        assert in_progress_todos[0].id == "test3"

    def test_todo_extraction_from_text(self, todo_manager):
        """テキストからのTODO抽出テスト"""
        test_text = """
        TODO: この機能を実装する
        FIXME: このバグを修正
        - [ ] チェックボックスタスク
        NOTE: 重要な情報
        BUG: エラーを修正する必要がある
        HACK: 一時的な解決策
        XXX: 要確認事項
        * [ ] 別のチェックボックス
        """

        todos = todo_manager.extract_todos_from_text(
            test_text,
            "test.md",
            "テストセクション"
        )

        assert len(todos) >= 6  # 主要なパターンが検出される

        # TODO項目の内容チェック
        todo_contents = [todo.content for todo in todos]
        assert any("実装" in content for content in todo_contents)
        assert any("修正" in content for content in todo_contents)
        assert any("チェックボックス" in content for content in todo_contents)

        # 優先度の推定チェック
        priorities = [todo.priority for todo in todos]
        assert "medium" in priorities  # デフォルト優先度

    def test_todo_extraction_with_priority_detection(self, todo_manager):
        """優先度検出付きTODO抽出テスト"""
        high_priority_text = "TODO: urgent この機能を急いで実装する"
        low_priority_text = "TODO: later この機能は後で実装する"

        high_todos = todo_manager.extract_todos_from_text(
            high_priority_text, "test.md", "高優先度"
        )
        low_todos = todo_manager.extract_todos_from_text(
            low_priority_text, "test.md", "低優先度"
        )

        assert len(high_todos) == 1
        assert high_todos[0].priority == "high"

        assert len(low_todos) == 1
        assert low_todos[0].priority == "low"

    def test_aggregate_todos_by_date(self, todo_manager, sample_todo_items):
        """日付別TODO集約テスト"""
        todo_manager.todos = sample_todo_items.copy()

        aggregated = todo_manager.aggregate_todos_by_date()

        # 今日の日付でTODOが集約されている
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in aggregated
        assert len(aggregated[today]) == 3  # 全てのTODOが今日作成された

    def test_get_overdue_todos(self, todo_manager, sample_todo_items):
        """期限切れTODO取得テスト"""
        todo_manager.todos = sample_todo_items.copy()

        overdue_todos = todo_manager.get_overdue_todos()

        # 期限切れのTODOは1つ（test2は期限が昨日でcompletedではない状態にする）
        # test2のstatusをpendingに変更してテスト
        for todo in todo_manager.todos:
            if todo.id == "test2":
                todo.status = "pending"

        overdue_todos = todo_manager.get_overdue_todos()
        assert len(overdue_todos) >= 1
        assert any(todo.id == "test2" for todo in overdue_todos)

    def test_add_extracted_todos_with_duplication_check(self, todo_manager):
        """重複チェック付きTODO追加テスト"""
        # 初期TODO作成
        initial_todo = todo_manager.add_todo(
            "テストタスク", "medium", "test.md", "セクション")

        # 同じ内容のTODOを抽出したリストを作成
        extracted_todos = [
            TodoItem(
                id=initial_todo.id,  # 同じID
                content="テストタスク",
                status="pending",
                priority="medium",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                source_file="test.md",
                source_section="セクション"
            ),
            TodoItem(
                id="new_todo",
                content="新しいタスク",
                status="pending",
                priority="low",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                source_file="test2.md",
                source_section="セクション2"
            )
        ]

        added_count = todo_manager.add_extracted_todos(extracted_todos)

        # 重複したTODOは追加されず、新しいTODOのみ追加される
        assert added_count == 1
        assert len(todo_manager.todos) == 2

    def test_save_and_load_todos(self, todo_manager, sample_todo_items):
        """TODO保存・読み込みテスト"""
        # TODOを設定
        todo_manager.todos = sample_todo_items.copy()
        todo_manager._save_todos()

        # 新しいインスタンスで読み込み
        new_todo_manager = TodoManager(todo_manager.persist_dir)

        assert len(new_todo_manager.todos) == 3

        # データの整合性チェック
        loaded_todo = next(
            todo for todo in new_todo_manager.todos if todo.id == "test1")
        assert loaded_todo.content == "テストタスク1"
        assert loaded_todo.status == "pending"
        assert loaded_todo.priority == "high"

    def test_todo_item_post_init(self):
        """TodoItemのpost_init処理テスト"""
        # tagsがNoneの場合の初期化
        todo = TodoItem(
            id="test",
            content="テスト",
            status="pending",
            priority="medium",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            source_file="test.md",
            source_section="セクション"
        )

        assert todo.tags == []

        # tagsが指定されている場合
        todo_with_tags = TodoItem(
            id="test2",
            content="テスト2",
            status="pending",
            priority="medium",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            source_file="test.md",
            source_section="セクション",
            tags=["tag1", "tag2"]
        )

        assert todo_with_tags.tags == ["tag1", "tag2"]

    def test_empty_todo_extraction(self, todo_manager):
        """空のテキストからのTODO抽出テスト"""
        empty_text = ""
        no_todo_text = "これは普通のテキストです。"

        todos_empty = todo_manager.extract_todos_from_text(
            empty_text, "test.md", "セクション"
        )
        todos_no_todo = todo_manager.extract_todos_from_text(
            no_todo_text, "test.md", "セクション"
        )

        assert len(todos_empty) == 0
        assert len(todos_no_todo) == 0

    def test_short_todo_filtering(self, todo_manager):
        """短すぎるTODO項目のフィルタリングテスト"""
        text_with_short_todo = """
        TODO: ab
        TODO: これは十分な長さのタスクです
        """

        todos = todo_manager.extract_todos_from_text(
            text_with_short_todo, "test.md", "セクション"
        )

        # 短すぎるTODO（3文字以下）は除外される
        assert len(todos) == 1
        assert "十分な長さ" in todos[0].content

    def test_invalid_due_date_handling(self, todo_manager, sample_todo_items):
        """無効な期限日付の処理テスト"""
        # 無効な日付形式のTODOを追加
        invalid_todo = TodoItem(
            id="invalid_date",
            content="無効な日付のタスク",
            status="pending",
            priority="medium",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            source_file="test.md",
            source_section="セクション",
            due_date="invalid-date-format"
        )

        todo_manager.todos = sample_todo_items + [invalid_todo]

        # 期限切れTODO取得時にエラーが発生しないことを確認
        overdue_todos = todo_manager.get_overdue_todos()
        # 無効な日付のTODOは期限切れリストに含まれない
        assert not any(todo.id == "invalid_date" for todo in overdue_todos)
