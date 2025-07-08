import os
import faiss  # type: ignore
from typing import Optional, List, cast
from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    Settings,
    load_index_from_storage,
    Document,
)
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

    def _initialize_index(self) -> VectorStoreIndex:
        """インデックスの初期化（読み込みまたは新規作成）"""
        # 永続化ディレクトリの作成
        os.makedirs(self.persist_dir, exist_ok=True)

        try:
            return self._load_index()
        except Exception as e:
            print(f"インデックスの読み込みに失敗しました: {e}")
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
        print("インデックスを新規に作成し、保存しました。")
        return index

    def load_documents(self, data_dir: Optional[str] = None) -> List[Document]:
        """ドキュメントを読み込む"""
        target_dir = data_dir or self.data_dir
        return SimpleDirectoryReader(target_dir).load_data()

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
        query_engine = self.index.as_query_engine(
            system_prompt="あなたは親切なアシスタントです。与えられた文脈に基づいて、日本語で簡潔に回答してください。"
        )
        response = query_engine.query(query_text)
        return str(response)

    def run_interactive(self) -> None:
        """インタラクティブな質問応答を実行する"""
        print("\n--- 質問応答開始 ---")
        print("終了するには 'exit' または 'quit' と入力してください。")

        while True:
            query_text = input("質問を入力してください: ")
            if query_text.lower() in ["exit", "quit"]:
                break

            response = self.query(query_text)
            print("\n回答:")
            print(response)
            print("-" * 20)


def main():
    """メイン関数"""
    rag = RAGSystem()
    rag.run_interactive()


if __name__ == "__main__":
    main()
