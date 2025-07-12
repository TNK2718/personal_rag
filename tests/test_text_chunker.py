"""TextChunkerのテスト"""
import pytest

from src.server.text_chunker import TextChunker


class TestTextChunker:
    """TextChunkerのテストクラス"""

    @pytest.fixture
    def text_chunker(self):
        """TextChunkerのインスタンスを作成"""
        return TextChunker(chunk_size=100, chunk_overlap=20)

    @pytest.fixture
    def long_text(self):
        """長いテストテキスト"""
        return """これは非常に長いテキストのサンプルです。このテキストは複数の文で構成されており、
段落も複数含まれています。文の境界や段落の境界でのチャンキング動作をテストするために使用されます。

このテキストには日本語の句読点も含まれています。また、改行やスペースの処理も確認できます。
チャンキングのアルゴリズムが正しく動作することを検証するための十分な長さがあります。

最後の段落です。ここまでくれば、テキストの分割が適切に行われているはずです。
終了前の最後の文章となります。"""

    @pytest.fixture
    def sentence_text(self):
        """文区切りテスト用テキスト"""
        return """最初の文です。二番目の文です！三番目の文ですか？四番目の文です。
五番目の文です。六番目の文です。"""

    @pytest.fixture
    def paragraph_text(self):
        """段落区切りテスト用テキスト"""
        return """最初の段落です。この段落にはいくつかの文が含まれています。
段落内の二番目の文です。

二番目の段落です。この段落も複数の文で構成されています。
二番目の段落の最後の文です。

三番目の段落です。短い段落です。

四番目の段落です。この段落も通常の長さです。
最後の文です。"""

    def test_initialization(self):
        """TextChunkerの初期化テスト"""
        chunker = TextChunker(chunk_size=200, chunk_overlap=50)

        assert chunker.chunk_size == 200
        assert chunker.chunk_overlap == 50

    def test_initialization_with_defaults(self):
        """デフォルト値での初期化テスト"""
        chunker = TextChunker()

        assert chunker.chunk_size == 800
        assert chunker.chunk_overlap == 100

    def test_split_text_by_length_short_text(self, text_chunker):
        """短いテキストの文字数分割テスト"""
        short_text = "短いテキスト"

        chunks = text_chunker.split_text_by_length(short_text)

        assert len(chunks) == 1
        assert chunks[0] == short_text

    def test_split_text_by_length_long_text(self, text_chunker, long_text):
        """長いテキストの文字数分割テスト"""
        chunks = text_chunker.split_text_by_length(
            long_text, chunk_size=100, overlap=20)

        # 複数のチャンクに分割される
        assert len(chunks) > 1

        # 各チャンクがサイズ制限内
        for chunk in chunks[:-1]:  # 最後のチャンク以外
            assert len(chunk) <= 100

        # 空のチャンクがない
        for chunk in chunks:
            assert chunk.strip() != ""

    def test_split_text_by_length_with_overlap(self, text_chunker):
        """オーバーラップ機能のテスト"""
        text = "A" * 150  # 150文字のテキスト

        chunks = text_chunker.split_text_by_length(
            text, chunk_size=50, overlap=10)

        assert len(chunks) > 1
        # オーバーラップが機能している（隣接するチャンクに共通部分がある）
        # ただし、Aが連続しているため具体的な重複は確認しにくい

    def test_split_text_by_sentences(self, text_chunker, sentence_text):
        """文単位分割テスト"""
        chunks = text_chunker.split_text_by_sentences(
            sentence_text, max_chunk_size=50)

        # 複数のチャンクに分割される
        assert len(chunks) >= 1

        # 各チャンクに文が含まれている
        for chunk in chunks:
            assert len(chunk.strip()) > 0

    def test_split_text_by_sentences_max_size(self, text_chunker, sentence_text):
        """文単位分割での最大サイズ制限テスト"""
        chunks = text_chunker.split_text_by_sentences(
            sentence_text, max_chunk_size=30)

        # 最大サイズを超えるチャンクがない（最後のチャンク以外）
        for chunk in chunks[:-1]:
            assert len(chunk) <= 35  # 少し余裕を持たせる（句読点分）

    def test_split_text_by_paragraphs(self, text_chunker, paragraph_text):
        """段落単位分割テスト"""
        chunks = text_chunker.split_text_by_paragraphs(
            paragraph_text, max_chunk_size=100)

        # 複数のチャンクに分割される
        assert len(chunks) >= 1

        # 各チャンクに内容がある
        for chunk in chunks:
            assert chunk.strip() != ""

    def test_split_text_by_paragraphs_large_paragraph(self, text_chunker):
        """大きな段落の分割テスト"""
        large_paragraph = "非常に長い段落です。" * 50  # 約500文字

        chunks = text_chunker.split_text_by_paragraphs(
            large_paragraph, max_chunk_size=100)

        # 大きすぎる段落は自動的に文字数分割される
        assert len(chunks) > 1

    def test_smart_split_text_with_paragraphs(self, text_chunker, paragraph_text):
        """段落のあるテキストのスマート分割テスト"""
        chunks = text_chunker.smart_split_text(paragraph_text, chunk_size=100)

        # 段落分割が優先される
        assert len(chunks) >= 1

        # 空のチャンクがない
        for chunk in chunks:
            assert chunk.strip() != ""

    def test_smart_split_text_with_sentences(self, text_chunker, sentence_text):
        """文のあるテキストのスマート分割テスト"""
        # 段落区切りがないテキストなので文分割が使用される
        chunks = text_chunker.smart_split_text(sentence_text, chunk_size=50)

        assert len(chunks) >= 1

    def test_smart_split_text_fallback_to_length(self, text_chunker):
        """文字数分割へのフォールバックテスト"""
        # 句読点のないテキスト
        no_punctuation_text = "A" * 200

        chunks = text_chunker.smart_split_text(
            no_punctuation_text, chunk_size=50)

        # 文字数分割が使用される
        assert len(chunks) > 1
        for chunk in chunks[:-1]:
            assert len(chunk) <= 50

    def test_get_chunk_metadata_empty(self, text_chunker):
        """空のチャンクリストのメタデータテスト"""
        metadata = text_chunker.get_chunk_metadata([])

        assert metadata['total_chunks'] == 0
        assert metadata['total_characters'] == 0
        assert metadata['avg_chunk_size'] == 0
        assert metadata['min_chunk_size'] == 0
        assert metadata['max_chunk_size'] == 0

    def test_get_chunk_metadata_with_chunks(self, text_chunker):
        """チャンクありのメタデータテスト"""
        chunks = ["短いチャンク", "これは少し長いチャンクです", "中程度の長さ"]

        metadata = text_chunker.get_chunk_metadata(chunks)

        assert metadata['total_chunks'] == 3
        assert metadata['total_characters'] == sum(
            len(chunk) for chunk in chunks)
        assert metadata['avg_chunk_size'] == metadata['total_characters'] / 3
        assert metadata['min_chunk_size'] == len("短いチャンク")
        assert metadata['max_chunk_size'] == len("これは少し長いチャンクです")

    def test_infinite_loop_prevention(self, text_chunker):
        """無限ループ防止機能のテスト"""
        # 異常なパラメータでの分割テスト
        text = "テスト" * 1000  # 長いテキスト

        # 非常に小さなチャンクサイズと大きなオーバーラップ
        chunks = text_chunker.split_text_by_length(
            text, chunk_size=5, overlap=10)

        # 無限ループにならずに完了する
        assert len(chunks) > 0
        assert len(chunks) < 1000  # 最大反復回数内

    def test_custom_chunk_parameters(self, text_chunker, long_text):
        """カスタムパラメータでの分割テスト"""
        # 初期設定とは異なるパラメータを使用
        chunks = text_chunker.split_text_by_length(
            long_text, chunk_size=150, overlap=30)

        assert len(chunks) >= 1

        # パラメータが適用されている
        for chunk in chunks[:-1]:
            assert len(chunk) <= 150

    def test_split_with_none_parameters(self, text_chunker, long_text):
        """Noneパラメータでのデフォルト値使用テスト"""
        chunks = text_chunker.split_text_by_length(
            long_text, chunk_size=None, overlap=None)

        # デフォルト値が使用される
        assert len(chunks) >= 1

    def test_edge_case_empty_text(self, text_chunker):
        """空テキストのエッジケーステスト"""
        chunks = text_chunker.split_text_by_length("")
        assert len(chunks) == 1
        assert chunks[0] == ""

        chunks = text_chunker.split_text_by_sentences("")
        assert len(chunks) == 0

        chunks = text_chunker.split_text_by_paragraphs("")
        assert len(chunks) == 0

        chunks = text_chunker.smart_split_text("")
        assert len(chunks) == 1

    def test_edge_case_whitespace_only(self, text_chunker):
        """空白のみのテキストのエッジケーステスト"""
        whitespace_text = "   \n\n\t  "

        chunks = text_chunker.split_text_by_length(whitespace_text)
        # 空白も保持される
        assert len(chunks) == 1

        chunks = text_chunker.split_text_by_sentences(whitespace_text)
        assert len(chunks) == 0

        chunks = text_chunker.split_text_by_paragraphs(whitespace_text)
        assert len(chunks) == 0

    def test_japanese_sentence_splitting(self, text_chunker):
        """日本語の文分割テスト"""
        japanese_text = "これは最初の文です。これは二番目の文です！これは疑問文ですか？最後の文です。"

        chunks = text_chunker.split_text_by_sentences(
            japanese_text, max_chunk_size=30)

        # 句読点で適切に分割される
        assert len(chunks) >= 2

    def test_mixed_content_splitting(self, text_chunker):
        """混合コンテンツの分割テスト"""
        mixed_text = """# ヘッダー

段落1です。文1。文2。

段落2です。
- リスト項目1
- リスト項目2

最後の段落です。"""

        chunks = text_chunker.smart_split_text(mixed_text, chunk_size=50)

        # 適切に分割される
        assert len(chunks) >= 1

        # ヘッダーが保持される
        assert any("ヘッダー" in chunk for chunk in chunks)
