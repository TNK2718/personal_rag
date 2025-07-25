import os
import json
import hashlib
import re
from typing import Optional, List, Dict
from dataclasses import dataclass, asdict, field
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
    related_chunk_ids: List[str] = field(default_factory=list)

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
            r'\b(?:TODO|Todo|todo)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:BUG|Bug|bug)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:HACK|Hack|hack)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:NOTE|Note|note)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:XXX|xxx)\s*:?\s*(.+?)(?:\n|$)',
            r'- \[ \]\s*(.+?)(?:\n|$)',  # Markdownチェックボックス
            r'- \[x\]\s*(.+?)(?:\n|$)',  # 完了チェックボックス
            r'^\s*[\*\-]\s*(?:TODO|Todo|todo)\s*:?\s*(.+?)(?:\n|$)',  # リストアイテムのTODO
            r'^\s*[\*\-]\s*(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?:\n|$)',  # リストアイテムのFIXME
            r'^\s*[\*\-]\s*(?:BUG|Bug|bug)\s*:?\s*(.+?)(?:\n|$)',  # リストアイテムのBUG
            r'^\s*[\*\-]\s*(?:NOTE|Note|note)\s*:?\s*(.+?)(?:\n|$)',  # リストアイテムのNOTE
            r'^\s*[\*\-]\s*(?:HACK|Hack|hack)\s*:?\s*(.+?)(?:\n|$)',  # リストアイテムのHACK
            r'^\s*[\*\-]\s*(?:XXX|xxx)\s*:?\s*(.+?)(?:\n|$)'  # リストアイテムのXXX
        ]

        current_time = datetime.now().isoformat()

        for pattern in patterns:
            matches = re.finditer(pattern, text,
                                  re.MULTILINE | re.IGNORECASE)
            for match in matches:
                content = match.group(1).strip()
                # リストアイテムの場合は最初の'*'や'-'を削除
                if content.startswith('*') or content.startswith('-'):
                    content = content[1:].strip()
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

                    # 既存のTODOを確認して作成日を保持
                    existing_todo = None
                    for existing in self.todos:
                        if existing.id == todo_id:
                            existing_todo = existing
                            break
                    
                    # 作成日と更新日を決定
                    if existing_todo:
                        created_at = existing_todo.created_at
                        updated_at = current_time
                    else:
                        created_at = current_time
                        updated_at = current_time

                    todo = TodoItem(
                        id=todo_id,
                        content=content,
                        status="pending",
                        priority=priority,
                        created_at=created_at,
                        updated_at=updated_at,
                        source_file=source_file,
                        source_section=source_section
                    )
                    todos.append(todo)

        # 重複を除去（コンテンツが同じまたは類似のTODOを削除）
        unique_todos = []
        seen_contents = set()
        for todo in todos:
            # TODO:プレフィックスを削除して比較
            normalized_content = todo.content.replace('TODO:', '').replace('Todo:', '').replace('todo:', '').strip()
            if normalized_content not in seen_contents:
                unique_todos.append(todo)
                seen_contents.add(normalized_content)

        # 締切日を抽出して設定
        for todo in unique_todos:
            extracted_due_date = self._extract_due_date_from_text(todo.content)
            if extracted_due_date and not todo.due_date:
                todo.due_date = extracted_due_date

        return unique_todos

    def extract_todos_with_chunk_ids(self, text: str, source_file: str, source_section: str) -> List[TodoItem]:
        """
        テキストからTODO項目を抽出し、チャンクIDも含める
        
        Args:
            text: 抽出するテキスト
            source_file: ソースファイル
            source_section: ソースセクション
            
        Returns:
            チャンクID付きTODO項目のリスト
        """
        todos = []
        
        # 基本的なTODO抽出
        base_todos = self.extract_todos_from_text(text, source_file, source_section)
        
        # 各TODOにチャンクIDを追加
        for todo in base_todos:
            # チャンクIDを生成（セクションIDは仮で1を使用）
            chunk_id = f"{source_file}:section_1:chunk_0"
            todo.related_chunk_ids = [chunk_id]
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
        
        # 内容ベースの重複チェック用に正規化された内容をセットで保持
        existing_normalized_contents = set()
        for existing_todo in self.todos:
            normalized = self._normalize_content_for_dedup(existing_todo.content)
            existing_normalized_contents.add(normalized)

        for todo in extracted_todos:
            # IDベースのチェック
            if todo.id in existing_ids:
                continue
                
            # 内容ベースのチェック
            normalized_content = self._normalize_content_for_dedup(todo.content)
            if normalized_content in existing_normalized_contents:
                continue
                
            # 重複していない場合は追加
            self.todos.append(todo)
            existing_ids.add(todo.id)
            existing_normalized_contents.add(normalized_content)
            added_count += 1

        if added_count > 0:
            self._save_todos()

        return added_count
    
    def _normalize_content_for_dedup(self, content: str) -> str:
        """
        重複チェック用にTODO内容を正規化する
        
        Args:
            content: TODO内容
            
        Returns:
            正規化されたTODO内容
        """
        import re
        
        # 基本的な前処理
        normalized = content.strip()
        
        # 各種プレフィックスを段階的に除去（複数回適用で複合パターンに対応）
        prefixes_to_remove = [
            r'^[\*\-\+]\s*\[\s*[x ]?\s*\]\s*',  # リスト付きマークダウンチェックボックス: - [ ], * [x], + []
            r'^-\s*\[\s*[x ]?\s*\]\s*',         # マークダウンチェックボックス: - [ ], - [x]
            r'^\[\s*[x ]?\s*\]\s*',             # 単体チェックボックス: [ ], [x]
            r'^[\*\-\+]\s*',                    # リストマーカー: -, *, +
            r'^\d+\.\s*',                       # 番号付きリスト: 1., 2.
            r'(?i)^(TODO|FIXME|BUG|HACK|NOTE|XXX)\s*:?\s*',  # TODOプレフィックス
        ]
        
        # 正規表現を使って順次プレフィックスを除去（複数回実行で複合パターンに対応）
        for _ in range(2):  # 最大2回実行で複合パターンを処理
            for pattern in prefixes_to_remove:
                before = normalized
                normalized = re.sub(pattern, '', normalized).strip()
                if before != normalized:
                    break  # パターンが適用されたら次のループへ
        
        # 句読点を除去
        punctuation_pattern = r'[。、！？．，!?\.;:…]+$'
        normalized = re.sub(punctuation_pattern, '', normalized)
        
        # 空白文字を統一
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        normalized = normalized.replace('　', ' ')
        
        return normalized.lower().strip()

    def _extract_due_date_from_text(self, text: str) -> Optional[str]:
        """
        テキストから締切日を抽出する
        
        Args:
            text: 抽出対象のテキスト
            
        Returns:
            抽出された締切日（ISO形式）またはNone
        """
        import re
        from datetime import datetime, timedelta
        
        # 日付パターンの定義
        date_patterns = [
            # 明示的な日付形式
            r'(?:締切|期限|until|by|due)\s*[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',  # 締切: 2024-12-31, by 2024/12/31
            r'(?:締切|期限|until|by|due)\s*[:：]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',  # 締切: 31-12-2024, by 31/12/2024
            r'(?:締切|期限|until|by|due)\s*[:：]?\s*(\d{1,2}月\d{1,2}日)',  # 締切: 12月31日
            r'(?:締切|期限|until|by|due)\s*[:：]?\s*(\d{4}年\d{1,2}月\d{1,2}日)',  # 締切: 2024年12月31日
            # 日付＋まで の形式
            r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})\s*まで',  # 2024-12-31まで, 2024/12/31まで
            r'(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s*まで',  # 31-12-2024まで, 31/12/2024まで
            r'(\d{1,2}月\d{1,2}日)\s*まで',  # 12月31日まで
            r'(\d{4}年\d{1,2}月\d{1,2}日)\s*まで',  # 2024年12月31日まで
            
            # 相対的な日付表現
            r'(?:明日|tomorrow)',  # 明日
            r'(?:今週|this week)',  # 今週
            r'(?:来週|next week)',  # 来週
            r'(?:今月|this month)',  # 今月
            r'(?:来月|next month)',  # 来月
            r'(\d+)日後',  # N日後
            r'(\d+)週間後',  # N週間後
            
            # 曜日指定
            r'(?:月曜|火曜|水曜|木曜|金曜|土曜|日曜)(?:日)?',
            r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)',
        ]
        
        today = datetime.now().date()
        
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                matched_text = match.group(0).lower()
                
                try:
                    # 明示的な日付形式の処理
                    if match.groups():
                        date_str = match.group(1)
                        
                        # YYYY-MM-DD または YYYY/MM/DD 形式
                        if re.match(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', date_str):
                            date_str = date_str.replace('/', '-')
                            return date_str
                        
                        # DD-MM-YYYY または DD/MM/YYYY 形式
                        elif re.match(r'\d{1,2}[-/]\d{1,2}[-/]\d{4}', date_str):
                            parts = re.split('[-/]', date_str)
                            return f"{parts[2]}-{parts[1]:0>2}-{parts[0]:0>2}"
                        
                        # N月N日 形式
                        elif '月' in date_str and '日' in date_str:
                            month_match = re.search(r'(\d{1,2})月', date_str)
                            day_match = re.search(r'(\d{1,2})日', date_str)
                            if month_match and day_match:
                                month = int(month_match.group(1))
                                day = int(day_match.group(1))
                                year = today.year
                                # 指定された月日が今年の過去の場合は来年とする
                                target_date = datetime(year, month, day).date()
                                if target_date < today:
                                    year += 1
                                return f"{year}-{month:02d}-{day:02d}"
                        
                        # YYYY年N月N日 形式
                        elif '年' in date_str:
                            year_match = re.search(r'(\d{4})年', date_str)
                            month_match = re.search(r'(\d{1,2})月', date_str)
                            day_match = re.search(r'(\d{1,2})日', date_str)
                            if year_match and month_match and day_match:
                                year = int(year_match.group(1))
                                month = int(month_match.group(1))
                                day = int(day_match.group(1))
                                return f"{year}-{month:02d}-{day:02d}"
                        
                        # N日後
                        elif '日後' in matched_text:
                            days = int(match.group(1))
                            target_date = today + timedelta(days=days)
                            return target_date.isoformat()
                        
                        # N週間後
                        elif '週間後' in matched_text:
                            weeks = int(match.group(1))
                            target_date = today + timedelta(weeks=weeks)
                            return target_date.isoformat()
                    
                    # 相対的な日付表現の処理
                    elif '明日' in matched_text or 'tomorrow' in matched_text:
                        target_date = today + timedelta(days=1)
                        return target_date.isoformat()
                    
                    elif '今週' in matched_text or 'this week' in matched_text:
                        # 今週の金曜日を設定
                        days_until_friday = (4 - today.weekday()) % 7
                        if days_until_friday == 0 and today.weekday() == 4:  # 今日が金曜日
                            days_until_friday = 7
                        target_date = today + timedelta(days=days_until_friday)
                        return target_date.isoformat()
                    
                    elif '来週' in matched_text or 'next week' in matched_text:
                        # 来週の金曜日を設定
                        days_until_next_friday = ((4 - today.weekday()) % 7) + 7
                        target_date = today + timedelta(days=days_until_next_friday)
                        return target_date.isoformat()
                    
                    elif '今月' in matched_text or 'this month' in matched_text:
                        # 今月末を設定
                        if today.month == 12:
                            target_date = datetime(today.year + 1, 1, 1).date() - timedelta(days=1)
                        else:
                            target_date = datetime(today.year, today.month + 1, 1).date() - timedelta(days=1)
                        return target_date.isoformat()
                    
                    elif '来月' in matched_text or 'next month' in matched_text:
                        # 来月末を設定
                        if today.month == 11:
                            target_date = datetime(today.year + 1, 1, 1).date() - timedelta(days=1)
                        elif today.month == 12:
                            target_date = datetime(today.year + 1, 2, 1).date() - timedelta(days=1)
                        else:
                            target_date = datetime(today.year, today.month + 2, 1).date() - timedelta(days=1)
                        return target_date.isoformat()
                
                except (ValueError, IndexError):
                    continue
        
        return None
