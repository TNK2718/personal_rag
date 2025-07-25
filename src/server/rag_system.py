from typing import List, Dict, Optional
from llama_index.core import Document
from llama_index.core.schema import TextNode
from datetime import datetime
import hashlib

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
            # セクションの内容をチャンクに分割（箇条書きを考慮）
            section_text = f"# {section.header}\n\n{section.content}"
            chunks = self.text_chunker.split_text_by_bullet_items(section_text)

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
                        # "original_section" removed for metadata size limit
                    }

                    # TODOメタデータを追加
                    if self._chunk_has_todo(chunk):
                        node.metadata["has_todo"] = True
                        node.metadata["todo_content"] = self._extract_todo_content_from_chunk(
                            chunk)

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

                # チャンクハッシュを保存
                self._save_chunk_hashes_for_documents(updated_docs)

                self.document_manager.save_document_hashes()
                print(
                    f"[DEBUG] Updated index with {len(updated_docs)} documents")

    def _save_chunk_hashes_for_documents(self, documents: List[Document]) -> None:
        """ドキュメントのチャンクハッシュを保存する"""
        for doc in documents:
            sections = self.markdown_parser.parse_markdown(doc.text)
            doc_id = self.document_manager.get_relative_path(
                doc.doc_id or "unknown")

            for i, section in enumerate(sections):
                section_text = f"# {section.header}\n\n{section.content}"
                chunks = self.text_chunker.smart_split_text(section_text)

                for j, chunk in enumerate(chunks):
                    if chunk.strip():
                        chunk_id = f"{doc_id}:section_{i}:chunk_{j}"
                        chunk_hash = self.document_manager.calculate_chunk_hash(
                            chunk)
                        self.document_manager.chunk_hashes[chunk_id] = chunk_hash

        # 更新されたチャンクハッシュを保存
        self.document_manager.save_chunk_hashes(
            self.document_manager.chunk_hashes)

    def check_chunk_level_updates(self, file_paths: List[str]) -> List[Dict]:
        """チャンクレベルでの更新をチェックする"""
        updated_chunks = []

        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Markdownを解析してチャンクを作成
                sections = self.markdown_parser.parse_markdown(content)
                doc_id = self.document_manager.get_relative_path(file_path)

                file_chunks = []
                for i, section in enumerate(sections):
                    section_text = f"# {section.header}\n\n{section.content}"
                    chunks = self.text_chunker.smart_split_text(section_text)

                    for j, chunk in enumerate(chunks):
                        if chunk.strip():
                            chunk_data = {
                                "id": f"{doc_id}:section_{i}:chunk_{j}",
                                "text": chunk,
                                "metadata": {
                                    "doc_id": doc_id,
                                    "section_id": i,
                                    "chunk_id": j,
                                    "header": section.header,
                                    "level": section.level
                                }
                            }
                            file_chunks.append(chunk_data)

                # チャンクレベルでの更新をチェック
                updated_file_chunks = self.document_manager.check_chunk_updates(
                    file_chunks)
                updated_chunks.extend(updated_file_chunks)

            except Exception as e:
                print(f"[DEBUG] Error processing file {file_path}: {e}")

        # 更新されたチャンクハッシュを保存
        if updated_chunks:
            self.document_manager.save_chunk_hashes(
                self.document_manager.chunk_hashes)

        return updated_chunks

    def apply_chunk_updates(self, updated_chunks: List[Dict]) -> None:
        """更新されたチャンクをインデックスに適用する"""
        if not updated_chunks:
            return

        print(f"[DEBUG] Applying {len(updated_chunks)} chunk updates")

        # 更新されたチャンクからノードを作成
        nodes = []
        for chunk_data in updated_chunks:
            node = CustomTextNode(
                text=chunk_data["text"],
                id_=chunk_data["id"]
            )
            node.metadata = chunk_data["metadata"]
            nodes.append(node)

        # 既存のチャンクを削除（同じIDのものがあれば）
        self._remove_existing_chunks([chunk["id"] for chunk in updated_chunks])

        # 新しいチャンクを追加
        self.index_manager.add_nodes(self.index, nodes)

        # チャンクハッシュを更新
        for chunk_data in updated_chunks:
            chunk_hash = self.document_manager.calculate_chunk_hash(
                chunk_data["text"])
            self.document_manager.chunk_hashes[chunk_data["id"]] = chunk_hash

        self.document_manager.save_chunk_hashes(
            self.document_manager.chunk_hashes)

    def handle_deleted_chunks(self, current_files: List[str]) -> List[str]:
        """削除されたチャンクを処理する"""
        # 現在のファイルからチャンクを生成
        current_chunks = []
        for file_path in current_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                sections = self.markdown_parser.parse_markdown(content)
                doc_id = self.document_manager.get_relative_path(file_path)

                for i, section in enumerate(sections):
                    section_text = f"# {section.header}\n\n{section.content}"
                    chunks = self.text_chunker.smart_split_text(section_text)

                    for j, chunk in enumerate(chunks):
                        if chunk.strip():
                            chunk_data = {
                                "id": f"{doc_id}:section_{i}:chunk_{j}",
                                "text": chunk
                            }
                            current_chunks.append(chunk_data)

            except Exception as e:
                print(f"[DEBUG] Error processing file {file_path}: {e}")

        # 削除されたチャンクを特定
        removed_chunk_ids = self.document_manager.remove_deleted_chunks(
            current_chunks)

        # インデックスからも削除
        if removed_chunk_ids:
            self._remove_existing_chunks(removed_chunk_ids)

        return removed_chunk_ids

    def _remove_existing_chunks(self, chunk_ids: List[str]) -> None:
        """既存のチャンクをインデックスから削除する"""
        # 現在の実装では、LlamaIndexでの個別ノード削除は複雑
        # 実用的には、インデックス全体を再構築するか、
        # 削除フラグを使用する方法がある
        # ここでは簡単な実装として、削除をログに記録
        print(f"[DEBUG] Removing {len(chunk_ids)} chunks from index")
        for chunk_id in chunk_ids:
            print(f"[DEBUG] Would remove chunk: {chunk_id}")

    def run_interactive(self) -> None:
        """インタラクティブなRAGシステムを実行する"""
        print("RAGシステムが起動しました。質問を入力してください。")
        print("終了するには 'quit' または 'exit' を入力してください。")

        while True:
            try:
                query = input("\n質問: ")

                if query.lower() in ['quit', 'exit', 'q']:
                    print("RAGシステムを終了します。")
                    break

                if not query.strip():
                    continue

                # 動的な更新チェック
                self._check_and_update_index()

                # 質問に回答
                result = self.query(query)
                print(f"\n回答: {result['answer']}")

                # 関連文書の表示
                if result['sources']:
                    print("\n関連文書:")
                    for i, source in enumerate(result['sources'], 1):
                        print(
                            f"{i}. {source['header']} (スコア: {source['score']:.2f})")
                        print(f"   {source['content'][:100]}...")

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
        """TODOを追加する"""
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
        """ドキュメントからTODOを抽出する"""
        total_extracted = 0
        all_extracted_todos = []  # 抽出したTODOを一時保存

        # 全ドキュメントファイルを取得
        all_files = self.document_manager.get_all_document_files()
        print(f"[DEBUG] Found {len(all_files)} files to process")

        for file_path in all_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # ファイルパスを相対パスに変換
                relative_path = self.document_manager.get_relative_path(
                    file_path)
                print(f"[DEBUG] Processing file: {relative_path}")

                # Markdownを解析してセクションごとに処理
                sections = self.markdown_parser.parse_markdown(content)
                print(
                    f"[DEBUG] Found {len(sections)} sections in {relative_path}")

                for i, section in enumerate(sections):
                    section_name = section.header

                    # TODOセクションの場合、デバッグ情報を出力
                    if 'TODO' in section.header.upper():
                        print(f"[DEBUG] Found TODO section: {section.header}")
                        print(
                            f"[DEBUG] Section content length: {len(section.content)}")
                        print(
                            f"[DEBUG] Section content preview: {section.content[:50]}...")

                    # チャンクからTODOメタデータを抽出
                    chunk_todos = self._extract_todos_from_chunks(
                        section.content, relative_path, section_name, i, section.header
                    )

                    # テキストからTODOを抽出
                    text_todos = self.todo_manager.extract_todos_from_text(
                        section.content,
                        relative_path,
                        section_name
                    )

                    # 重複を除去して両方の抽出結果をマージ
                    section_todos = self._deduplicate_todos(chunk_todos, text_todos)
                    
                    if section_todos:
                        print(
                            f"[DEBUG] Found {len(section_todos)} unique TODOs in section '{section.header}' (chunk: {len(chunk_todos)}, text: {len(text_todos)})")
                        for todo in section_todos:
                            print(f"[DEBUG] Unique TODO: {todo.content}")
                        all_extracted_todos.extend(section_todos)
                        total_extracted += len(section_todos)

            except Exception as e:
                print(f"[DEBUG] Error extracting TODOs from {file_path}: {e}")

        print(f"[DEBUG] Total extracted TODOs: {total_extracted}")
        print(
            f"[DEBUG] All extracted TODOs: {[todo.content for todo in all_extracted_todos]}")

        # 抽出したTODOを追加（重複チェック付き）
        if all_extracted_todos:
            added_count = self.todo_manager.add_extracted_todos(
                all_extracted_todos)
            print(
                f"[DEBUG] Added {added_count} new TODOs out of {total_extracted} extracted")
            return added_count

        print(f"[DEBUG] No TODOs extracted")
        return 0

    def _extract_todos_from_chunks(self, text: str, relative_path: str, section_name: str, section_id: int, section_header: str = "") -> List[TodoItem]:
        """
        チャンクのメタデータからTODOを抽出する

        Args:
            text: セクションのテキスト
            relative_path: 相対ファイルパス
            section_name: セクション名
            section_id: セクションID
            section_header: セクションのヘッダー名

        Returns:
            抽出されたTODO項目のリスト
        """
        todos = []

        # チャンクのメタデータを作成（セクションヘッダーを含める）
        chunks_with_metadata = self.text_chunker.create_chunks_with_todo_metadata(
            text, relative_path, section_id, section_header
        )

        for chunk_data in chunks_with_metadata:
            metadata = chunk_data['metadata']

            # TODOメタデータを持つチャンクを検出
            if metadata.get('has_todo'):
                todo_content = metadata.get('todo_content', '')

                if todo_content:
                    # 既存のTODOマネージャーを使用して作成
                    current_time = datetime.now().isoformat()
                    todo_id = hashlib.md5(
                        f"{relative_path}:{section_name}:{todo_content}".encode()
                    ).hexdigest()[:8]

                    # 既存のTODOを確認して作成日を保持
                    existing_todo = None
                    for existing in self.todo_manager.todos:
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

                    # TODOコンテンツから締切日を抽出
                    extracted_due_date = self.todo_manager._extract_due_date_from_text(
                        todo_content)

                    todo = TodoItem(
                        id=todo_id,
                        content=todo_content,
                        status="pending",
                        priority=metadata.get('todo_priority', 'medium'),
                        created_at=created_at,
                        updated_at=updated_at,
                        source_file=relative_path,
                        source_section=section_name,
                        due_date=extracted_due_date,
                        related_chunk_ids=[metadata.get('chunk_id', '')]
                    )
                    todos.append(todo)

        return todos

    def _deduplicate_todos(self, chunk_todos: List[TodoItem], text_todos: List[TodoItem]) -> List[TodoItem]:
        """
        チャンクTODOとテキストTODOから重複を除去してマージする
        
        Args:
            chunk_todos: チャンクから抽出されたTODO項目のリスト
            text_todos: テキストから抽出されたTODO項目のリスト
            
        Returns:
            重複を除去したTODO項目のリスト
        """
        # チャンクTODOを優先とする統合リスト
        unique_todos = []
        seen_contents = set()
        
        # チャンクTODOを最初に追加（より詳細なメタデータを持つため優先）
        content_to_todo = {}  # 正規化コンテンツ -> TODO のマッピング
        
        for todo in chunk_todos:
            normalized_content = self._normalize_todo_content(todo.content)
            if len(normalized_content) > 3:
                if normalized_content not in content_to_todo:
                    content_to_todo[normalized_content] = todo
                    seen_contents.add(normalized_content)
                else:
                    # 既存のTODOと比較して、より早い作成日を保持
                    existing_todo = content_to_todo[normalized_content]
                    if todo.created_at < existing_todo.created_at:
                        # より早い作成日のTODOで置き換え（ただしチャンクメタデータは保持）
                        updated_todo = TodoItem(
                            id=existing_todo.id,
                            content=existing_todo.content,
                            status=existing_todo.status,
                            priority=existing_todo.priority,
                            created_at=todo.created_at,  # より早い作成日を使用
                            updated_at=existing_todo.updated_at,
                            source_file=existing_todo.source_file,
                            source_section=existing_todo.source_section,
                            due_date=existing_todo.due_date,
                            tags=existing_todo.tags,
                            related_chunk_ids=existing_todo.related_chunk_ids
                        )
                        content_to_todo[normalized_content] = updated_todo
        
        # テキストTODOから重複していないものを追加、または作成日がより早いものは更新
        for todo in text_todos:
            normalized_content = self._normalize_todo_content(todo.content)
            if len(normalized_content) > 3:
                if normalized_content not in content_to_todo:
                    content_to_todo[normalized_content] = todo
                    seen_contents.add(normalized_content)
                else:
                    # 既存のTODOと比較して、より早い作成日を保持
                    existing_todo = content_to_todo[normalized_content]
                    if todo.created_at < existing_todo.created_at:
                        # より早い作成日で既存TODOを更新（チャンクメタデータは保持）
                        updated_todo = TodoItem(
                            id=existing_todo.id,
                            content=existing_todo.content,
                            status=existing_todo.status,
                            priority=existing_todo.priority,
                            created_at=todo.created_at,  # より早い作成日を使用
                            updated_at=existing_todo.updated_at,
                            source_file=existing_todo.source_file,
                            source_section=existing_todo.source_section,
                            due_date=existing_todo.due_date,
                            tags=existing_todo.tags,
                            related_chunk_ids=existing_todo.related_chunk_ids
                        )
                        content_to_todo[normalized_content] = updated_todo
        
        # マップから最終的なリストを作成
        unique_todos = list(content_to_todo.values())
        
        return unique_todos
    
    def _normalize_todo_content(self, content: str) -> str:
        """
        TODO内容を正規化して重複判定用に統一する
        
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
        
        # 句読点を統一・除去（日本語と英語の句読点）
        punctuation_pattern = r'[。、！？．，!?\.;:…]+$'
        normalized = re.sub(punctuation_pattern, '', normalized)
        
        # 複数のスペース・タブを単一スペースに統一
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        # 全角スペースを半角スペースに統一
        normalized = normalized.replace('　', ' ')
        
        # 「する」「を行う」などの冗長な表現を正規化（オプション）
        # これは積極的すぎる可能性があるので、コメントアウト
        # normalized = re.sub(r'(する|を行う|を実行する)$', '', normalized)
        
        return normalized.lower().strip()

    def _chunk_has_todo(self, chunk_text: str) -> bool:
        """
        チャンクにTODOが含まれているかをチェックする

        Args:
            chunk_text: チャンクのテキスト

        Returns:
            TODOが含まれている場合True
        """
        todo_patterns = [
            r'\b(?:TODO|Todo|todo)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:BUG|Bug|bug)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:HACK|Hack|hack)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:NOTE|Note|note)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:XXX|xxx)\s*:?\s*(.+?)(?:\n|$)',
            r'- \[ \]\s*(.+?)(?:\n|$)',  # Markdownチェックボックス
            # r'- \[x\]\s*(.+?)(?:\n|$)',  # 完了チェックボックス
            # リストアイテムのTODO
            r'^\s*[\*\-]\s*(?:TODO|Todo|todo)\s*:?\s*(.+?)(?:\n|$)',
            # リストアイテムのFIXME
            r'^\s*[\*\-]\s*(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?:\n|$)',
            # リストアイテムのBUG
            r'^\s*[\*\-]\s*(?:BUG|Bug|bug)\s*:?\s*(.+?)(?:\n|$)',
            # リストアイテムのNOTE
            r'^\s*[\*\-]\s*(?:NOTE|Note|note)\s*:?\s*(.+?)(?:\n|$)',
            # リストアイテムのHACK
            r'^\s*[\*\-]\s*(?:HACK|Hack|hack)\s*:?\s*(.+?)(?:\n|$)',
            r'^\s*[\*\-]\s*(?:XXX|xxx)\s*:?\s*(.+?)(?:\n|$)'  # リストアイテムのXXX
        ]

        import re
        for pattern in todo_patterns:
            if re.search(pattern, chunk_text, re.MULTILINE | re.IGNORECASE):
                return True
        return False

    def _extract_todo_content_from_chunk(self, chunk_text: str) -> str:
        """
        チャンクからTODOコンテンツを抽出する

        Args:
            chunk_text: チャンクのテキスト

        Returns:
            抽出されたTODOコンテンツ
        """
        todo_patterns = [
            r'\b(?:TODO|Todo|todo)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:BUG|Bug|bug)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:HACK|Hack|hack)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:NOTE|Note|note)\s*:?\s*(.+?)(?:\n|$)',
            r'\b(?:XXX|xxx)\s*:?\s*(.+?)(?:\n|$)',
            r'- \[ \]\s*(.+?)(?:\n|$)',  # Markdownチェックボックス
            r'- \[x\]\s*(.+?)(?:\n|$)',  # 完了チェックボックス
            # リストアイテムのTODO
            r'^\s*[\*\-]\s*(?:TODO|Todo|todo)\s*:?\s*(.+?)(?:\n|$)',
            # リストアイテムのFIXME
            r'^\s*[\*\-]\s*(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?:\n|$)',
            # リストアイテムのBUG
            r'^\s*[\*\-]\s*(?:BUG|Bug|bug)\s*:?\s*(.+?)(?:\n|$)',
            # リストアイテムのNOTE
            r'^\s*[\*\-]\s*(?:NOTE|Note|note)\s*:?\s*(.+?)(?:\n|$)',
            # リストアイテムのHACK
            r'^\s*[\*\-]\s*(?:HACK|Hack|hack)\s*:?\s*(.+?)(?:\n|$)',
            r'^\s*[\*\-]\s*(?:XXX|xxx)\s*:?\s*(.+?)(?:\n|$)'  # リストアイテムのXXX
        ]

        import re
        for pattern in todo_patterns:
            match = re.search(pattern, chunk_text,
                              re.MULTILINE | re.IGNORECASE)
            if match:
                content = match.group(1).strip()
                # リストアイテムの場合は最初の'*'や'-'を削除
                if content.startswith('*') or content.startswith('-'):
                    content = content[1:].strip()
                return content

        return ""

    def get_system_info(self) -> dict:
        """システム情報を取得する"""
        try:
            # インデックス統計情報
            index_stats = self.index_manager.get_index_stats(self.index)

            # TODO統計情報
            all_todos = self.todo_manager.get_todos()
            todo_stats = {
                'total_todos': len(all_todos),
                'pending_todos': len([t for t in all_todos if t.status == 'pending']),
                'completed_todos': len([t for t in all_todos if t.status == 'completed']),
            }

            # ドキュメント統計情報
            all_files = self.document_manager.get_all_document_files()
            doc_stats = {
                'total_documents': len(all_files),
                'data_directory': self.data_dir,
                'persist_directory': self.persist_dir
            }

            return {
                'index_stats': index_stats,
                'todo_stats': todo_stats,
                'document_stats': doc_stats,
                'system_components': {
                    'document_manager': 'DocumentManager',
                    'todo_manager': 'TodoManager',
                    'markdown_parser': 'MarkdownParser',
                    'text_chunker': 'TextChunker',
                    'index_manager': 'IndexManager'
                }
            }

        except Exception as e:
            print(f"[DEBUG] Error getting system info: {e}")
            return {'error': str(e)}

    def _parse_markdown(self, content: str) -> List[MarkdownSection]:
        """Markdownコンテンツを解析する（後方互換性のため）"""
        return self.markdown_parser.parse_markdown(content)

    def _create_new_index(self):
        """新しいインデックスを作成する（後方互換性のため）"""
        return self.index_manager._create_new_index()
