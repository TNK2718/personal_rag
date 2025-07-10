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

        # メソッドもMockオブジェクトに置き換え
        rag_system.query = Mock()
        rag_system.get_todos = Mock()
        rag_system.add_todo = Mock()
        rag_system.update_todo = Mock()
        rag_system.delete_todo = Mock()
        rag_system.aggregate_todos_by_date = Mock()
        rag_system.extract_todos_from_documents = Mock()
        rag_system.get_overdue_todos = Mock()

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
