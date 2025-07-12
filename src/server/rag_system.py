from typing import List, Dict, Optional
from dataclasses import dataclass
from llama_index.core import Document
from llama_index.core.schema import TextNode

# 分割したクラスをインポート
from document_manager import DocumentManager
from todo_manager import TodoManager, TodoItem
from markdown_parser import MarkdownParser, MarkdownSection
from text_chunker import TextChunker
from index_manager import IndexManager


class CustomTextNode(TextNode):
    """get_doc_idメソッドを持つカスタムTextNode"""

    def get_doc_id(self) -> str:
        """ドキュメントIDを取得する"""
        return self.metadata.get("doc_id", self.id_ or "unknown")


DEFAULT_PERSIST_DIR = "./storage"
DEFAULT_DATA_DIR = "./data"
DEFAULT_EMBEDDING_DIM = 768  # nomic-embed-textの次元数
HASH_FILE = "document_hashes.json"
TODO_FILE = "todos.json"
DEFAULT_CHUNK_SIZE = 800  # チャンクサイズ（文字数）
DEFAULT_CHUNK_OVERLAP = 100  # チャンク間のオーバーラップ（文字数）


class RAGSystem:
    """RAGシステムの主要なクラス - 全体の調整とクエリ処理を担当"""

    def __init__(
        self,
        persist_dir: str = DEFAULT_PERSIST_DIR,
        data_dir: str = DEFAULT_DATA_DIR,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        """
        RAGシステムの初期化

        Args:
            persist_dir: インデックスの永続化ディレクトリ
            data_dir: 入力データのディレクトリ
            embedding_dim: 埋め込みベクトルの次元数
            chunk_size: チャンクサイズ（文字数）
            chunk_overlap: チャンク間のオーバーラップ（文字数）
        """
        self.persist_dir = persist_dir
        self.data_dir = data_dir
        self.embedding_dim = embedding_dim
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # 各管理クラスの初期化
        self.document_manager = DocumentManager(data_dir, persist_dir)
        self.todo_manager = TodoManager(persist_dir)
        self.markdown_parser = MarkdownParser()
        self.text_chunker = TextChunker(chunk_size, chunk_overlap)
        self.index_manager = IndexManager(persist_dir, embedding_dim)

        # インデックスの初期化
        self.index = self.index_manager.initialize_index()

        # 初期化時にドキュメントの更新チェックを実行
        self._check_and_update_index_on_init()

    def load_documents(self, data_dir: Optional[str] = None) -> List[Document]:
        """
        指定されたディレクトリからドキュメントを読み込む

        Args:
            data_dir: 読み込み元ディレクトリ

        Returns:
            読み込んだドキュメントのリスト
        """
        return self.document_manager.load_documents(data_dir)

    def add_documents(self, documents: List[Document]) -> None:
        """
        インデックスにドキュメントを追加する

        Args:
            documents: 追加するドキュメント
        """
        if not documents:
            return

        # ドキュメントをノードに変換
        nodes = []
        for doc in documents:
            sections = self.markdown_parser.parse_markdown(doc.text)
            doc_nodes = self._create_nodes_from_sections(
                sections, doc.doc_id or "unknown"
            )
            nodes.extend(doc_nodes)

        # インデックスに追加
        self.index_manager.add_nodes(self.index, nodes)

    def _create_nodes_from_sections(
        self, sections: List[MarkdownSection], doc_id: str
    ) -> List[CustomTextNode]:
        """
        Markdownセクションからノードを作成する

        Args:
            sections: Markdownセクションリスト
            doc_id: ドキュメントID

        Returns:
            作成されたノードのリスト
        """
        nodes = []
        relative_path = self.document_manager.get_relative_path(doc_id)

        for i, section in enumerate(sections):
            # セクションの内容をチャンクに分割
            section_text = f"# {section.header}\n\n{section.content}"
            chunks = self.text_chunker.smart_split_text(section_text)

            for j, chunk in enumerate(chunks):
                if chunk.strip():
                    # ノードを作成
                    node = CustomTextNode(
                        text=chunk,
                        id_=f"{relative_path}:section_{i}:chunk_{j}"
                    )
                    # メタデータを設定
                    node.metadata = {
                        "doc_id": relative_path,
                        "section_id": i,
                        "chunk_id": j,
                        "header": section.header,
                        "level": section.level,
                        "total_chunks": len(chunks),
                        "original_section": section_text,
                    }
                    nodes.append(node)

        return nodes

    def query(self, query_text: str, top_k: int = 5) -> dict:
        """
        クエリを実行して回答を取得する

        Args:
            query_text: クエリテキスト
            top_k: 取得する関連文書数

        Returns:
            回答と関連文書の辞書
        """
        print(f"[DEBUG] Processing query: {query_text}")

        # クエリエンジンを作成
        query_engine = self.index_manager.create_query_engine(
            self.index, top_k)

        # クエリを実行
        response = query_engine.query(query_text)

        # 回答を構築
        result = {
            "answer": str(response.response),
            "sources": []
        }

        # ソース情報を追加
        if hasattr(response, 'source_nodes'):
            for node in response.source_nodes:
                if hasattr(node, 'node'):
                    node_data = node.node
                    metadata = node_data.metadata

                    source_info = {
                        "header": metadata.get("header", "Unknown"),
                        "content": node_data.text,
                        "doc_id": metadata.get("doc_id", "unknown"),
                        "section_id": metadata.get("section_id", 0),
                        "level": metadata.get("level", 1),
                        "score": getattr(node, 'score', 0.0)
                    }
                    result["sources"].append(source_info)

        return result

    def _check_and_update_index(self) -> None:
        """
        ドキュメントの更新をチェックし、必要に応じてインデックスを更新する
        """
        updated_files = self.document_manager.check_document_updates()

        if updated_files:
            print(f"[DEBUG] Found {len(updated_files)} updated files")

            # 更新されたファイルを読み込み
            updated_docs = []
            for file_path in updated_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    doc = Document(
                        text=content,
                        doc_id=file_path,
                        metadata={
                            "file_path": file_path,
                            "relative_path": self.document_manager.get_relative_path(file_path)
                        }
                    )
                    updated_docs.append(doc)
                except Exception as e:
                    print(f"[DEBUG] Error reading file {file_path}: {e}")

            # インデックスに追加
            if updated_docs:
                self.add_documents(updated_docs)
                self.document_manager.save_document_hashes()
                print(
                    f"[DEBUG] Updated index with {len(updated_docs)} documents")

    def _check_and_update_index_on_init(self) -> None:
        """
        初期化時にドキュメントの更新をチェックし、必要に応じてインデックスを更新する
        """
        print("[DEBUG] Checking for document updates during initialization...")

        # インデックスが空の場合は、全ドキュメントを強制的に処理
        index_is_empty = self.index_manager.is_index_empty(self.index)
        if index_is_empty:
            print("[DEBUG] Index is empty, forcing full document processing...")
            # 全ドキュメントを取得して処理
            all_files = self.document_manager.get_all_document_files()
            updated_files = all_files
            print(f"[DEBUG] Processing all {len(all_files)} documents")
        else:
            # 通常の更新チェック
            updated_files = self.document_manager.check_document_updates()

        if updated_files:
            print(
                f"[DEBUG] Found {len(updated_files)} files to process during initialization")

            # 更新されたファイルを読み込み
            updated_docs = []
            for file_path in updated_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    doc = Document(
                        text=content,
                        doc_id=file_path,
                        metadata={
                            "file_path": file_path,
                            "relative_path": self.document_manager.get_relative_path(file_path)
                        }
                    )
                    updated_docs.append(doc)
                except Exception as e:
                    print(f"[DEBUG] Error reading file {file_path}: {e}")

            # インデックスに追加
            if updated_docs:
                self.add_documents(updated_docs)
                self.document_manager.save_document_hashes()
                print(
                    f"[DEBUG] Updated index with {len(updated_docs)} documents during initialization")
        else:
            print("[DEBUG] No document updates found during initialization")

    def run_interactive(self) -> None:
        """
        インタラクティブモードで実行する
        """
        print("RAGシステムが起動しました。質問を入力してください。")
        print("終了するには 'quit' または 'exit' を入力してください。")

        while True:
            try:
                query = input("\n質問: ").strip()

                if query.lower() in ['quit', 'exit']:
                    print("RAGシステムを終了します。")
                    break

                if not query:
                    continue

                result = self.query(query)

                print(f"\n回答: {result['answer']}")

                if result['sources']:
                    print("\n参照元:")
                    for i, source in enumerate(result['sources'][:3]):
                        print(f"  [{i+1}] {source['header']} "
                              f"({source['doc_id']})")
                        print(f"      {source['content'][:200]}...")
                        if len(source['content']) > 200:
                            print("      [...]")

            except KeyboardInterrupt:
                print("\nRAGシステムを終了します。")
                break
            except Exception as e:
                print(f"エラーが発生しました: {e}")

    # TODO機能の委譲
    def get_todos(self, status: Optional[str] = None) -> List[TodoItem]:
        """TODOリストを取得する"""
        return self.todo_manager.get_todos(status)

    def add_todo(
        self, content: str, priority: str = "medium",
        source_file: str = "manual", source_section: str = "manual"
    ) -> TodoItem:
        """新しいTODOを追加する"""
        return self.todo_manager.add_todo(content, priority, source_file, source_section)

    def update_todo(self, todo_id: str, **kwargs) -> Optional[TodoItem]:
        """TODOを更新する"""
        return self.todo_manager.update_todo(todo_id, **kwargs)

    def delete_todo(self, todo_id: str) -> bool:
        """TODOを削除する"""
        return self.todo_manager.delete_todo(todo_id)

    def aggregate_todos_by_date(self) -> Dict[str, List[TodoItem]]:
        """日付別にTODOを集約する"""
        return self.todo_manager.aggregate_todos_by_date()

    def get_overdue_todos(self) -> List[TodoItem]:
        """期限切れのTODOを取得する"""
        return self.todo_manager.get_overdue_todos()

    def extract_todos_from_documents(self) -> int:
        """
        ドキュメントからTODOを抽出する

        Returns:
            抽出されたTODO数
        """
        all_files = self.document_manager.get_all_document_files()
        total_todos = 0

        for file_path in all_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                sections = self.markdown_parser.parse_markdown(content)
                relative_path = self.document_manager.get_relative_path(
                    file_path)

                for section in sections:
                    extracted_todos = self.todo_manager.extract_todos_from_text(
                        section.content, relative_path, section.header
                    )
                    added_count = self.todo_manager.add_extracted_todos(
                        extracted_todos)
                    total_todos += added_count

            except Exception as e:
                print(f"[DEBUG] Error processing file {file_path}: {e}")

        return total_todos

    def get_system_info(self) -> dict:
        """
        システム情報を取得する

        Returns:
            システム情報の辞書
        """
        return {
            "persist_dir": self.persist_dir,
            "data_dir": self.data_dir,
            "embedding_dim": self.embedding_dim,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "index_stats": self.index_manager.get_index_stats(self.index),
            "todo_count": len(self.todo_manager.get_todos()),
            "document_count": len(self.document_manager.get_all_document_files())
        }

    def _parse_markdown(self, content: str) -> List[MarkdownSection]:
        """
        Markdownコンテンツをパースしてセクションに分割する

        Args:
            content: Markdownコンテンツ

        Returns:
            MarkdownSectionのリスト
        """
        return self.markdown_parser.parse_markdown(content)

    def _create_new_index(self):
        """
        新しいインデックスを作成する

        Returns:
            新しく作成されたインデックス
        """
        return self.index_manager.refresh_index(self.index)
