import re
from typing import List, Optional
from dataclasses import dataclass
from markdown_it import MarkdownIt


@dataclass
class MarkdownSection:
    """Markdownセクションを表すデータクラス"""
    header: str
    content: str
    level: int  # ヘッダーレベル (h1=1, h2=2, etc.)


class MarkdownParser:
    """Markdownの解析とセクション分割を担当するクラス"""

    def __init__(self):
        """MarkdownParserの初期化"""
        self.md_parser = MarkdownIt()

    def parse_markdown(self, content: str) -> List[MarkdownSection]:
        """
        Markdownコンテンツを解析してセクションに分割

        Args:
            content: Markdownコンテンツ

        Returns:
            MarkdownSectionのリスト
        """
        sections = []
        lines = content.split('\n')
        current_section = None
        current_content = []

        for line in lines:
            # ヘッダーを検出
            header_match = re.match(r'^(#{1,6})\s+(.+)', line)
            if header_match:
                # 前のセクションを保存
                if current_section:
                    current_section.content = '\n'.join(current_content)
                    sections.append(current_section)

                # 新しいセクションを開始
                level = len(header_match.group(1))
                header = header_match.group(2).strip()
                current_section = MarkdownSection(
                    header=header,
                    content='',
                    level=level
                )
                current_content = []
            else:
                # コンテンツを追加
                current_content.append(line)

        # 最後のセクションを保存
        if current_section:
            current_section.content = '\n'.join(current_content)
            sections.append(current_section)

        # セクションが見つからない場合は、全体を1つのセクションとして扱う
        if not sections and content.strip():
            sections.append(MarkdownSection(
                header="Document",
                content=content,
                level=1
            ))

        return sections

    def extract_metadata(self, content: str) -> dict:
        """
        Markdownコンテンツからメタデータを抽出

        Args:
            content: Markdownコンテンツ

        Returns:
            メタデータの辞書
        """
        metadata = {
            'headers': [],
            'todo_count': 0,
            'code_blocks': 0,
            'links': [],
            'images': []
        }

        lines = content.split('\n')

        for line in lines:
            # ヘッダーを検出
            header_match = re.match(r'^(#{1,6})\s+(.+)', line)
            if header_match:
                level = len(header_match.group(1))
                header = header_match.group(2).strip()
                metadata['headers'].append({
                    'level': level,
                    'text': header
                })

            # TODOパターンを検出
            todo_patterns = [
                r'(?:TODO|Todo|todo)\s*:?\s*(.+?)(?:\n|$)',
                r'(?:FIXME|Fixme|fixme)\s*:?\s*(.+?)(?:\n|$)',
                r'- \[ \]\s*(.+?)(?:\n|$)',  # Markdownチェックボックス
                r'\* \[ \]\s*(.+?)(?:\n|$)'
            ]

            for pattern in todo_patterns:
                if re.search(pattern, line):
                    metadata['todo_count'] += 1
                    break

            # コードブロック
            if line.strip().startswith('```'):
                metadata['code_blocks'] += 1

            # リンク
            links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', line)
            metadata['links'].extend(links)

            # 画像
            images = re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', line)
            metadata['images'].extend(images)

        return metadata

    def extract_frontmatter(self, content: str) -> tuple[dict, str]:
        """
        Markdownコンテンツからフロントマターを抽出

        Args:
            content: Markdownコンテンツ

        Returns:
            (フロントマター辞書, 残りのコンテンツ)
        """
        frontmatter = {}
        remaining_content = content

        # YAML形式のフロントマターを検出
        yaml_pattern = r'^---\s*\n(.*?)\n---\s*\n'
        match = re.match(yaml_pattern, content, re.DOTALL)

        if match:
            yaml_content = match.group(1)
            remaining_content = content[len(match.group(0)):]

            # 簡単なYAMLパーサー（キー: 値形式のみ）
            for line in yaml_content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    frontmatter[key.strip()] = value.strip()

        return frontmatter, remaining_content

    def get_section_by_header(self, sections: List[MarkdownSection],
                              header: str) -> Optional[MarkdownSection]:
        """
        指定されたヘッダーのセクションを取得

        Args:
            sections: セクションリスト
            header: 検索するヘッダー

        Returns:
            見つかったセクション（見つからない場合はNone）
        """
        for section in sections:
            if section.header.lower() == header.lower():
                return section
        return None

    def get_sections_by_level(self, sections: List[MarkdownSection],
                              level: int) -> List[MarkdownSection]:
        """
        指定されたレベルのセクションを取得

        Args:
            sections: セクションリスト
            level: 検索するレベル

        Returns:
            見つかったセクションのリスト
        """
        return [section for section in sections if section.level == level]

    def flatten_sections(self, sections: List[MarkdownSection]) -> str:
        """
        セクションリストを平坦化してテキストに変換

        Args:
            sections: セクションリスト

        Returns:
            結合されたテキスト
        """
        result = []
        for section in sections:
            result.append(f"{'#' * section.level} {section.header}")
            if section.content.strip():
                result.append(section.content)
        return '\n\n'.join(result)
