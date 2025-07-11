"""ファイル管理機能のテスト"""
import os
import json
import tempfile
import pytest
from unittest.mock import patch, Mock
from src.server.server import app


class TestFileManagement:
    """ファイル管理機能のテストクラス"""

    @pytest.fixture
    def client(self):
        """Flaskテストクライアント"""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    @pytest.fixture
    def temp_dir(self):
        """一時ディレクトリの作成と削除"""
        import shutil
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_list_files_endpoint(self, client, temp_dir):
        """ファイル一覧取得のテスト"""
        # テストファイルを作成
        test_data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(test_data_dir, exist_ok=True)

        test_file1 = os.path.join(test_data_dir, 'file1.md')
        test_file2 = os.path.join(test_data_dir, 'folder', 'file2.md')
        os.makedirs(os.path.dirname(test_file2), exist_ok=True)

        with open(test_file1, 'w', encoding='utf-8') as f:
            f.write('# ファイル1')
        with open(test_file2, 'w', encoding='utf-8') as f:
            f.write('# ファイル2')

        with patch('src.server.server.current_dir', temp_dir):
            response = client.get('/api/files')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'files' in data
        assert len(data['files']) == 2

    def test_get_file_content(self, client, temp_dir):
        """ファイル内容取得のテスト"""
        test_data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(test_data_dir, exist_ok=True)
        test_file = os.path.join(test_data_dir, 'test.md')
        test_content = '# テストファイル\n\nテスト内容です。'

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(test_content)

        with patch('src.server.server.current_dir', temp_dir):
            response = client.get('/api/files/test.md')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['content'] == test_content

    def test_save_file_content(self, client, temp_dir):
        """ファイル保存のテスト"""
        test_content = '# 新しいファイル\n\n保存内容です。'
        request_data = {'content': test_content}

        # より完全なMockオブジェクトを作成
        mock_rag = Mock()
        mock_rag.document_hashes = {}
        mock_rag._save_document_hashes = Mock()

        # データディレクトリを事前に作成
        test_data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(test_data_dir, exist_ok=True)

        with patch('src.server.server.current_dir', temp_dir), \
                patch('src.server.server.rag_system', mock_rag):
            response = client.put(
                '/api/files/new_file.md',
                data=json.dumps(request_data),
                content_type='application/json'
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'message' in data

        # ファイルが作成されたことを確認
        created_file = os.path.join(test_data_dir, 'new_file.md')
        assert os.path.exists(created_file)

        # ファイル内容も確認
        with open(created_file, 'r', encoding='utf-8') as f:
            saved_content = f.read()
        assert saved_content == test_content

    def test_delete_file(self, client, temp_dir):
        """ファイル削除のテスト"""
        test_data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(test_data_dir, exist_ok=True)
        test_file = os.path.join(test_data_dir, 'delete_me.md')

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('削除対象')

        with patch('src.server.server.current_dir', temp_dir), \
                patch('src.server.server.rag_system', Mock()):
            response = client.delete('/api/files/delete_me.md')

        assert response.status_code == 200
        assert not os.path.exists(test_file)

    def test_security_check(self, client, temp_dir):
        """セキュリティチェックのテスト"""
        with patch('src.server.server.current_dir', temp_dir):
            # パストラバーサル攻撃の試行
            response = client.get('/api/files/../../../etc/passwd')

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
        assert '不正' in data['error']


class TestChunkAnalysis:
    """チャンク分析機能のテストクラス"""

    @pytest.fixture
    def client(self):
        """Flaskテストクライアント"""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    @pytest.fixture
    def temp_dir(self):
        """一時ディレクトリの作成と削除"""
        import shutil
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_rag_system(self):
        """モックRAGシステム"""
        mock = Mock()
        mock._parse_markdown.return_value = [
            Mock(header='テストヘッダー', content='テストコンテンツ', level=1)
        ]
        mock._create_nodes_from_sections.return_value = [
            Mock(
                text='テストヘッダー',
                metadata={
                    'type': 'header',
                    'header': 'テストヘッダー',
                    'level': 1,
                    'section_id': 0,
                    'folder_name': '',
                    'file_name': 'test',
                }
            ),
            Mock(
                text='テストコンテンツ',
                metadata={
                    'type': 'content',
                    'header': 'テストヘッダー',
                    'level': 1,
                    'section_id': 0,
                    'folder_name': '',
                    'file_name': 'test',
                }
            )
        ]
        return mock

    def test_analyze_chunks(self, client, temp_dir, mock_rag_system):
        """チャンク分析のテスト"""
        # テストファイル作成
        test_data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(test_data_dir, exist_ok=True)
        test_file = os.path.join(test_data_dir, 'analyze.md')

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('# テストヘッダー\n\nテストコンテンツ')

        with patch('src.server.server.current_dir', temp_dir), \
                patch('src.server.server.rag_system', mock_rag_system):
            response = client.get('/api/chunks/analyze/analyze.md')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'file_path' in data
        assert 'total_chunks' in data
        assert 'chunks' in data
        assert data['total_chunks'] == 2

    def test_refresh_index(self, client, mock_rag_system):
        """インデックス更新のテスト"""
        mock_rag_system._create_new_index.return_value = Mock()

        with patch('src.server.server.rag_system', mock_rag_system):
            response = client.post('/api/index/refresh')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'message' in data
        mock_rag_system._create_new_index.assert_called_once()

    def test_chunk_analysis_no_rag_system(self, client, temp_dir):
        """RAGシステムが無い場合のテスト"""
        with patch('src.server.server.rag_system', None), \
                patch('src.server.server.current_dir', temp_dir):
            response = client.get('/api/chunks/analyze/test.md')

        assert response.status_code == 500
        data = json.loads(response.data)
        assert 'error' in data
