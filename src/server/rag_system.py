import os
import json
import hashlib
import faiss  # type: ignore
import re
from typing import Optional, List, Dict, cast
from dataclasses import dataclass, asdict
from datetime import datetime
from markdown_it import MarkdownIt
from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    Settings,
    load_index_from_storage,
    Document,
)
from llama_index.core.schema import TextNode
from llama_index.vector_stores.faiss import FaissVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding

DEFAULT_PERSIST_DIR = "./storage"
DEFAULT_DATA_DIR = "./data"
DEFAULT_EMBEDDING_DIM = 768  # nomic-embed-textの次元数
HASH_FILE = "document_hashes.json"
TODO_FILE = "todos.json"


@dataclass
class MarkdownSection:
    """Markdownセクションを表すデータクラス"""
    header: str
    content: str
    level: int  # ヘッダーレベル (h1=1, h2=2, etc.)


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


class RAGSystem:
    """RAGシステムのメインクラス"""

    def __init__(
        self,
        persist_dir: str = DEFAULT_PERSIST_DIR,
        data_dir: str = DEFAULT_DATA_DIR,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
    ):
        """
        RAGシステムの初期化

        Args:
            persist_dir: インデックスの永続化ディレクトリ
            data_dir: 入力データのディレクトリ
            embedding_dim: 埋め込みベクトルの次元数
        """
        self.persist_dir = persist_dir
        self.data_dir = data_dir
        self.embedding_dim = embedding_dim
        self.faiss_index_path = os.path.join(persist_dir, "faiss_index.bin")
        self.hash_file_path = os.path.join(persist_dir, HASH_FILE)
        self.todo_file_path = os.path.join(persist_dir, TODO_FILE)
        self.md_parser = MarkdownIt()
        self.document_hashes: Dict[str, str] = self._load_document_hashes()
        self.todos: List[TodoItem] = self._load_todos()

        # LLMの設定
        self.llm = Ollama(
            model="hf.co/mmnga/sarashina2.2-3b-instruct-v0.1-gguf:latest",
            request_timeout=120.0,
            system_prompt="あなたは親切なアシスタントです。与えられた文脈に基づいて、日本語で簡潔に回答してください。"
        )
        Settings.llm = self.llm

        # Embedding Modelの設定
        self.embed_model = OllamaEmbedding(model_name="nomic-embed-text")
        Settings.embed_model = self.embed_model

        # インデックスの初期化
        self.index = self._initialize_index()

    def _load_document_hashes(self) -> Dict[str, str]:
        """保存されているドキュメントハッシュを読み込む"""
        if os.path.exists(self.hash_file_path):
            with open(self.hash_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save_document_hashes(self) -> None:
        """ドキュメントハッシュを保存する"""
        os.makedirs(self.persist_dir, exist_ok=True)
        with open(self.hash_file_path, 'w', encoding='utf-8') as f:
            json.dump(self.document_hashes, f, ensure_ascii=False, indent=2)

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

    def _calculate_file_hash(self, file_path: str) -> str:
        """ファイルのハッシュ値を計算する"""
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def _extract_todos_from_text(self, text: str, source_file: str, source_section: str) -> List[TodoItem]:
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
            r'\* \[ \]\s*(.+?)(?:\n|$)',
            r'\d+\.\s*(.+?)(?:\n|$)',  # 番号付きリスト
            r'[・•]\s*(.+?)(?:\n|$)',  # 箇条書き
        ]

        current_time = datetime.now().isoformat()

        for pattern in patterns:
            matches = re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE)
            for match in matches:
                content = match.group(1).strip()
                if content and len(content) > 3:  # 短すぎるものは除外
                    # 優先度を推定
                    priority = "medium"
                    if any(word in content.lower() for word in ['urgent', '急', '緊急', 'asap']):
                        priority = "high"
                    elif any(word in content.lower() for word in ['later', '後で', '将来']):
                        priority = "low"

                    # IDを生成
                    todo_id = hashlib.md5(
                        f"{source_file}:{source_section}:{content}".encode()).hexdigest()[:8]

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

    def _check_document_updates(self) -> List[str]:
        """更新のあったドキュメントのパスを取得する"""
        updated_files = []
        for root, _, files in os.walk(self.data_dir):
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
                    # パスを正規化してクロスプラットフォーム対応
                    file_path = os.path.normpath(file_path)
                    current_hash = self._calculate_file_hash(file_path)
                    stored_hash = self.document_hashes.get(file_path)

                    if stored_hash != current_hash:
                        updated_files.append(file_path)
                        self.document_hashes[file_path] = current_hash

        return updated_files

    def _parse_markdown(self, content: str) -> List[MarkdownSection]:
        """Markdownコンテンツをパースしてセクションに分割する"""
        tokens = self.md_parser.parse(content)
        sections: List[MarkdownSection] = []
        current_header = ""
        current_level = 0
        current_content: List[str] = []
        in_header = False

        for token in tokens:
            if token.type == "heading_open":
                if current_header and current_content:
                    sections.append(MarkdownSection(
                        header=current_header,
                        content="\n".join(current_content).strip(),
                        level=current_level
                    ))
                current_level = int(token.tag[1])  # h1 -> 1, h2 -> 2, etc.
                current_content = []
                in_header = True
            elif token.type == "heading_close":
                in_header = False
            elif token.type == "inline":
                if in_header:
                    current_header = token.content
                else:
                    current_content.append(token.content)

        if current_header and current_content:
            sections.append(MarkdownSection(
                header=current_header,
                content="\n".join(current_content).strip(),
                level=current_level
            ))

        return sections

    def _create_nodes_from_sections(
        self,
        sections: List[MarkdownSection],
        doc_id: str
    ) -> List[TextNode]:
        """セクションからノードを作成する"""
        nodes = []

        # ファイルパスからフォルダ名を抽出
        file_path = doc_id
        folder_name = ""
        if file_path.startswith(self.data_dir):
            rel_path = os.path.relpath(file_path, self.data_dir)
            folder_parts = os.path.dirname(rel_path).split(os.sep)
            # 空文字列や'.'を除外してフォルダ名を構築
            folder_parts = [
                part for part in folder_parts if part and part != '.']
            if folder_parts:
                folder_name = "/".join(folder_parts)

        # ファイル名（拡張子なし）を取得
        file_name = os.path.splitext(os.path.basename(file_path))[0]

        for i, section in enumerate(sections):
            # セクションからTODOを抽出
            section_todos = self._extract_todos_from_text(
                section.content, doc_id, section.header
            )

            # 既存のTODOと重複チェック
            for todo in section_todos:
                if not any(existing.id == todo.id for existing in self.todos):
                    self.todos.append(todo)

            # 共通のメタデータ
            common_metadata = {
                "doc_id": doc_id,
                "file_name": file_name,
                "folder_name": folder_name,
                "section_id": i,
                "header": section.header,
                "level": section.level
            }

            header_node = TextNode(
                text=section.header,
                metadata={
                    **common_metadata,
                    "type": "header"
                }
            )

            content_node = TextNode(
                text=section.content,
                metadata={
                    **common_metadata,
                    "type": "content"
                }
            )

            nodes.extend([header_node, content_node])

        return nodes

    def _initialize_index(self) -> VectorStoreIndex:
        """インデックスの初期化（読み込みまたは新規作成）"""
        os.makedirs(self.persist_dir, exist_ok=True)

        try:
            updated_files = self._check_document_updates()

            if os.path.exists(self.faiss_index_path):
                index = self._load_index()
                print("既存のインデックスを読み込みました。")

                if updated_files:
                    print(f"{len(updated_files)}個のファイルが更新されています。")

                    faiss_index = faiss.IndexFlatL2(self.embedding_dim)
                    vector_store = FaissVectorStore(faiss_index=faiss_index)
                    storage_context = StorageContext.from_defaults(
                        vector_store=vector_store
                    )

                    all_documents = []
                    for root, _, files in os.walk(self.data_dir):
                        for file in files:
                            if file.endswith('.md'):
                                file_path = os.path.join(root, file)
                                if file_path not in updated_files:
                                    reader = SimpleDirectoryReader(
                                        input_files=[file_path])
                                    docs = reader.load_data()
                                    for doc in docs:
                                        if doc.text.strip():
                                            sections = self._parse_markdown(
                                                doc.text)
                                            nodes = self._create_nodes_from_sections(
                                                sections, doc.doc_id)
                                            all_documents.extend([
                                                Document(
                                                    text=node.text,
                                                    metadata=node.metadata
                                                ) for node in nodes
                                            ])

                    for file_path in updated_files:
                        reader = SimpleDirectoryReader(input_files=[file_path])
                        docs = reader.load_data()
                        for doc in docs:
                            if doc.text.strip():
                                sections = self._parse_markdown(doc.text)
                                nodes = self._create_nodes_from_sections(
                                    sections, doc.doc_id)
                                all_documents.extend([
                                    Document(
                                        text=node.text,
                                        metadata=node.metadata
                                    ) for node in nodes
                                ])

                    index = VectorStoreIndex.from_documents(
                        all_documents,
                        storage_context=storage_context
                    )

                    index.storage_context.persist(persist_dir=self.persist_dir)
                    self._save_document_hashes()
                    print("インデックスを更新しました。")

                return index
            else:
                print("インデックスファイルが見つかりません。新規作成します。")
                return self._create_new_index()

        except Exception as e:
            print(f"インデックスの処理中にエラーが発生しました: {e}")
            print("インデックスを新規に作成します。")
            return self._create_new_index()

    def _load_index(self) -> VectorStoreIndex:
        """既存のインデックスを読み込む"""
        if not os.path.exists(self.faiss_index_path):
            raise FileNotFoundError("Faissインデックスファイルが見つかりません")

        faiss_index = faiss.read_index(self.faiss_index_path)
        vector_store = FaissVectorStore(faiss_index=faiss_index)

        storage_context = StorageContext.from_defaults(
            vector_store=vector_store,
            persist_dir=self.persist_dir
        )
        index = load_index_from_storage(storage_context)
        print("既存のインデックスを読み込みました。")
        return cast(VectorStoreIndex, index)

    def _create_new_index(self) -> VectorStoreIndex:
        """新しいインデックスを作成する"""
        documents = self.load_documents()

        faiss_index = faiss.IndexFlatL2(self.embedding_dim)
        vector_store = FaissVectorStore(faiss_index=faiss_index)
        storage_context = StorageContext.from_defaults(
            vector_store=vector_store)

        index = VectorStoreIndex.from_documents(
            documents, storage_context=storage_context
        )

        self._save_index(faiss_index, storage_context)

        for root, _, files in os.walk(self.data_dir):
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
                    self.document_hashes[file_path] = self._calculate_file_hash(
                        file_path)
        self._save_document_hashes()

        print("インデックスを新規に作成し、保存しました。")
        return index

    def load_documents(self, data_dir: Optional[str] = None) -> List[Document]:
        """ドキュメントを読み込んでセクションに分割する"""
        target_dir = data_dir or self.data_dir
        documents = SimpleDirectoryReader(target_dir).load_data()

        all_nodes = []
        for doc in documents:
            if doc.text.strip():
                sections = self._parse_markdown(doc.text)
                nodes = self._create_nodes_from_sections(sections, doc.doc_id)
                all_nodes.extend(nodes)

        return [Document(text=node.text, metadata=node.metadata) for node in all_nodes]

    def _save_index(
        self,
        faiss_index: faiss.Index,
        storage_context: StorageContext
    ) -> None:
        """インデックスを永続化する"""
        faiss.write_index(faiss_index, self.faiss_index_path)
        storage_context.persist(persist_dir=self.persist_dir)

    def add_documents(self, documents: List[Document]) -> None:
        """既存のインデックスに新しいドキュメントを追加する"""
        self.index = cast(VectorStoreIndex, self.index.from_documents(
            documents,
            storage_context=self.index.storage_context
        ))
        print("ドキュメントを追加しました。")

    def query(self, query_text: str) -> dict:
        """質問に対する回答を生成する"""
        try:
            print(f"[DEBUG] クエリ開始: {query_text}")

            retriever = self.index.as_retriever(
                similarity_top_k=3
            )
            print("[DEBUG] Retriever作成完了")

            nodes = []

            print("[DEBUG] ノード検索開始")
            all_retrieved_nodes = retriever.retrieve(query_text)
            retrieved_count = len(all_retrieved_nodes)
            print(f"[DEBUG] 検索結果: {retrieved_count}個のノードを取得")

            header_nodes = [
                node for node in all_retrieved_nodes
                if node.metadata.get("type") == "header"
            ]

            content_nodes = [
                node for node in all_retrieved_nodes
                if node.metadata.get("type") == "content"
            ]

            nodes = header_nodes + content_nodes
            nodes.sort(key=lambda x: (
                x.metadata.get("level", 999),
                -(x.score or 0.0)
            ))

            header_count = len(header_nodes)
            content_count = len(content_nodes)
            print(f"[DEBUG] ノード整理完了: header={header_count}, "
                  f"content={content_count}")

            print("[DEBUG] QueryEngine作成開始")
            query_engine = self.index.as_query_engine(
                similarity_top_k=3,
                system_prompt="""あなたは親切なアシスタントです。
与えられた文脈に基づいて、日本語で簡潔に回答してください。
特に、ヘッダー情報を参考にして、文書の構造を意識した回答を心がけてください。
関連するヘッダーがある場合は、その情報も含めて回答してください。"""
            )
            print("[DEBUG] QueryEngine作成完了")

            print("[DEBUG] LLMクエリ実行開始")
            response = query_engine.query(query_text)
            response_type = type(response)
            print(f"[DEBUG] LLMクエリ実行完了: response type={response_type}")

            answer = str(response)
            answer_length = len(answer)
            print(f"[DEBUG] レスポンス変換完了: answer length={answer_length}")

            if not answer or answer.strip() == "":
                print("[WARNING] 空の回答が生成されました")
                answer = "申し訳ございませんが、適切な回答を生成できませんでした。"

            # ソース情報を整理
            sources = []
            for node in nodes[:3]:  # 上位3つのノードのみ
                sources.append({
                    "header": node.metadata.get("header", ""),
                    "content": node.text,
                    "doc_id": node.metadata.get("doc_id", ""),
                    "file_name": node.metadata.get("file_name", ""),
                    "folder_name": node.metadata.get("folder_name", ""),
                    "section_id": node.metadata.get("section_id", 0),
                    "level": node.metadata.get("level", 1),
                    "type": node.metadata.get("type", ""),
                    "score": node.score or 0.0
                })

            sources_count = len(sources)
            print(f"[DEBUG] ソース情報整理完了: {sources_count}個のソース")

            result = {
                "answer": answer,
                "sources": sources
            }

            print("[DEBUG] クエリ処理完了")
            return result

        except Exception as e:
            print(f"[ERROR] クエリ処理中にエラーが発生: {e}")
            import traceback
            traceback.print_exc()

            # フォールバック応答
            error_msg = (f"エラーが発生しました: {str(e)}。"
                         "システム管理者にお問い合わせください。")
            return {
                "answer": error_msg,
                "sources": []
            }

    def run_interactive(self) -> None:
        """インタラクティブな質問応答を実行する"""
        print("\n--- 質問応答開始 ---")
        print("終了するには 'exit' または 'quit' と入力してください。")

        while True:
            query_text = input("\n質問を入力してください: ")
            if query_text.lower() in ["exit", "quit"]:
                break

            print("\n回答:")

            query_engine = self.index.as_query_engine(
                similarity_top_k=3,
                system_prompt="""あなたは親切なアシスタントです。
与えられた文脈に基づいて、日本語で簡潔に回答してください。
特に、ヘッダー情報を参考にして、文書の構造を意識した回答を心がけてください。
関連するヘッダーがある場合は、その情報も含めて回答してください。
できるだけ短い単位で区切って回答を生成してください。"""
            )

            response = query_engine.query(query_text)
            response_text = str(response)

            for char in response_text:
                print(char, end="", flush=True)
                if char in ["。", "、", "！", "？", "\n"]:
                    from time import sleep
                    sleep(0.1)

            print("\n" + "-" * 20)

    def get_todos(self, status: Optional[str] = None) -> List[TodoItem]:
        """TODOリストを取得する"""
        if status:
            return [todo for todo in self.todos if todo.status == status]
        return self.todos

    def add_todo(self, content: str, priority: str = "medium", source_file: str = "manual", source_section: str = "manual") -> TodoItem:
        """TODO項目を手動で追加する"""
        current_time = datetime.now().isoformat()
        todo_id = hashlib.md5(
            f"{source_file}:{source_section}:{content}:{current_time}".encode()).hexdigest()[:8]

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
        """TODO項目を更新する"""
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
        """TODO項目を削除する"""
        for i, todo in enumerate(self.todos):
            if todo.id == todo_id:
                del self.todos[i]
                self._save_todos()
                return True
        return False

    def aggregate_todos_by_date(self) -> Dict[str, List[TodoItem]]:
        """日付別にTODOを集約する"""
        aggregated = {}
        for todo in self.todos:
            date_key = todo.created_at[:10]  # YYYY-MM-DDを抽出
            if date_key not in aggregated:
                aggregated[date_key] = []
            aggregated[date_key].append(todo)

        # 日付でソート
        return dict(sorted(aggregated.items(), reverse=True))

    def get_overdue_todos(self) -> List[TodoItem]:
        """期限切れのTODOを取得する"""
        current_date = datetime.now().date()
        overdue_todos = []

        for todo in self.todos:
            if todo.due_date:
                try:
                    due_date = datetime.fromisoformat(todo.due_date).date()
                    if due_date < current_date and todo.status != "completed":
                        overdue_todos.append(todo)
                except ValueError:
                    continue

        return overdue_todos

    def extract_todos_from_documents(self) -> int:
        """全てのドキュメントからTODOを再抽出する"""
        initial_count = len(self.todos)

        # 既存のTODOをクリアして再抽出
        self.todos = []

        for root, _, files in os.walk(self.data_dir):
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            sections = self._parse_markdown(content)

                            for section in sections:
                                todos = self._extract_todos_from_text(
                                    section.content, file_path, section.header
                                )
                                self.todos.extend(todos)
                    except Exception as e:
                        print(f"Error processing {file_path}: {e}")

        self._save_todos()
        return len(self.todos) - initial_count
