"""フロントエンド統合テスト"""
import pytest
import json
from unittest.mock import patch, Mock
from src.server.server import app


class TestFrontendIntegration:
    """フロントエンド統合テストクラス"""

    @pytest.fixture
    def client(self):
        """Flaskテストクライアント"""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    @pytest.fixture
    def mock_rag_system(self):
        """モックRAGシステム"""
        mock = Mock()
        mock.query.return_value = {
            'answer': 'テスト回答です。',
            'sources': [
                {
                    'header': 'テストヘッダー',
                    'content': 'テストコンテンツ',
                    'doc_id': 'test.md',
                    'file_name': 'test',
                    'folder_name': 'project1',
                    'section_id': 1,
                    'level': 2,
                    'type': 'content',
                    'score': 0.95
                }
            ]
        }
        return mock

    def test_serve_frontend_index(self, client):
        """フロントエンドindex.htmlの配信テスト"""
        response = client.get('/')
        assert response.status_code == 200
        # HTMLが返されることを確認
        assert b'DOCTYPE html' in response.data or b'html' in response.data

    def test_serve_static_css(self, client):
        """CSSファイルの配信テスト"""
        response = client.get('/styles.css')
        assert response.status_code == 200

    def test_serve_static_js(self, client):
        """JavaScriptファイルの配信テスト"""
        response = client.get('/script.js')
        assert response.status_code == 200

    def test_rag_search_workflow(self, client, mock_rag_system):
        """RAG検索ワークフローのテスト"""
        with patch('src.server.server.rag_system', mock_rag_system):
            # 質問送信
            response = client.post(
                '/api/query',
                data=json.dumps({'query': 'テスト質問'}),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'answer' in data
            assert 'sources' in data
            assert len(data['sources']) == 1

            # ソースのメタデータ確認
            source = data['sources'][0]
            assert source['file_name'] == 'test'
            assert source['folder_name'] == 'project1'
            assert source['type'] == 'content'

    def test_file_management_workflow(self, client, temp_dir):
        """ファイル管理ワークフローのテスト"""
        import os

        # ファイル一覧取得
        with patch('src.server.server.current_dir', temp_dir):
            response = client.get('/api/files')
            assert response.status_code == 200

            # 新しいファイル作成
            response = client.put(
                '/api/files/test_workflow.md',
                data=json.dumps({'content': '# ワークフローテスト'}),
                content_type='application/json'
            )
            assert response.status_code == 200

            # ファイル内容取得
            response = client.get('/api/files/test_workflow.md')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['content'] == '# ワークフローテスト'

    def test_chunk_analysis_workflow(self, client, temp_dir):
        """チャンク分析ワークフローのテスト"""
        import os

        # テストファイル作成
        test_data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(test_data_dir, exist_ok=True)
        test_file = os.path.join(test_data_dir, 'workflow_test.md')

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('# ワークフローテスト\n\nテスト内容です。')

        mock_rag = Mock()
        mock_rag._parse_markdown.return_value = [
            Mock(header='ワークフローテスト', content='テスト内容です。', level=1)
        ]
        mock_rag._create_nodes_from_sections.return_value = [
            Mock(
                text='ワークフローテスト',
                metadata={'type': 'header', 'level': 1}
            ),
            Mock(
                text='テスト内容です。',
                metadata={'type': 'content', 'level': 1}
            )
        ]

        with patch('src.server.server.current_dir', temp_dir), \
                patch('src.server.server.rag_system', mock_rag):
            response = client.get('/api/chunks/analyze/workflow_test.md')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['total_chunks'] == 2
            assert data['header_chunks'] == 1
            assert data['content_chunks'] == 1

    def test_error_handling_workflow(self, client):
        """エラーハンドリングワークフローのテスト"""
        # 不正なリクエスト
        response = client.post(
            '/api/query',
            data=json.dumps({}),  # 空のクエリ
            content_type='application/json'
        )
        assert response.status_code == 400

        # 存在しないファイルのアクセス
        response = client.get('/api/files/nonexistent.md')
        assert response.status_code == 404

    @pytest.fixture
    def temp_dir(self):
        """一時ディレクトリの作成と削除"""
        import tempfile
        import shutil
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)


class TestUIFeatures:
    """UI機能のテスト"""

    @pytest.fixture
    def client(self):
        """Flaskテストクライアント"""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_health_check_for_ui(self, client):
        """UIからのヘルスチェック"""
        response = client.get('/api/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'ok'

    def test_todo_management_ui_endpoints(self, client):
        """TODO管理UI用エンドポイント"""
        with patch('src.server.server.rag_system') as mock_rag:
            # TodoItemのモックオブジェクトを作成
            from src.server.todo_manager import TodoItem
            from datetime import datetime
            
            mock_todo = TodoItem(
                id="test1",
                content="テストタスク",
                status="pending",
                priority="medium",
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                source_file="test.md",
                source_section="セクション"
            )
            
            mock_rag.get_todos.return_value = [mock_todo]

            response = client.get('/api/todos')
            assert response.status_code == 200
            data = response.get_json()
            assert 'todos' in data
            assert data['count'] == 1

            response = client.get('/api/todos?status=pending')
            assert response.status_code == 200

    def test_cors_headers(self, client):
        """CORS ヘッダーの確認"""
        response = client.get('/api/health')
        # CORSが設定されていることを確認
        assert response.status_code == 200

    def test_content_type_handling(self, client):
        """コンテンツタイプの処理"""
        # JSON リクエスト
        response = client.post(
            '/api/query',
            data=json.dumps({'query': 'test'}),
            content_type='application/json'
        )
        # レスポンスのコンテンツタイプも確認
        assert 'application/json' in response.content_type
