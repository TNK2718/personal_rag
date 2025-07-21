from typing import List, Optional, Dict, Any
import re


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

    def split_text_with_todo_boundaries(self, text: str) -> List[str]:
        """
        TODOパターンを境界としてテキストを分割する
        
        Args:
            text: 分割するテキスト
            
        Returns:
            TODOパターンで分割されたテキストのリスト
        """
        if not text.strip():
            return []
        
        # TODOパターンを定義（より厳密に）
        todo_patterns = [
            r'\b(?:TODO|Todo|todo)\s*:\s*(.+?)(?=\n|$)',
            r'\b(?:FIXME|Fixme|fixme)\s*:\s*(.+?)(?=\n|$)',
            r'\b(?:BUG|Bug|bug)\s*:\s*(.+?)(?=\n|$)',
            r'\b(?:HACK|Hack|hack)\s*:\s*(.+?)(?=\n|$)',
            r'\b(?:NOTE|Note|note)\s*:\s*(.+?)(?=\n|$)',
            r'\b(?:XXX|xxx)\s*:\s*(.+?)(?=\n|$)',
            r'- \[ \]\s*(.+?)(?=\n|$)',  # Markdownチェックボックス
            r'- \[x\]\s*(.+?)(?=\n|$)',  # 完了チェックボックス
            r'^\s*[\*\-]\s*(?:TODO|Todo|todo)\s*:?\s*(.+?)(?=\n|$)',  # リストアイテムのTODO
            r'^\s*[\*\-]\s*(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?=\n|$)',  # リストアイテムのFIXME
            r'^\s*[\*\-]\s*(?:BUG|Bug|bug)\s*:?\s*(.+?)(?=\n|$)',  # リストアイテムのBUG
            r'^\s*[\*\-]\s*(?:NOTE|Note|note)\s*:?\s*(.+?)(?=\n|$)',  # リストアイテムのNOTE
            r'^\s*[\*\-]\s*(?:HACK|Hack|hack)\s*:?\s*(.+?)(?=\n|$)',  # リストアイテムのHACK
            r'^\s*[\*\-]\s*(?:XXX|xxx)\s*:?\s*(.+?)(?=\n|$)'  # リストアイテムのXXX
        ]
        
        # 全てのTODOパターンを検索
        todo_matches = []
        for pattern in todo_patterns:
            for match in re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE):
                todo_matches.append((match.start(), match.end(), match.group(0)))
        
        # 位置でソート
        todo_matches.sort(key=lambda x: x[0])
        
        if not todo_matches:
            # TODOがない場合は通常のチャンク分割
            return self.smart_split_text(text)
        
        chunks = []
        last_end = 0
        
        for start, end, todo_text in todo_matches:
            # TODO前のテキスト
            before_todo = text[last_end:start].strip()
            if before_todo:
                chunks.extend(self.smart_split_text(before_todo))
            
            # TODO部分（行全体を含む）
            line_start = text.rfind('\n', 0, start) + 1  # 行の始まり
            line_end = text.find('\n', end)  # 行の終わり
            if line_end == -1:
                line_end = len(text)
            
            todo_chunk = text[line_start:line_end].strip()
            if todo_chunk:
                chunks.append(todo_chunk)
            
            last_end = line_end
        
        # 最後のTODO後のテキスト
        after_last_todo = text[last_end:].strip()
        if after_last_todo:
            chunks.extend(self.smart_split_text(after_last_todo))
        
        return chunks

    def split_text_by_bullet_items(self, text: str) -> List[str]:
        """
        箇条書きを1つ1チャンクに分割する
        
        Args:
            text: 分割するテキスト
            
        Returns:
            箇条書きで分割されたテキストのリスト
        """
        if not text.strip():
            return []
        
        # 箇条書きパターンを定義
        bullet_pattern = r'^(\s*[*\-+]\s+.+?)(?=\n\s*[*\-+]\s+|\n\s*$|\Z)'
        
        # 箇条書きを検索
        bullet_matches = list(re.finditer(bullet_pattern, text, re.MULTILINE | re.DOTALL))
        
        if not bullet_matches:
            # 箇条書きがない場合は通常のチャンク分割
            return self.smart_split_text(text)
        
        chunks = []
        last_end = 0
        
        for match in bullet_matches:
            # 箇条書き前のテキスト
            before_bullet = text[last_end:match.start()].strip()
            if before_bullet:
                chunks.extend(self.smart_split_text(before_bullet))
            
            # 箇条書き項目（1つの項目を1チャンクに）
            bullet_item = match.group(1).strip()
            if bullet_item:
                chunks.append(bullet_item)
            
            last_end = match.end()
        
        # 最後の箇条書き後のテキスト
        after_last_bullet = text[last_end:].strip()
        if after_last_bullet:
            chunks.extend(self.smart_split_text(after_last_bullet))
        
        return chunks

    def create_chunks_with_todo_metadata(self, text: str, file_path: str, section_id: int) -> List[Dict[str, Any]]:
        """
        TODOメタデータ付きのチャンクを作成する
        
        Args:
            text: 分割するテキスト
            file_path: ファイルパス
            section_id: セクションID
            
        Returns:
            メタデータ付きチャンクのリスト
        """
        if not text.strip():
            return []
        
        # 箇条書きを考慮したチャンク分割
        chunks = self.split_text_by_bullet_items(text)
        chunks_with_metadata = []
        
        # TODOパターンを定義（より厳密に）
        todo_patterns = [
            (r'\b(?:TODO|Todo|todo)\s*:\s*(.+?)(?=\n|$)', 'TODO'),
            (r'\b(?:FIXME|Fixme|fixme)\s*:\s*(.+?)(?=\n|$)', 'FIXME'),
            (r'\b(?:BUG|Bug|bug)\s*:\s*(.+?)(?=\n|$)', 'BUG'),
            (r'\b(?:HACK|Hack|hack)\s*:\s*(.+?)(?=\n|$)', 'HACK'),
            (r'\b(?:NOTE|Note|note)\s*:\s*(.+?)(?=\n|$)', 'NOTE'),
            (r'\b(?:XXX|xxx)\s*:\s*(.+?)(?=\n|$)', 'XXX'),
            (r'- \[ \]\s*(.+?)(?=\n|$)', 'CHECKBOX'),
            (r'- \[x\]\s*(.+?)(?=\n|$)', 'CHECKBOX_COMPLETED'),
            (r'^\s*[\*\-]\s*(?:TODO|Todo|todo)\s*:?\s*(.+?)(?=\n|$)', 'TODO'),
            (r'^\s*[\*\-]\s*(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?=\n|$)', 'FIXME'),
            (r'^\s*[\*\-]\s*(?:BUG|Bug|bug)\s*:?\s*(.+?)(?=\n|$)', 'BUG'),
            (r'^\s*[\*\-]\s*(?:NOTE|Note|note)\s*:?\s*(.+?)(?=\n|$)', 'NOTE'),
            (r'^\s*[\*\-]\s*(?:HACK|Hack|hack)\s*:?\s*(.+?)(?=\n|$)', 'HACK'),
            (r'^\s*[\*\-]\s*(?:XXX|xxx)\s*:?\s*(.+?)(?=\n|$)', 'XXX')
        ]
        
        for i, chunk_text in enumerate(chunks):
            chunk_id = f"{file_path}:section_{section_id}:chunk_{i}"
            
            # TODOの検出
            has_todo = False
            todo_type = None
            todo_content = None
            todo_priority = 'medium'
            
            for pattern, pattern_type in todo_patterns:
                match = re.search(pattern, chunk_text, re.MULTILINE | re.IGNORECASE)
                if match:
                    has_todo = True
                    todo_type = pattern_type
                    todo_content = match.group(1).strip()
                    
                    # 優先度の推定
                    urgent_words = ['urgent', '急', '緊急', 'asap']
                    later_words = ['later', '後で', '将来']
                    
                    if any(word in chunk_text.lower() for word in urgent_words):
                        todo_priority = 'high'
                    elif any(word in chunk_text.lower() for word in later_words):
                        todo_priority = 'low'
                    
                    break
            
            # コンテキストキーワードの抽出
            context_keywords = []
            if has_todo and todo_content:
                # 簡単なキーワード抽出（カタカナ、英単語、重要そうな日本語）
                keywords = re.findall(r'[ァ-ヶー]+|[A-Za-z]+|[重要|実装|修正|バグ|機能|API|エンドポイント]', chunk_text)
                context_keywords = list(set(keywords))
            
            metadata = {
                'chunk_id': chunk_id,
                'file_path': file_path,
                'section_id': section_id,
                'chunk_index': i,
                'has_todo': has_todo,
                'todo_type': todo_type,
                'todo_content': todo_content,
                'todo_priority': todo_priority,
                'context_keywords': context_keywords
            }
            
            chunks_with_metadata.append({
                'text': chunk_text,
                'metadata': metadata
            })
        
        return chunks_with_metadata

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
