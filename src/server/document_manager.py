import os
import json
import hashlib
from typing import Optional, List, Dict
from llama_index.core import Document, SimpleDirectoryReader


class DocumentManager:
    """ドキュメント管理を担当するクラス"""

    def __init__(self, data_dir: str, persist_dir: str,
                 hash_file: str = "document_hashes.json"):
        """
        DocumentManagerの初期化

        Args:
            data_dir: 入力データのディレクトリ
            persist_dir: 永続化ディレクトリ
            hash_file: ハッシュファイル名
        """
        self.data_dir = data_dir
        self.persist_dir = persist_dir
        self.hash_file_path = os.path.join(persist_dir, hash_file)
        self.chunk_hash_file_path = os.path.join(
            persist_dir, "chunk_hashes.json")
        self.document_hashes: Dict[str, str] = self._load_document_hashes()
        self.chunk_hashes: Dict[str, str] = self.load_chunk_hashes()

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

    def calculate_chunk_hash(self, chunk_text: str) -> str:
        """チャンクのハッシュ値を計算する"""
        return hashlib.md5(chunk_text.encode('utf-8')).hexdigest()

    def load_chunk_hashes(self) -> Dict[str, str]:
        """保存されているチャンクハッシュを読み込む"""
        if os.path.exists(self.chunk_hash_file_path):
            with open(self.chunk_hash_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_chunk_hashes(self, chunk_hashes: Dict[str, str]) -> None:
        """チャンクハッシュを保存する"""
        os.makedirs(self.persist_dir, exist_ok=True)
        with open(self.chunk_hash_file_path, 'w', encoding='utf-8') as f:
            json.dump(chunk_hashes, f, ensure_ascii=False, indent=2)
        self.chunk_hashes = chunk_hashes

    def check_chunk_updates(self, new_chunks: List[Dict]) -> List[Dict]:
        """チャンクレベルの更新をチェックする"""
        updated_chunks = []

        for chunk in new_chunks:
            chunk_id = chunk["id"]
            chunk_text = chunk["text"]
            current_hash = self.calculate_chunk_hash(chunk_text)
            stored_hash = self.chunk_hashes.get(chunk_id)

            if stored_hash != current_hash:
                updated_chunks.append(chunk)
                self.chunk_hashes[chunk_id] = current_hash

        return updated_chunks

    def get_chunk_metadata(self, chunk_id: str) -> Dict:
        """チャンクIDからメタデータを取得する"""
        parts = chunk_id.split(':')
        if len(parts) >= 3:
            return {
                "doc_id": parts[0],
                "section_id": int(parts[1].split('_')[1]),
                "chunk_id": int(parts[2].split('_')[1])
            }
        return {"doc_id": chunk_id, "section_id": 0, "chunk_id": 0}

    def remove_deleted_chunks(self, current_chunks: List[Dict]) -> List[str]:
        """削除されたチャンクを除去し、そのIDリストを返す"""
        current_chunk_ids = {chunk["id"] for chunk in current_chunks}
        stored_chunk_ids = set(self.chunk_hashes.keys())

        deleted_chunk_ids = stored_chunk_ids - current_chunk_ids

        # 削除されたチャンクのハッシュを除去
        for chunk_id in deleted_chunk_ids:
            del self.chunk_hashes[chunk_id]

        # 更新されたハッシュを保存
        self.save_chunk_hashes(self.chunk_hashes)

        return list(deleted_chunk_ids)

    def get_relative_path(self, file_path: str) -> str:
        """フルパスを相対パス（dataディレクトリ基準）に変換する"""
        if not file_path:
            return file_path

        # dataディレクトリ基準の相対パスを取得
        try:
            # dataディレクトリの絶対パスを取得
            abs_data_dir = os.path.abspath(self.data_dir)
            abs_file_path = os.path.abspath(file_path)

            # dataディレクトリ内のファイルかチェック
            if abs_file_path.startswith(abs_data_dir):
                rel_path = os.path.relpath(abs_file_path, abs_data_dir)
                # Windowsのバックスラッシュをスラッシュに変換
                rel_path = rel_path.replace(os.sep, '/')
                print(f"[DEBUG] Path conversion: {file_path} -> {rel_path}")
                return rel_path
        except (ValueError, TypeError) as e:
            print(f"[DEBUG] Path conversion error: {e}")
            pass

        # フォールバック: ファイル名のみを返す
        fallback = os.path.basename(file_path)
        print(f"[DEBUG] Path conversion fallback: {file_path} -> {fallback}")
        return fallback

    def check_document_updates(self) -> List[str]:
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

    def save_document_hashes(self) -> None:
        """ドキュメントハッシュを保存する（外部から呼び出し可能）"""
        self._save_document_hashes()

    def load_documents(self, data_dir: Optional[str] = None) -> List[Document]:
        """
        指定されたディレクトリからドキュメントを読み込む

        Args:
            data_dir: 読み込み元ディレクトリ（Noneの場合は初期化時のディレクトリを使用）

        Returns:
            読み込んだドキュメントのリスト
        """
        target_dir = data_dir if data_dir else self.data_dir

        # ディレクトリが存在しない場合の処理
        if not os.path.exists(target_dir):
            print(f"[DEBUG] Directory does not exist: {target_dir}")
            return []

        # ディレクトリ内にファイルがない場合の処理
        files = []
        for root, _, filenames in os.walk(target_dir):
            for filename in filenames:
                if filename.endswith('.md'):
                    files.append(os.path.join(root, filename))

        if not files:
            print(f"[DEBUG] No .md files found in: {target_dir}")
            return []

        print(f"[DEBUG] Loading {len(files)} files from {target_dir}")
        try:
            loader = SimpleDirectoryReader(
                input_dir=target_dir,
                required_exts=[".md"],
                recursive=True
            )
            documents = loader.load_data()
            print(f"[DEBUG] Successfully loaded {len(documents)} documents")
            return documents
        except Exception as e:
            print(f"[DEBUG] Error loading documents: {e}")
            return []

    def get_all_document_files(self) -> List[str]:
        """データディレクトリ内のすべてのMarkdownファイルのパスを取得する"""
        files = []
        for root, _, filenames in os.walk(self.data_dir):
            for filename in filenames:
                if filename.endswith('.md'):
                    files.append(os.path.join(root, filename))
        return files
