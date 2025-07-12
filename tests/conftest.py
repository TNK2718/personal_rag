"""テスト設定ファイル - リファクタリング後の構造に対応"""
from src.server.markdown_parser import MarkdownSection
from src.server.todo_manager import TodoItem
import os
import tempfile
import shutil
import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
from typing import Dict, Any, Generator
from datetime import datetime, timedelta

# プロジェクトルートをsys.pathに追加
project_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'src', 'server'))

# インポート


@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    """一時ディレクトリを作成し、テスト後に削除"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_todo_items() -> list[TodoItem]:
    """サンプルTODO項目を生成"""
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
        )
    ]


@pytest.fixture
def sample_markdown_content() -> str:
    """サンプルMarkdownコンテンツ"""
    return """# メインタイトル

これはメインセクションのコンテンツです。

## サブセクション1

サブセクション1のコンテンツ。
TODO: この機能を実装する

### サブサブセクション

さらに深いレベルのコンテンツ。

## サブセクション2

- [ ] チェックボックス項目1
- [x] 完了した項目
- [ ] チェックボックス項目2

FIXME: このバグを修正する

```python
print("コードブロック")
```

[リンクテキスト](https://example.com)
![画像](image.png)
"""


@pytest.fixture
def sample_markdown_sections() -> list[MarkdownSection]:
    """サンプルMarkdownセクション"""
    return [
        MarkdownSection(
            header="メインタイトル",
            content="これはメインセクションのコンテンツです。",
            level=1
        ),
        MarkdownSection(
            header="サブセクション1",
            content="サブセクション1のコンテンツ。\nTODO: この機能を実装する",
            level=2
        ),
        MarkdownSection(
            header="サブサブセクション",
            content="さらに深いレベルのコンテンツ。",
            level=3
        )
    ]


@pytest.fixture
def mock_query_response() -> Dict[str, Any]:
    """モッククエリレスポンス"""
    return {
        'answer': 'これはテスト用の回答です。',
        'sources': [
            {
                'header': 'テストヘッダー',
                'content': 'テストコンテンツ',
                'doc_id': 'test.md',
                'file_name': 'test',
                'folder_name': 'project',
                'section_id': 1,
                'level': 2,
                'type': 'content',
                'score': 0.95
            }
        ]
    }


@pytest.fixture
def mock_documents():
    """モックドキュメント"""
    mock_doc1 = Mock()
    mock_doc1.text = "# ドキュメント1\n\nコンテンツ1"
    mock_doc1.metadata = {"source": "doc1.md"}

    mock_doc2 = Mock()
    mock_doc2.text = "# ドキュメント2\n\nコンテンツ2"
    mock_doc2.metadata = {"source": "doc2.md"}

    return [mock_doc1, mock_doc2]


@pytest.fixture
def mock_external_dependencies():
    """外部依存関係（LlamaIndex、FAISS、Ollama）をモック"""
    with patch('src.server.index_manager.Ollama') as mock_ollama, \
            patch('src.server.index_manager.OllamaEmbedding') as mock_embed, \
            patch('src.server.index_manager.Settings') as mock_settings, \
            patch('src.server.index_manager.faiss') as mock_faiss, \
            patch('src.server.index_manager.VectorStoreIndex') as mock_index, \
            patch('src.server.index_manager.FaissVectorStore') as mock_store, \
            patch('src.server.index_manager.StorageContext') as mock_context, \
            patch('src.server.index_manager.load_index_from_storage') as mock_load, \
            patch('src.server.document_manager.SimpleDirectoryReader') as mock_reader:

        # FAISSインデックスのモック
        mock_faiss_instance = MagicMock()
        mock_faiss_instance.ntotal = 0
        mock_faiss.IndexFlatL2.return_value = mock_faiss_instance
        mock_faiss.read_index.return_value = mock_faiss_instance

        # VectorStoreIndexのモック
        mock_index_instance = MagicMock()
        mock_index.return_value = mock_index_instance
        mock_load.return_value = mock_index_instance

        # StorageContextのモック
        mock_context_instance = MagicMock()
        mock_context.from_defaults.return_value = mock_context_instance

        # SimpleDirectoryReaderのモック
        mock_reader.return_value.load_data.return_value = []

        yield {
            'ollama': mock_ollama,
            'embed': mock_embed,
            'settings': mock_settings,
            'faiss': mock_faiss,
            'index': mock_index,
            'store': mock_store,
            'context': mock_context,
            'load': mock_load,
            'reader': mock_reader,
            'faiss_instance': mock_faiss_instance,
            'index_instance': mock_index_instance
        }


# 各クラス用のフィクスチャー

@pytest.fixture
def document_manager(temp_dir):
    """DocumentManagerのインスタンス"""
    from src.server.document_manager import DocumentManager
    data_dir = os.path.join(temp_dir, 'data')
    persist_dir = os.path.join(temp_dir, 'storage')
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(persist_dir, exist_ok=True)
    return DocumentManager(data_dir, persist_dir)


@pytest.fixture
def todo_manager(temp_dir):
    """TodoManagerのインスタンス"""
    from src.server.todo_manager import TodoManager
    persist_dir = os.path.join(temp_dir, 'storage')
    os.makedirs(persist_dir, exist_ok=True)
    return TodoManager(persist_dir)


@pytest.fixture
def markdown_parser():
    """MarkdownParserのインスタンス"""
    from src.server.markdown_parser import MarkdownParser
    return MarkdownParser()


@pytest.fixture
def text_chunker():
    """TextChunkerのインスタンス"""
    from src.server.text_chunker import TextChunker
    return TextChunker(chunk_size=100, chunk_overlap=20)


@pytest.fixture
def index_manager(temp_dir, mock_external_dependencies):
    """IndexManagerのインスタンス"""
    from src.server.index_manager import IndexManager
    persist_dir = os.path.join(temp_dir, 'storage')
    os.makedirs(persist_dir, exist_ok=True)
    return IndexManager(persist_dir, embedding_dim=768)


@pytest.fixture
def rag_system(temp_dir, mock_external_dependencies):
    """リファクタリング後のRAGSystemインスタンス"""
    from src.server.rag_system import RAGSystem
    data_dir = os.path.join(temp_dir, 'data')
    persist_dir = os.path.join(temp_dir, 'storage')
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(persist_dir, exist_ok=True)

    return RAGSystem(
        persist_dir=persist_dir,
        data_dir=data_dir,
        embedding_dim=768,
        chunk_size=100,
        chunk_overlap=20
    )


# 後方互換性のための古いフィクスチャー（必要に応じて削除）

@pytest.fixture
def mock_rag_system(temp_dir):
    """
    後方互換性のための古いRAGSystemモック

    注意: 新しいテストでは rag_system フィクスチャーを使用してください
    """
    # 簡単なモックオブジェクトを返す
    mock_system = Mock()
    mock_system.persist_dir = os.path.join(temp_dir, 'storage')
    mock_system.data_dir = os.path.join(temp_dir, 'data')
    mock_system.embedding_dim = 768
    mock_system.todos = []
    mock_system.document_hashes = {}

    # 基本的なメソッドをモック
    mock_system.add_todo.return_value = Mock(id="test_id", content="test")
    mock_system.get_todos.return_value = []
    mock_system.update_todo.return_value = None
    mock_system.delete_todo.return_value = False
    mock_system.query.return_value = {'answer': 'test', 'sources': []}

    return mock_system


# テスト用ヘルパー関数

def create_test_file(directory: str, filename: str, content: str) -> str:
    """テスト用ファイルを作成"""
    os.makedirs(directory, exist_ok=True)
    file_path = os.path.join(directory, filename)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return file_path


def create_test_todo(
    todo_id: str = "test_id",
    content: str = "テストタスク",
    status: str = "pending",
    priority: str = "medium"
) -> TodoItem:
    """テスト用TODOアイテムを作成"""
    current_time = datetime.now().isoformat()
    return TodoItem(
        id=todo_id,
        content=content,
        status=status,
        priority=priority,
        created_at=current_time,
        updated_at=current_time,
        source_file="test.md",
        source_section="テストセクション"
    )


def create_test_markdown_section(
    header: str = "テストヘッダー",
    content: str = "テストコンテンツ",
    level: int = 1
) -> MarkdownSection:
    """テスト用Markdownセクションを作成"""
    return MarkdownSection(
        header=header,
        content=content,
        level=level
    )


# pytest設定

def pytest_configure(config):
    """pytest設定"""
    # テスト環境変数を設定
    os.environ['IS_TESTING'] = 'true'


def pytest_unconfigure(config):
    """pytest終了時の処理"""
    # テスト環境変数をクリア
    if 'IS_TESTING' in os.environ:
        del os.environ['IS_TESTING']
