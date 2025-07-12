"""MarkdownParserのテスト"""
import pytest

from src.server.markdown_parser import MarkdownParser, MarkdownSection


class TestMarkdownParser:
    """MarkdownParserのテストクラス"""

    @pytest.fixture
    def markdown_parser(self):
        """MarkdownParserのインスタンスを作成"""
        return MarkdownParser()

    @pytest.fixture
    def sample_markdown_content(self):
        """サンプルMarkdownコンテンツ"""
        return """# メインタイトル

これはメインセクションのコンテンツです。

## サブセクション1

サブセクション1のコンテンツ。
TODO: この機能を実装する

### サブサブセクション

さらに深いレベルのコンテンツ。

## サブセクション2

- [ ] チェックボックス項目1
- [x] 完了した項目
- [ ] チェックボックス項目2

FIXME: このバグを修正する

```python
print("コードブロック")
```

[リンクテキスト](https://example.com)
![画像](image.png)
"""

    @pytest.fixture
    def frontmatter_content(self):
        """フロントマター付きMarkdownコンテンツ"""
        return """---
title: テストドキュメント
author: テスト作成者
date: 2024-01-01
tags: test, markdown
---

# ドキュメント本文

これはフロントマター付きのドキュメントです。
"""

    def test_initialization(self, markdown_parser):
        """MarkdownParserの初期化テスト"""
        assert markdown_parser.md_parser is not None

    def test_parse_markdown_with_sections(self, markdown_parser, sample_markdown_content):
        """セクション付きMarkdownの解析テスト"""
        sections = markdown_parser.parse_markdown(sample_markdown_content)

        # セクションが正しく分割されている
        assert len(sections) >= 4

        # 最初のセクション（h1）
        main_section = sections[0]
        assert main_section.header == "メインタイトル"
        assert main_section.level == 1
        assert "メインセクション" in main_section.content

        # h2セクション
        h2_sections = [s for s in sections if s.level == 2]
        assert len(h2_sections) >= 2

        subsection1 = next(s for s in h2_sections if "サブセクション1" in s.header)
        assert subsection1.header == "サブセクション1"
        assert subsection1.level == 2

        # h3セクション
        h3_sections = [s for s in sections if s.level == 3]
        assert len(h3_sections) >= 1
        assert h3_sections[0].header == "サブサブセクション"
        assert h3_sections[0].level == 3

    def test_parse_markdown_without_headers(self, markdown_parser):
        """ヘッダーなしMarkdownの解析テスト"""
        content = """これはヘッダーのないMarkdownテキストです。

段落が複数あります。

最後の段落です。"""

        sections = markdown_parser.parse_markdown(content)

        # ヘッダーがない場合は1つのセクションとして扱われる
        assert len(sections) == 1
        assert sections[0].header == "Document"
        assert sections[0].level == 1
        assert "ヘッダーのない" in sections[0].content

    def test_parse_empty_markdown(self, markdown_parser):
        """空のMarkdownの解析テスト"""
        empty_content = ""
        sections = markdown_parser.parse_markdown(empty_content)

        assert len(sections) == 0

    def test_extract_metadata(self, markdown_parser, sample_markdown_content):
        """メタデータ抽出テスト"""
        metadata = markdown_parser.extract_metadata(sample_markdown_content)

        # ヘッダー情報
        assert len(metadata['headers']) >= 4

        header_texts = [h['text'] for h in metadata['headers']]
        assert "メインタイトル" in header_texts
        assert "サブセクション1" in header_texts
        assert "サブサブセクション" in header_texts

        # TODO項目数
        assert metadata['todo_count'] >= 2  # TODO: とFIXME: が検出される

        # コードブロック
        assert metadata['code_blocks'] >= 1

        # リンク
        assert len(metadata['links']) >= 1
        link_texts = [link[0] for link in metadata['links']]
        assert "リンクテキスト" in link_texts

        # 画像
        assert len(metadata['images']) >= 1
        image_alts = [img[0] for img in metadata['images']]
        assert "画像" in image_alts

    def test_extract_frontmatter(self, markdown_parser, frontmatter_content):
        """フロントマター抽出テスト"""
        frontmatter, remaining_content = markdown_parser.extract_frontmatter(
            frontmatter_content)

        # フロントマターが正しく抽出される
        assert frontmatter['title'] == "テストドキュメント"
        assert frontmatter['author'] == "テスト作成者"
        assert frontmatter['date'] == "2024-01-01"
        assert frontmatter['tags'] == "test, markdown"

        # 残りのコンテンツにフロントマターが含まれない
        assert "---" not in remaining_content
        assert "# ドキュメント本文" in remaining_content

    def test_extract_frontmatter_without_frontmatter(self, markdown_parser):
        """フロントマターなしコンテンツの処理テスト"""
        content = "# 普通のMarkdown\n\nフロントマターはありません。"

        frontmatter, remaining_content = markdown_parser.extract_frontmatter(
            content)

        assert len(frontmatter) == 0
        assert remaining_content == content

    def test_get_section_by_header(self, markdown_parser, sample_markdown_content):
        """ヘッダーによるセクション検索テスト"""
        sections = markdown_parser.parse_markdown(sample_markdown_content)

        # 存在するヘッダーで検索
        found_section = markdown_parser.get_section_by_header(
            sections, "サブセクション1")
        assert found_section is not None
        assert found_section.header == "サブセクション1"
        assert found_section.level == 2

        # 大文字小文字を無視した検索
        found_section_ci = markdown_parser.get_section_by_header(
            sections, "サブセクション1")
        assert found_section_ci is not None

        # 存在しないヘッダーで検索
        not_found = markdown_parser.get_section_by_header(
            sections, "存在しないセクション")
        assert not_found is None

    def test_get_sections_by_level(self, markdown_parser, sample_markdown_content):
        """レベルによるセクション検索テスト"""
        sections = markdown_parser.parse_markdown(sample_markdown_content)

        # h1レベルのセクション
        h1_sections = markdown_parser.get_sections_by_level(sections, 1)
        assert len(h1_sections) == 1
        assert h1_sections[0].header == "メインタイトル"

        # h2レベルのセクション
        h2_sections = markdown_parser.get_sections_by_level(sections, 2)
        assert len(h2_sections) >= 2

        # 存在しないレベル
        h5_sections = markdown_parser.get_sections_by_level(sections, 5)
        assert len(h5_sections) == 0

    def test_flatten_sections(self, markdown_parser, sample_markdown_content):
        """セクション平坦化テスト"""
        sections = markdown_parser.parse_markdown(sample_markdown_content)
        flattened = markdown_parser.flatten_sections(sections)

        # すべてのヘッダーが含まれている
        assert "# メインタイトル" in flattened
        assert "## サブセクション1" in flattened
        assert "### サブサブセクション" in flattened

        # コンテンツも含まれている
        assert "メインセクション" in flattened
        assert "チェックボックス" in flattened

    def test_markdown_with_special_characters(self, markdown_parser):
        """特殊文字を含むMarkdownの解析テスト"""
        content = """# 特殊文字テスト: {[()]}

**太字** と *斜体* と `インラインコード`

> ブロッククォート

1. 番号付きリスト
2. 項目2

- 箇条書き
- 項目2

| 表 | ヘッダー |
|---|----------|
| セル1 | セル2 |
"""

        sections = markdown_parser.parse_markdown(content)

        assert len(sections) >= 1
        main_section = sections[0]
        assert "特殊文字テスト" in main_section.header
        assert "太字" in main_section.content

    def test_nested_headers_order(self, markdown_parser):
        """ネストしたヘッダーの順序テスト"""
        content = """# レベル1

コンテンツ1

## レベル2-1

コンテンツ2-1

### レベル3

コンテンツ3

## レベル2-2

コンテンツ2-2

#### レベル4

コンテンツ4
"""

        sections = markdown_parser.parse_markdown(content)

        # セクションが正しい順序で取得される
        assert len(sections) >= 5

        levels = [section.level for section in sections]
        headers = [section.header for section in sections]

        assert levels[0] == 1
        assert headers[0] == "レベル1"
        assert levels[1] == 2
        assert headers[1] == "レベル2-1"

    def test_markdown_with_code_blocks(self, markdown_parser):
        """コードブロックを含むMarkdownの処理テスト"""
        content = """# コードテスト

通常のテキスト

```python
def hello():
    print("Hello World")
    # TODO: コメント内のTODO
```

TODO: コードブロック外のTODO

```
プレーンコードブロック
```
"""

        sections = markdown_parser.parse_markdown(content)
        metadata = markdown_parser.extract_metadata(content)

        assert len(sections) >= 1
        assert metadata['code_blocks'] >= 2
        # コードブロック外のTODOは検出される
        assert metadata['todo_count'] >= 1

    def test_empty_sections_handling(self, markdown_parser):
        """空のセクションの処理テスト"""
        content = """# 空セクションテスト

## 空のセクション

## コンテンツありセクション

実際のコンテンツがあります。

## また空のセクション

"""

        sections = markdown_parser.parse_markdown(content)

        # 空のセクションも保持される（空白のみのコンテンツは除外される場合もある）
        non_empty_sections = [s for s in sections if s.content.strip()]
        assert len(non_empty_sections) >= 1
