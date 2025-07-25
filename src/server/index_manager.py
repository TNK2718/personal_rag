import os
import faiss  # type: ignore
from typing import List
from llama_index.core import (
    VectorStoreIndex,
    StorageContext,
    Settings,
    load_index_from_storage,
    Document,
)
from llama_index.core.schema import TextNode
from llama_index.vector_stores.faiss import FaissVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding


class IndexManager:
    """インデックスの管理、永続化を担当するクラス"""

    def __init__(self, persist_dir: str, embedding_dim: int = 768):
        """
        IndexManagerの初期化

        Args:
            persist_dir: 永続化ディレクトリ
            embedding_dim: 埋め込みベクトルの次元数
        """
        self.persist_dir = persist_dir
        self.embedding_dim = embedding_dim
        self.faiss_index_path = os.path.join(persist_dir, "faiss_index.bin")

        # LLMの設定
        self.llm = Ollama(
            model="hf.co/mmnga/sarashina2.2-3b-instruct-v0.1-gguf:latest",
            request_timeout=120.0,
            system_prompt=(
                "あなたは親切で知識豊富なアシスタントです。以下のルールに従って回答してください：\n\n"
                "1. **言語**: 必ず日本語で回答してください。\n"
                "2. **簡潔に**: クエリに対する回答のみを会話のように簡潔に出力してください。\n"
                "3. **情報源**: 提供された文脈（コンテキスト）の情報を基に回答してください。コンテキストについて冗長な説明は含めないこと。\n"
                "4. **不明な場合**: 文脈に情報がない場合は「提供された情報からは判断できません」と明記してください。\n"
                "5. **構造化**: 複数の要点がある場合は、箇条書きや番号付きリストを使用して整理してください。\n"
            )
        )
        Settings.llm = self.llm

        # Embedding Modelの設定
        self.embed_model = OllamaEmbedding(model_name="nomic-embed-text")
        Settings.embed_model = self.embed_model

    def initialize_index(self) -> VectorStoreIndex:
        """
        インデックスを初期化する

        Returns:
            VectorStoreIndex
        """
        # 既存のインデックスを読み込み
        if os.path.exists(self.persist_dir):
            try:
                return self._load_index()
            except Exception as e:
                print(f"[DEBUG] Failed to load existing index: {e}")
                print("[DEBUG] Creating new index...")

        # 新しいインデックスを作成
        return self._create_new_index()

    def _load_index(self) -> VectorStoreIndex:
        """
        既存のインデックスを読み込む

        Returns:
            VectorStoreIndex
        """
        print(f"[DEBUG] Loading existing index from {self.persist_dir}")

        # FAISSインデックスファイルが存在するかチェック
        if not os.path.exists(self.faiss_index_path):
            print(f"[DEBUG] FAISS index file not found: "
                  f"{self.faiss_index_path}")
            return self._create_new_index()

        try:
            # FAISSインデックスを読み込み
            faiss_index = faiss.read_index(self.faiss_index_path)
            print(
                f"[DEBUG] Loaded FAISS index with {faiss_index.ntotal} vectors")

            # VectorStoreを作成
            vector_store = FaissVectorStore(faiss_index=faiss_index)
            storage_context = StorageContext.from_defaults(
                vector_store=vector_store, persist_dir=self.persist_dir
            )

            # インデックスを読み込み
            index = load_index_from_storage(storage_context)
            print("[DEBUG] Successfully loaded index from storage")

            return index
        except Exception as e:
            print(f"[DEBUG] Error loading index: {e}")
            raise

    def _create_new_index(self) -> VectorStoreIndex:
        """
        新しいインデックスを作成する

        Returns:
            VectorStoreIndex
        """
        print("[DEBUG] Creating new index")

        # 新しいFAISSインデックスを作成
        faiss_index = faiss.IndexFlatL2(self.embedding_dim)

        # VectorStoreを作成
        vector_store = FaissVectorStore(faiss_index=faiss_index)
        storage_context = StorageContext.from_defaults(
            vector_store=vector_store)

        # 空のインデックスを作成
        index = VectorStoreIndex([], storage_context=storage_context)

        # 作成したインデックスを永続化
        self._save_index(faiss_index, storage_context)

        print("[DEBUG] Created new index")
        return index

    def _save_index(self, faiss_index: faiss.Index,
                    storage_context: StorageContext) -> None:
        """
        インデックスを永続化する

        Args:
            faiss_index: FAISSインデックス
            storage_context: ストレージコンテキスト
        """
        os.makedirs(self.persist_dir, exist_ok=True)
        faiss.write_index(faiss_index, self.faiss_index_path)
        storage_context.persist(persist_dir=self.persist_dir)
        print(f"[DEBUG] Saved index to {self.persist_dir}")

    def add_documents(self, index: VectorStoreIndex,
                      documents: List[Document]) -> None:
        """
        インデックスにドキュメントを追加する

        Args:
            index: 対象のインデックス
            documents: 追加するドキュメント
        """
        if not documents:
            print("[DEBUG] No documents to add")
            return

        print(f"[DEBUG] Adding {len(documents)} documents to index")

        # ドキュメントをインデックスに追加
        for doc in documents:
            index.insert(doc)

        # インデックスを永続化
        self._persist_index(index)

        print("[DEBUG] Documents added successfully")

    def add_nodes(self, index: VectorStoreIndex, nodes: List[TextNode]) -> None:
        """
        インデックスにノードを追加する

        Args:
            index: 対象のインデックス
            nodes: 追加するノード
        """
        if not nodes:
            print("[DEBUG] No nodes to add")
            return

        print(f"[DEBUG] Adding {len(nodes)} nodes to index")

        # ノードをインデックスに追加
        for node in nodes:
            index.insert(node)

        # インデックスを永続化
        self._persist_index(index)

        print("[DEBUG] Nodes added successfully")

    def _persist_index(self, index: VectorStoreIndex) -> None:
        """
        インデックスを永続化する

        Args:
            index: 永続化するインデックス
        """
        # ストレージコンテキストを取得
        storage_context = index.storage_context

        # FAISSインデックスを取得する複数の方法を試す
        faiss_index = None

        # 方法1: _faiss_index属性（最も確実）
        if hasattr(storage_context.vector_store, '_faiss_index'):
            faiss_index = storage_context.vector_store._faiss_index

        # 方法2: faiss_index属性
        elif hasattr(storage_context.vector_store, 'faiss_index'):
            faiss_index = storage_context.vector_store.faiss_index

        if faiss_index is not None:
            self._save_index(faiss_index, storage_context)
        else:
            print("[DEBUG] Warning: Could not access FAISS index")
            # ストレージコンテキストだけでも保存
            storage_context.persist(persist_dir=self.persist_dir)

    def create_query_engine(self, index: VectorStoreIndex,
                            top_k: int = 5):
        """
        クエリエンジンを作成する

        Args:
            index: 対象のインデックス
            top_k: 取得する関連文書数

        Returns:
            クエリエンジン
        """
        return index.as_query_engine(
            similarity_top_k=top_k,
            response_mode="compact",
            streaming=False
        )

    def create_retriever(self, index: VectorStoreIndex,
                         top_k: int = 5):
        """
        リトリーバーを作成する

        Args:
            index: 対象のインデックス
            top_k: 取得する関連文書数

        Returns:
            リトリーバー
        """
        return index.as_retriever(similarity_top_k=top_k)

    def get_index_stats(self, index: VectorStoreIndex) -> dict:
        """
        インデックスの統計情報を取得する

        Args:
            index: 対象のインデックス

        Returns:
            統計情報の辞書
        """
        stats = {
            'total_documents': 0,
            'total_nodes': 0,
            'vector_dimension': self.embedding_dim,
            'storage_path': self.persist_dir
        }

        try:
            # FAISSインデックスから統計情報を取得
            storage_context = index.storage_context
            if hasattr(storage_context.vector_store, 'faiss_index'):
                faiss_index = storage_context.vector_store.faiss_index
                stats['total_documents'] = faiss_index.ntotal
                stats['total_nodes'] = faiss_index.ntotal
        except Exception as e:
            print(f"[DEBUG] Error getting index stats: {e}")

        return stats

    def refresh_index(self, index: VectorStoreIndex) -> VectorStoreIndex:
        """
        インデックスをリフレッシュする（完全に再作成）

        Args:
            index: 現在のインデックス

        Returns:
            新しいインデックス
        """
        print("[DEBUG] Refreshing index...")

        # 既存のインデックスファイルを削除
        if os.path.exists(self.faiss_index_path):
            os.remove(self.faiss_index_path)

        # 新しいインデックスを作成
        return self._create_new_index()

    def delete_index(self) -> None:
        """
        インデックスを削除する
        """
        if os.path.exists(self.persist_dir):
            import shutil
            shutil.rmtree(self.persist_dir)
            print(f"[DEBUG] Deleted index directory: {self.persist_dir}")

    def is_index_empty(self, index: VectorStoreIndex) -> bool:
        """
        インデックスが空かどうかを確認する

        Args:
            index: 確認するインデックス

        Returns:
            空の場合True
        """
        try:
            storage_context = index.storage_context

            # 方法1: _faiss_index属性をチェック（最も確実）
            if hasattr(storage_context.vector_store, '_faiss_index'):
                faiss_index = storage_context.vector_store._faiss_index
                vector_count = faiss_index.ntotal
                print(
                    f"[DEBUG] Index has {vector_count} vectors via _faiss_index")
                return vector_count == 0

            # 方法2: faiss_index属性をチェック
            elif hasattr(storage_context.vector_store, 'faiss_index'):
                faiss_index = storage_context.vector_store.faiss_index
                vector_count = faiss_index.ntotal
                print(
                    f"[DEBUG] Index has {vector_count} vectors via faiss_index")
                return vector_count == 0

            print("[DEBUG] Could not access FAISS index for empty check")
            return True
        except Exception as e:
            print(f"[DEBUG] Error checking if index is empty: {e}")
            return True
