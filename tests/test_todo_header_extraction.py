"""
TODOセクションヘッダーからの抽出機能のテスト
"""
import pytest
import tempfile
import os
from src.server.text_chunker import TextChunker
from src.server.rag_system import RAGSystem


class TestTodoHeaderExtraction:
    """TODOセクションヘッダーからの抽出テスト"""

    def setup_method(self):
        """テストセットアップ"""
        self.text_chunker = TextChunker()

    def test_check_header_has_todo(self):
        """ヘッダーにTODOが含まれているかのチェックテスト"""
        # TODOを含むヘッダー
        assert self.text_chunker._check_header_has_todo("TODO") is True
        assert self.text_chunker._check_header_has_todo("TODO: 抽出テスト") is True
        assert self.text_chunker._check_header_has_todo("FIXME: バグ修正") is True
        assert self.text_chunker._check_header_has_todo("BUG: 問題報告") is True
        assert self.text_chunker._check_header_has_todo("HACK: 暫定対応") is True
        assert self.text_chunker._check_header_has_todo("NOTE: 注意事項") is True
        assert self.text_chunker._check_header_has_todo("XXX: 要確認") is True

        # TODOを含まないヘッダー
        assert self.text_chunker._check_header_has_todo("通常のセクション") is False
        assert self.text_chunker._check_header_has_todo("実装予定") is False
        assert self.text_chunker._check_header_has_todo("") is False
        assert self.text_chunker._check_header_has_todo("完了項目") is False

    def test_create_chunks_with_todo_metadata_header_todo(self):
        """TODOヘッダーを持つセクションの全チャンクがTODO項目として抽出されるテスト"""
        text = """- データベースの設計を見直す
- APIエンドポイントを追加する
- ユニットテストを書く
- ドキュメントを更新する"""

        section_header = "TODO: 抽出テスト"
        chunks_with_metadata = self.text_chunker.create_chunks_with_todo_metadata(
            text, "test.md", 0, section_header
        )

        # 全チャンクがTODO項目として認識される
        assert len(chunks_with_metadata) == 4
        for chunk_data in chunks_with_metadata:
            metadata = chunk_data['metadata']
            assert metadata['has_todo'] is True
            assert metadata['todo_type'] == 'TODO'
            assert metadata['todo_content'] == chunk_data['text'].strip()

    def test_create_chunks_with_todo_metadata_fixme_header(self):
        """FIXMEヘッダーを持つセクションのテスト"""
        text = """- ログイン機能のバグを修正
- パフォーマンスの問題を解決"""

        section_header = "FIXME: バグ修正"
        chunks_with_metadata = self.text_chunker.create_chunks_with_todo_metadata(
            text, "test.md", 1, section_header
        )

        # 全チャンクがFIXME項目として認識される
        assert len(chunks_with_metadata) == 2
        for chunk_data in chunks_with_metadata:
            metadata = chunk_data['metadata']
            assert metadata['has_todo'] is True
            assert metadata['todo_type'] == 'FIXME'
            assert metadata['todo_content'] == chunk_data['text'].strip()

    def test_create_chunks_with_todo_metadata_normal_header(self):
        """通常のヘッダーを持つセクションのテスト"""
        text = """- 単なるリスト項目1
- 単なるリスト項目2
TODO: このチャンク内のTODO"""

        section_header = "通常のセクション"
        chunks_with_metadata = self.text_chunker.create_chunks_with_todo_metadata(
            text, "test.md", 2, section_header
        )

        # チャンク内容でTODOが判定される（ヘッダーではなく）
        todo_chunks = [chunk for chunk in chunks_with_metadata 
                      if chunk['metadata']['has_todo']]
        assert len(todo_chunks) == 1  # "TODO: このチャンク内のTODO"のみ
        assert "このチャンク内のTODO" in todo_chunks[0]['metadata']['todo_content']

    def test_todo_type_detection_from_header(self):
        """ヘッダーからのTODOタイプ検出テスト"""
        test_cases = [
            ("TODO: 作業項目", "TODO"),
            ("FIXME: 修正項目", "FIXME"),
            ("BUG: バグ報告", "BUG"),
            ("HACK: 暫定対応", "HACK"),
            ("NOTE: 注意事項", "NOTE"),
            ("XXX: 要確認", "XXX")
        ]

        for header, expected_type in test_cases:
            chunks_with_metadata = self.text_chunker.create_chunks_with_todo_metadata(
                "テスト内容", "test.md", 0, header
            )
            
            assert len(chunks_with_metadata) == 1
            metadata = chunks_with_metadata[0]['metadata']
            assert metadata['has_todo'] is True
            assert metadata['todo_type'] == expected_type

    def test_priority_detection_with_header(self):
        """ヘッダーと内容を考慮した優先度検出テスト"""
        # 緊急キーワードを含むケース
        chunks_with_metadata = self.text_chunker.create_chunks_with_todo_metadata(
            "urgent 緊急対応が必要", "test.md", 0, "TODO: 緊急タスク"
        )
        
        assert chunks_with_metadata[0]['metadata']['todo_priority'] == 'high'

        # 後回しキーワードを含むケース
        chunks_with_metadata = self.text_chunker.create_chunks_with_todo_metadata(
            "later 後で対応", "test.md", 0, "TODO: 後回しタスク"
        )
        
        assert chunks_with_metadata[0]['metadata']['todo_priority'] == 'low'

        # 通常のケース
        chunks_with_metadata = self.text_chunker.create_chunks_with_todo_metadata(
            "通常の作業", "test.md", 0, "TODO: 通常タスク"
        )
        
        assert chunks_with_metadata[0]['metadata']['todo_priority'] == 'medium'


class TestTodoHeaderExtractionIntegration:
    """TODOヘッダー抽出の統合テスト"""

    def test_rag_system_header_todo_extraction(self):
        """RAGシステム全体でのヘッダーTODO抽出テスト"""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = os.path.join(temp_dir, 'data')
            persist_dir = os.path.join(temp_dir, 'storage') 
            os.makedirs(data_dir, exist_ok=True)

            # セクションヘッダーにTODOを含むテストファイルを作成
            test_content = """# テストドキュメント

## TODO: 実装予定の機能

- ユーザー認証機能を追加
- データベース設計を見直し
- APIドキュメントを作成

## FIXME: 修正が必要な問題

- ログイン時のエラーハンドリング
- パフォーマンス最適化

## 通常のセクション

通常のコンテンツです。

TODO: このセクション内のTODO項目
"""

            test_file = os.path.join(data_dir, 'header_todo_test.md')
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(test_content)

            # RAGシステムを初期化してTODO抽出
            rag = RAGSystem(persist_dir=persist_dir, data_dir=data_dir)
            extracted_count = rag.extract_todos_from_documents()

            # TODOが抽出されていることを確認
            assert extracted_count > 0

            todos = rag.get_todos()
            
            # セクションヘッダーからのTODO抽出を確認
            header_todos = [t for t in todos if 'TODO: 実装予定の機能' in t.source_section]
            assert len(header_todos) == 3  # 3つのリスト項目

            fixme_todos = [t for t in todos if 'FIXME: 修正が必要な問題' in t.source_section]
            assert len(fixme_todos) == 2  # 2つのリスト項目

            # 通常セクション内のTODO項目も抽出されることを確認
            normal_section_todos = [t for t in todos if '通常のセクション' in t.source_section]
            assert len(normal_section_todos) >= 1

            # 内容の確認
            header_todo_contents = [t.content for t in header_todos]
            assert any('ユーザー認証機能' in content for content in header_todo_contents)
            assert any('データベース設計' in content for content in header_todo_contents)

    def test_mixed_todo_patterns(self):
        """ヘッダーTODOと内容TODOが混在する場合のテスト"""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = os.path.join(temp_dir, 'data')
            persist_dir = os.path.join(temp_dir, 'storage')
            os.makedirs(data_dir, exist_ok=True)

            # 混在パターンのテストファイル
            test_content = """# プロジェクト

## TODO: ヘッダーTODOセクション

- ヘッダーから抽出される項目1
- ヘッダーから抽出される項目2

## 通常セクション

TODO: 内容から抽出されるTODO
- [ ] チェックボックスTODO
"""

            test_file = os.path.join(data_dir, 'mixed_todo_test.md')
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(test_content)

            # RAGシステムでTODO抽出
            rag = RAGSystem(persist_dir=persist_dir, data_dir=data_dir)
            extracted_count = rag.extract_todos_from_documents()

            todos = rag.get_todos()
            
            # ヘッダーTODOセクションからの抽出
            header_section_todos = [t for t in todos if 'TODO: ヘッダーTODOセクション' in t.source_section]
            assert len(header_section_todos) == 2

            # 通常セクションからの抽出
            normal_section_todos = [t for t in todos if '通常セクション' in t.source_section]
            assert len(normal_section_todos) >= 2  # 内容TODO + チェックボックス