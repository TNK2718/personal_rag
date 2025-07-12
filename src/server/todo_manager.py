import os
import json
import hashlib
import re
from typing import Optional, List, Dict
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class TodoItem:
    """TODO項目を表すデータクラス"""
    id: str
    content: str
    status: str  # "pending", "in_progress", "completed"
    priority: str  # "high", "medium", "low"
    created_at: str
    updated_at: str
    source_file: str
    source_section: str
    due_date: Optional[str] = None
    tags: Optional[List[str]] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class TodoManager:
    """TODO項目の管理を担当するクラス"""

    def __init__(self, persist_dir: str, todo_file: str = "todos.json"):
        """
        TodoManagerの初期化

        Args:
            persist_dir: 永続化ディレクトリ
            todo_file: TODOファイル名
        """
        self.persist_dir = persist_dir
        self.todo_file_path = os.path.join(persist_dir, todo_file)
        self.todos: List[TodoItem] = self._load_todos()

    def _load_todos(self) -> List[TodoItem]:
        """保存されているTODOリストを読み込む"""
        if os.path.exists(self.todo_file_path):
            with open(self.todo_file_path, 'r', encoding='utf-8') as f:
                todo_data = json.load(f)
                return [TodoItem(**item) for item in todo_data]
        return []

    def _save_todos(self) -> None:
        """TODOリストを保存する"""
        os.makedirs(self.persist_dir, exist_ok=True)
        with open(self.todo_file_path, 'w', encoding='utf-8') as f:
            todo_data = [asdict(todo) for todo in self.todos]
            json.dump(todo_data, f, ensure_ascii=False, indent=2)

    def extract_todos_from_text(
        self, text: str, source_file: str, source_section: str
    ) -> List[TodoItem]:
        """テキストからTODO項目を抽出する"""
        todos = []

        # 様々なTODOパターンを検出
        patterns = [
            r'(?:TODO|Todo|todo)\s*:?\s*(.+?)(?:\n|$)',
            r'(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?:\n|$)',
            r'(?:BUG|Bug|bug)\s*:?\s*(.+?)(?:\n|$)',
            r'(?:HACK|Hack|hack)\s*:?\s*(.+?)(?:\n|$)',
            r'(?:NOTE|Note|note)\s*:?\s*(.+?)(?:\n|$)',
            r'(?:XXX|xxx)\s*:?\s*(.+?)(?:\n|$)',
            r'- \[ \]\s*(.+?)(?:\n|$)',  # Markdownチェックボックス
            r'\* \[ \]\s*(.+?)(?:\n|$)'
        ]

        current_time = datetime.now().isoformat()

        for pattern in patterns:
            matches = re.finditer(pattern, text,
                                  re.MULTILINE | re.IGNORECASE)
            for match in matches:
                content = match.group(1).strip()
                if content and len(content) > 3:  # 短すぎるものは除外
                    # 優先度を推定
                    priority = "medium"
                    urgent_words = ['urgent', '急', '緊急', 'asap']
                    later_words = ['later', '後で', '将来']
                    if any(word in content.lower() for word in urgent_words):
                        priority = "high"
                    elif any(word in content.lower() for word in later_words):
                        priority = "low"

                    # IDを生成
                    source_key = f"{source_file}:{source_section}:{content}"
                    todo_id = hashlib.md5(source_key.encode()).hexdigest()[:8]

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

    def get_todos(self, status: Optional[str] = None) -> List[TodoItem]:
        """
        TODOリストを取得する

        Args:
            status: フィルタするステータス（Noneの場合は全て）

        Returns:
            TODO項目のリスト
        """
        if status:
            return [todo for todo in self.todos if todo.status == status]
        return self.todos

    def add_todo(
        self, content: str, priority: str = "medium",
        source_file: str = "manual", source_section: str = "manual"
    ) -> TodoItem:
        """
        新しいTODOを追加する

        Args:
            content: TODO内容
            priority: 優先度
            source_file: ソースファイル
            source_section: ソースセクション

        Returns:
            作成されたTODO項目
        """
        current_time = datetime.now().isoformat()

        # IDを生成
        source_key = f"{source_file}:{source_section}:{content}"
        todo_id = hashlib.md5(source_key.encode()).hexdigest()[:8]

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

        self.todos.append(todo)
        self._save_todos()

        return todo

    def update_todo(self, todo_id: str, **kwargs) -> Optional[TodoItem]:
        """
        TODOを更新する

        Args:
            todo_id: TODO ID
            **kwargs: 更新する属性

        Returns:
            更新されたTODO項目（見つからない場合はNone）
        """
        for todo in self.todos:
            if todo.id == todo_id:
                for key, value in kwargs.items():
                    if hasattr(todo, key):
                        setattr(todo, key, value)
                todo.updated_at = datetime.now().isoformat()
                self._save_todos()
                return todo
        return None

    def delete_todo(self, todo_id: str) -> bool:
        """
        TODOを削除する

        Args:
            todo_id: TODO ID

        Returns:
            削除成功の場合True
        """
        for i, todo in enumerate(self.todos):
            if todo.id == todo_id:
                del self.todos[i]
                self._save_todos()
                return True
        return False

    def aggregate_todos_by_date(self) -> Dict[str, List[TodoItem]]:
        """
        日付別にTODOを集約する

        Returns:
            日付をキーとしたTODO項目の辞書
        """
        aggregated = {}
        for todo in self.todos:
            date = todo.created_at.split('T')[0]  # 日付部分のみ
            if date not in aggregated:
                aggregated[date] = []
            aggregated[date].append(todo)
        return aggregated

    def get_overdue_todos(self) -> List[TodoItem]:
        """
        期限切れのTODOを取得する

        Returns:
            期限切れのTODO項目のリスト
        """
        overdue_todos = []
        current_date = datetime.now().date()

        for todo in self.todos:
            if todo.due_date and todo.status not in ["completed", "cancelled"]:
                try:
                    due_date = datetime.fromisoformat(todo.due_date).date()
                    if due_date < current_date:
                        overdue_todos.append(todo)
                except ValueError:
                    # 日付形式が不正な場合はスキップ
                    continue

        return overdue_todos

    def add_extracted_todos(self, extracted_todos: List[TodoItem]) -> int:
        """
        抽出されたTODOを追加する（重複チェック付き）

        Args:
            extracted_todos: 抽出されたTODO項目のリスト

        Returns:
            追加されたTODO数
        """
        added_count = 0
        existing_ids = {todo.id for todo in self.todos}

        for todo in extracted_todos:
            if todo.id not in existing_ids:
                self.todos.append(todo)
                added_count += 1

        if added_count > 0:
            self._save_todos()

        return added_count
