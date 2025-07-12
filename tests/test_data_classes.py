"""データクラスとユーティリティのテスト"""
from datetime import datetime

from src.server.rag_system import TodoItem, MarkdownSection


class TestTodoItem:
    """TodoItemデータクラスのテスト"""

    def test_todo_item_creation(self):
        """TodoItem作成テスト"""
        todo = TodoItem(
            id="test_id",
            content="テストコンテンツ",
            status="pending",
            priority="high",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            source_file="project1/test.md",
            source_section="セクション1"
        )

        assert todo.id == "test_id"
        assert todo.content == "テストコンテンツ"
        assert todo.status == "pending"
        assert todo.priority == "high"
        assert todo.created_at == "2024-01-01T00:00:00"
        assert todo.updated_at == "2024-01-01T00:00:00"
        assert todo.source_file == "project1/test.md"
        assert todo.source_section == "セクション1"
        assert todo.due_date is None
        assert todo.tags == []

    def test_todo_item_with_tags(self):
        """タグ付きTodoItem作成テスト"""
        todo = TodoItem(
            id="test_id",
            content="テストコンテンツ",
            status="pending",
            priority="medium",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            source_file="project1/test.md",
            source_section="セクション1",
            tags=["urgent", "bug"]
        )

        assert todo.tags == ["urgent", "bug"]

    def test_todo_item_with_due_date(self):
        """期限付きTodoItem作成テスト"""
        due_date = "2024-01-31T23:59:59"
        todo = TodoItem(
            id="test_id",
            content="期限付きタスク",
            status="pending",
            priority="high",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            source_file="project1/test.md",
            source_section="セクション1",
            due_date=due_date
        )

        assert todo.due_date == due_date

    def test_todo_item_post_init(self):
        """TodoItem __post_init__メソッドのテスト"""
        # tagsがNoneの場合、空リストに設定される
        todo = TodoItem(
            id="test_id",
            content="テストコンテンツ",
            status="pending",
            priority="low",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            source_file="project1/test.md",
            source_section="セクション1",
            tags=None
        )

        assert todo.tags == []


class TestMarkdownSection:
    """MarkdownSectionデータクラスのテスト"""

    def test_markdown_section_creation(self):
        """MarkdownSection作成テスト"""
        section = MarkdownSection(
            header="テストヘッダー",
            content="テストコンテンツの内容",
            level=2
        )

        assert section.header == "テストヘッダー"
        assert section.content == "テストコンテンツの内容"
        assert section.level == 2

    def test_markdown_section_different_levels(self):
        """異なるレベルのMarkdownSectionテスト"""
        sections = [
            MarkdownSection("H1", "コンテンツ1", 1),
            MarkdownSection("H2", "コンテンツ2", 2),
            MarkdownSection("H3", "コンテンツ3", 3),
            MarkdownSection("H4", "コンテンツ4", 4),
            MarkdownSection("H5", "コンテンツ5", 5),
            MarkdownSection("H6", "コンテンツ6", 6),
        ]

        for i, section in enumerate(sections, 1):
            assert section.level == i
            assert section.header == f"H{i}"
            assert section.content == f"コンテンツ{i}"

    def test_markdown_section_empty_content(self):
        """空のコンテンツのMarkdownSectionテスト"""
        section = MarkdownSection(
            header="空のセクション",
            content="",
            level=1
        )

        assert section.header == "空のセクション"
        assert section.content == ""
        assert section.level == 1

    def test_markdown_section_multiline_content(self):
        """複数行コンテンツのMarkdownSectionテスト"""
        multiline_content = """これは複数行の
        コンテンツです。
        
        改行やスペースも
        含まれています。"""

        section = MarkdownSection(
            header="複数行セクション",
            content=multiline_content,
            level=2
        )

        assert section.content == multiline_content
        assert "\n" in section.content
