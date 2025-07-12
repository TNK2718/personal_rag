from typing import List, Optional


class TextChunker:
    """テキストの分割処理を担当するクラス"""

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100):
        """
        TextChunkerの初期化

        Args:
            chunk_size: チャンクサイズ（文字数）
            chunk_overlap: チャンク間のオーバーラップ（文字数）
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text_by_length(self, text: str,
                             chunk_size: Optional[int] = None,
                             overlap: Optional[int] = None) -> List[str]:
        """
        テキストを指定された文字数で分割する（無限ループ防止機能付き）

        Args:
            text: 分割するテキスト
            chunk_size: チャンクサイズ（文字数）（Noneの場合は初期値を使用）
            overlap: チャンク間のオーバーラップ（文字数）（Noneの場合は初期値を使用）

        Returns:
            分割されたテキストのリスト
        """
        if chunk_size is None:
            chunk_size = self.chunk_size
        if overlap is None:
            overlap = self.chunk_overlap

        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        max_iterations = 1000  # 無限ループ防止のため
        iteration_count = 0

        while start < len(text) and iteration_count < max_iterations:
            end = min(start + chunk_size, len(text))
            chunk = text[start:end]

            if chunk.strip():  # 空でないチャンクのみ追加
                chunks.append(chunk)

            # 最後のチャンクの場合は終了
            if end == len(text):
                break

            # 次のチャンクの開始位置を計算（オーバーラップを考慮）
            start = end - overlap

            # 無限ループ防止：進行がない場合は強制的に進める
            if start <= end - chunk_size:
                start = end - overlap + 1

            iteration_count += 1

        if iteration_count >= max_iterations:
            print(f"[WARNING] Text chunking reached max iterations. "
                  f"Text length: {len(text)}, Chunks created: {len(chunks)}")

        return chunks

    def split_text_by_sentences(self, text: str,
                                max_chunk_size: Optional[int] = None) -> List[str]:
        """
        テキストを文単位で分割する

        Args:
            text: 分割するテキスト
            max_chunk_size: 最大チャンクサイズ（文字数）

        Returns:
            分割されたテキストのリスト
        """
        if max_chunk_size is None:
            max_chunk_size = self.chunk_size

        # 日本語の文区切りを考慮した正規表現
        import re
        sentences = re.split(r'[。！？\.\!\?]', text)

        chunks = []
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # 現在のチャンクに追加した場合の長さを計算
            if current_chunk:
                potential_chunk = current_chunk + "。" + sentence
            else:
                potential_chunk = sentence

            # 最大サイズを超える場合は現在のチャンクを確定
            if len(potential_chunk) > max_chunk_size and current_chunk:
                chunks.append(current_chunk)
                current_chunk = sentence
            else:
                current_chunk = potential_chunk

        # 最後のチャンクを追加
        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def split_text_by_paragraphs(self, text: str,
                                 max_chunk_size: Optional[int] = None) -> List[str]:
        """
        テキストを段落単位で分割する

        Args:
            text: 分割するテキスト
            max_chunk_size: 最大チャンクサイズ（文字数）

        Returns:
            分割されたテキストのリスト
        """
        if max_chunk_size is None:
            max_chunk_size = self.chunk_size

        # 段落で分割（2つ以上の改行で区切り）
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

        chunks = []
        current_chunk = ""

        for paragraph in paragraphs:
            # 現在のチャンクに追加した場合の長さを計算
            if current_chunk:
                potential_chunk = current_chunk + "\n\n" + paragraph
            else:
                potential_chunk = paragraph

            # 最大サイズを超える場合
            if len(potential_chunk) > max_chunk_size:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = paragraph
                else:
                    # 段落自体が大きすぎる場合は文字数で分割
                    para_chunks = self.split_text_by_length(
                        paragraph, max_chunk_size)
                    chunks.extend(para_chunks)
            else:
                current_chunk = potential_chunk

        # 最後のチャンクを追加
        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def smart_split_text(self, text: str,
                         chunk_size: Optional[int] = None,
                         overlap: Optional[int] = None) -> List[str]:
        """
        テキストを適切な方法で分割する（段落→文→文字の順で試行）

        Args:
            text: 分割するテキスト
            chunk_size: チャンクサイズ（文字数）
            overlap: チャンク間のオーバーラップ（文字数）

        Returns:
            分割されたテキストのリスト
        """
        if chunk_size is None:
            chunk_size = self.chunk_size
        if overlap is None:
            overlap = self.chunk_overlap

        # 段落分割を優先
        if '\n\n' in text:
            chunks = self.split_text_by_paragraphs(text, chunk_size)
        # 文分割を次に試行
        elif any(delimiter in text for delimiter in ['。', '！', '？', '.', '!', '?']):
            chunks = self.split_text_by_sentences(text, chunk_size)
        # 最後に文字数分割
        else:
            chunks = self.split_text_by_length(text, chunk_size, overlap)

        return chunks

    def get_chunk_metadata(self, chunks: List[str]) -> dict:
        """
        チャンクのメタデータを取得する

        Args:
            chunks: チャンクのリスト

        Returns:
            メタデータの辞書
        """
        if not chunks:
            return {
                'total_chunks': 0,
                'total_characters': 0,
                'avg_chunk_size': 0,
                'min_chunk_size': 0,
                'max_chunk_size': 0
            }

        chunk_sizes = [len(chunk) for chunk in chunks]

        return {
            'total_chunks': len(chunks),
            'total_characters': sum(chunk_sizes),
            'avg_chunk_size': sum(chunk_sizes) / len(chunk_sizes),
            'min_chunk_size': min(chunk_sizes),
            'max_chunk_size': max(chunk_sizes)
        }
