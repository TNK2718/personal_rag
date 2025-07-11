from src.server.rag_system import RAGSystem, TodoItem, MarkdownSection
import os
import tempfile
import shutil
import pytest
from unittest.mock import Mock, patch
import sys
from typing import Dict, Any, Generator

# プロジェクトルートをsys.pathに追加
project_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src', 'server'))


@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    """一時ディレクトリを作成し、テスト後に削除"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_rag_system(temp_dir):
    """モックRAGシステムインスタンス"""
    # より包括的なモック設定
    with patch('src.server.rag_system.OllamaEmbedding'), \
            patch('src.server.rag_system.Ollama'), \
            patch('src.server.rag_system.faiss'), \
            patch('src.server.rag_system.VectorStoreIndex'), \
            patch('src.server.rag_system.Settings'), \
            patch.dict('os.environ', {'IS_TESTING': 'true'}):

        data_dir = os.path.join(temp_dir, 'data')
        persist_dir = os.path.join(temp_dir, 'storage')
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(persist_dir, exist_ok=True)

        # RAGSystemの__init__をパッチして直接インスタンスを作成
        rag_system = object.__new__(RAGSystem)

        # 必要な属性を手動で設定
        rag_system.persist_dir = persist_dir
        rag_system.data_dir = data_dir
        rag_system.embedding_dim = 768
        rag_system.faiss_index_path = os.path.join(
            persist_dir, "faiss_index.bin")
        rag_system.hash_file_path = os.path.join(
            persist_dir, "document_hashes.json")
        rag_system.todo_file_path = os.path.join(persist_dir, "todos.json")
        rag_system.document_hashes = {}
        rag_system.todos = []

        # MarkdownItパーサーのモック設定
        rag_system.md_parser = Mock()
        # parseメソッドが返すトークンリストをモック
        mock_tokens = [
            Mock(type='heading_open', tag='h1', level=1),
            Mock(type='inline', content='メインタイトル'),
            Mock(type='heading_close'),
            Mock(type='paragraph_open'),
            Mock(type='inline', content='コンテンツ'),
            Mock(type='paragraph_close')
        ]
        rag_system.md_parser.parse.return_value = mock_tokens

        # モックインデックスを設定
        rag_system.index = Mock()
        mock_retriever = Mock()
        mock_retriever.retrieve.return_value = []  # 空のリストを返す
        rag_system.index.as_retriever.return_value = mock_retriever
        rag_system.index.as_query_engine.return_value = Mock()
        rag_system.llm = Mock()
        rag_system.embed_model = Mock()

        # 実際のメソッドを実装
        # TODO関連のメソッドを実装
        def add_todo(self, content, priority="medium", source_file="manual",
                     source_section="manual"):
            from datetime import datetime
            import uuid
            todo = TodoItem(
                id=str(uuid.uuid4()),
                content=content,
                priority=priority,
                status="pending",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                source_file=source_file,
                source_section=source_section,
                tags=[]
            )
            self.todos.append(todo)
            return todo

        def get_todos(self, status=None):
            if status:
                return [todo for todo in self.todos
                        if todo.status == status]
            return self.todos.copy()

        def update_todo(self, todo_id, **kwargs):
            for todo in self.todos:
                if todo.id == todo_id:
                    for key, value in kwargs.items():
                        if hasattr(todo, key):
                            setattr(todo, key, value)
                    return todo
            return None

        def delete_todo(self, todo_id):
            for i, todo in enumerate(self.todos):
                if todo.id == todo_id:
                    self.todos.pop(i)
                    return True
            return False

        def get_overdue_todos(self):
            from datetime import datetime
            current_time = datetime.now()
            overdue = []
            for todo in self.todos:
                if todo.due_date and todo.status != "completed":
                    due_date = datetime.fromisoformat(todo.due_date)
                    if due_date < current_time:
                        overdue.append(todo)
            return overdue

        def aggregate_todos_by_date(self):
            result = {}
            for todo in self.todos:
                date_key = todo.created_at[:10]  # YYYY-MM-DD
                if date_key not in result:
                    result[date_key] = []
                result[date_key].append(todo)
            return result

        def query(self, query_text):
            return {
                'answer': f'モック回答: {query_text}',
                'sources': []
            }

        def extract_todos_from_documents(self):
            return 0

        # 実際のRAGSystemメソッドをバインド
        from types import MethodType
        rag_system.add_todo = MethodType(add_todo, rag_system)
        rag_system.get_todos = MethodType(get_todos, rag_system)
        rag_system.update_todo = MethodType(update_todo, rag_system)
        rag_system.delete_todo = MethodType(delete_todo, rag_system)
        rag_system.get_overdue_todos = MethodType(
            get_overdue_todos, rag_system)
        rag_system.aggregate_todos_by_date = MethodType(
            aggregate_todos_by_date, rag_system)
        rag_system.query = MethodType(query, rag_system)
        rag_system.extract_todos_from_documents = MethodType(
            extract_todos_from_documents, rag_system)

        # 実際のRAGSystemから必要なメソッドをインポートして設定
        real_rag = RAGSystem.__new__(RAGSystem)

        # プライベートメソッドのバインド（selfが必要）
        def _parse_markdown(self, content):
            return real_rag._parse_markdown.__func__(self, content)

        def _extract_todos_from_text(self, text, source_file, source_section):
            return real_rag._extract_todos_from_text.__func__(
                self, text, source_file, source_section)

        def _calculate_file_hash(self, file_path):
            return real_rag._calculate_file_hash.__func__(self, file_path)

        def _check_document_updates(self):
            return real_rag._check_document_updates.__func__(self)

        def _create_nodes_from_sections(self, sections, doc_id):
            return real_rag._create_nodes_from_sections.__func__(
                self, sections, doc_id)

        # 新しいメソッドの追加
        def _split_text_by_length(self, text, chunk_size=800, overlap=100):
            return real_rag._split_text_by_length.__func__(
                self, text, chunk_size, overlap)

        def _calculate_content_diversity(self, selected_nodes, candidate_node, lambda_param=0.5):
            return real_rag._calculate_content_diversity.__func__(
                self, selected_nodes, candidate_node, lambda_param)

        def _select_diverse_nodes(self, nodes, target_count=3, lambda_param=0.7):
            return real_rag._select_diverse_nodes.__func__(
                self, nodes, target_count, lambda_param)

        rag_system._parse_markdown = MethodType(_parse_markdown, rag_system)
        rag_system._extract_todos_from_text = MethodType(
            _extract_todos_from_text, rag_system)
        rag_system._calculate_file_hash = MethodType(
            _calculate_file_hash, rag_system)
        rag_system._check_document_updates = MethodType(
            _check_document_updates, rag_system)
        rag_system._create_nodes_from_sections = MethodType(
            _create_nodes_from_sections, rag_system)

        # 新しいメソッドのバインド
        rag_system._split_text_by_length = MethodType(
            _split_text_by_length, rag_system)
        rag_system._calculate_content_diversity = MethodType(
            _calculate_content_diversity, rag_system)
        rag_system._select_diverse_nodes = MethodType(
            _select_diverse_nodes, rag_system)

        return rag_system


@pytest.fixture
def sample_markdown_content() -> str:
    """テスト用のMarkdownコンテンツ"""
    return """# メインタイトル

これはメインセクションのコンテンツです。

## サブセクション

TODO: この部分を改善する必要があります
FIXME: バグがあります

- [ ] 実装が必要
- [x] 完了済みタスク

### 詳細セクション

NOTE: 重要な点を記録
"""


@pytest.fixture
def sample_todo_items() -> list[TodoItem]:
    """テスト用のTODO項目"""
    return [
        TodoItem(
            id="test1",
            content="テストタスク1",
            status="pending",
            priority="high",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            source_file="test.md",
            source_section="セクション1",
            tags=["テスト"]
        ),
        TodoItem(
            id="test2",
            content="テストタスク2",
            status="completed",
            priority="medium",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T01:00:00",
            source_file="test.md",
            source_section="セクション2",
            tags=["完了"]
        )
    ]


@pytest.fixture
def sample_markdown_sections() -> list[MarkdownSection]:
    """テスト用のMarkdownセクション"""
    return [
        MarkdownSection(
            header="メインタイトル",
            content="これはメインセクションのコンテンツです。",
            level=1
        ),
        MarkdownSection(
            header="サブセクション",
            content="TODO: この部分を改善する必要があります\nFIXME: バグがあります",
            level=2
        ),
        MarkdownSection(
            header="詳細セクション",
            content="NOTE: 重要な点を記録",
            level=3
        )
    ]


@pytest.fixture
def mock_query_response() -> Dict[str, Any]:
    """モッククエリレスポンス"""
    return {
        'answer': 'これはテスト回答です。',
        'sources': [
            {
                'header': 'テストヘッダー',
                'content': 'テストコンテンツ',
                'doc_id': 'test.md',
                'section_id': 1,
                'level': 2,
                'score': 0.95
            }
        ]
    }


@pytest.fixture
def mock_documents():
    """モックドキュメント"""
    with patch('src.server.rag_system.SimpleDirectoryReader') as mock_reader:
        mock_doc = Mock()
        mock_doc.text = "テストドキュメントの内容"
        mock_doc.doc_id = "test_doc_1"
        mock_reader.return_value.load_data.return_value = [mock_doc]
        yield mock_reader
