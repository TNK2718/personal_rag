import os
import json
import hashlib
import faiss  # type: ignore
from typing import Optional, List, Dict, cast
from dataclasses import dataclass
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

# =================================
# 設定
# =================================
# デフォルト設定
DEFAULT_PERSIST_DIR = "./storage"
DEFAULT_DATA_DIR = "./data"
DEFAULT_EMBEDDING_DIM = 768  # nomic-embed-textの次元数
HASH_FILE = "document_hashes.json"


@dataclass
class MarkdownSection:
    """Markdownセクションを表すデータクラス"""
    header: str
    content: str
    level: int  # ヘッダーレベル (h1=1, h2=2, etc.)


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
        self.md_parser = MarkdownIt()
        self.document_hashes: Dict[str, str] = self._load_document_hashes()

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

    def _calculate_file_hash(self, file_path: str) -> str:
        """ファイルのハッシュ値を計算する"""
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def _check_document_updates(self) -> List[str]:
        """更新のあったドキュメントのパスを取得する"""
        updated_files = []
        for root, _, files in os.walk(self.data_dir):
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
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
                # 新しいセクションの開始
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

        # 最後のセクションを追加
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
        for i, section in enumerate(sections):
            # ヘッダーノード
            header_node = TextNode(
                text=section.header,
                metadata={
                    "doc_id": doc_id,
                    "section_id": i,
                    "type": "header",
                    "level": section.level
                }
            )

            # コンテンツノード
            content_node = TextNode(
                text=section.content,
                metadata={
                    "doc_id": doc_id,
                    "section_id": i,
                    "type": "content",
                    "header": section.header,
                    "level": section.level
                }
            )

            nodes.extend([header_node, content_node])

        return nodes

    def _initialize_index(self) -> VectorStoreIndex:
        """インデックスの初期化（読み込みまたは新規作成）"""
        os.makedirs(self.persist_dir, exist_ok=True)

        try:
            # 更新のあったドキュメントをチェック
            updated_files = self._check_document_updates()

            if os.path.exists(self.faiss_index_path):
                # 既存のインデックスを読み込む
                index = self._load_index()
                print("既存のインデックスを読み込みました。")

                # 更新があれば処理
                if updated_files:
                    print(f"{len(updated_files)}個のファイルが更新されています。")

                    # 新しいインデックスを作成
                    faiss_index = faiss.IndexFlatL2(self.embedding_dim)
                    vector_store = FaissVectorStore(faiss_index=faiss_index)
                    storage_context = StorageContext.from_defaults(
                        vector_store=vector_store
                    )

                    # 更新されていないドキュメントを保持
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

                    # 更新されたドキュメントを処理
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

                    # 新しいインデックスを作成
                    index = VectorStoreIndex.from_documents(
                        all_documents,
                        storage_context=storage_context
                    )

                    # インデックスを保存
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

        # Faissインデックスの読み込み
        faiss_index = faiss.read_index(self.faiss_index_path)
        vector_store = FaissVectorStore(faiss_index=faiss_index)

        # StorageContextの作成とインデックスの読み込み
        storage_context = StorageContext.from_defaults(
            vector_store=vector_store,
            persist_dir=self.persist_dir
        )
        index = load_index_from_storage(storage_context)
        print("既存のインデックスを読み込みました。")
        return cast(VectorStoreIndex, index)

    def _create_new_index(self) -> VectorStoreIndex:
        """新しいインデックスを作成する"""
        # ドキュメントの読み込み
        documents = self.load_documents()

        # Faissのインデックスを作成
        faiss_index = faiss.IndexFlatL2(self.embedding_dim)
        vector_store = FaissVectorStore(faiss_index=faiss_index)
        storage_context = StorageContext.from_defaults(
            vector_store=vector_store)

        # インデックスを構築
        index = VectorStoreIndex.from_documents(
            documents, storage_context=storage_context
        )

        # インデックスの永続化
        self._save_index(faiss_index, storage_context)

        # ドキュメントハッシュの保存
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

    def query(self, query_text: str) -> str:
        """質問に対する回答を生成する"""
        # クエリに対してヘッダーとコンテンツの両方の類似度を計算
        retriever = self.index.as_retriever(
            similarity_top_k=3  # 各タイプから上位3件を取得
        )

        # ヘッダーとコンテンツの両方に対して検索を実行
        nodes = []

        # ヘッダーノードの検索
        header_nodes = [
            node for node in retriever.retrieve(query_text)
            if node.metadata.get("type") == "header"
        ]

        # 関連するコンテンツノードの検索
        content_nodes = [
            node for node in retriever.retrieve(query_text)
            if node.metadata.get("type") == "content"
        ]

        # ヘッダーとコンテンツを組み合わせて、レベルとスコアでソート
        nodes = header_nodes + content_nodes
        nodes.sort(key=lambda x: (
            x.metadata.get("level", 999),
            -(x.score or 0.0)  # スコアがNoneの場合は0.0を使用
        ))

        # クエリエンジンの作成と実行
        query_engine = self.index.as_query_engine(
            streaming=True,  # ストリーミングを有効化
            similarity_top_k=3,
            system_prompt="""あなたは親切なアシスタントです。
与えられた文脈に基づいて、日本語で簡潔に回答してください。
特に、ヘッダー情報を参考にして、文書の構造を意識した回答を心がけてください。
関連するヘッダーがある場合は、その情報も含めて回答してください。"""
        )

        response = query_engine.query(query_text)
        return str(response)

    def run_interactive(self) -> None:
        """インタラクティブな質問応答を実行する"""
        print("\n--- 質問応答開始 ---")
        print("終了するには 'exit' または 'quit' と入力してください。")

        while True:
            query_text = input("\n質問を入力してください: ")
            if query_text.lower() in ["exit", "quit"]:
                break

            print("\n回答:")

            # クエリエンジンの作成
            query_engine = self.index.as_query_engine(
                similarity_top_k=3,
                system_prompt="""あなたは親切なアシスタントです。
与えられた文脈に基づいて、日本語で簡潔に回答してください。
特に、ヘッダー情報を参考にして、文書の構造を意識した回答を心がけてください。
関連するヘッダーがある場合は、その情報も含めて回答してください。
できるだけ短い単位で区切って回答を生成してください。"""
            )

            # 回答の生成と出力
            response = query_engine.query(query_text)
            response_text = str(response)

            # 文字単位でストリーミング出力
            for char in response_text:
                print(char, end="", flush=True)
                if char in ["。", "、", "！", "？", "\n"]:
                    from time import sleep
                    sleep(0.1)  # 区切り文字で少し待機

            print("\n" + "-" * 20)


def main():
    """メイン関数"""
    rag = RAGSystem()
    rag.run_interactive()


if __name__ == "__main__":
    main()
