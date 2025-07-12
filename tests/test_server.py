"""APIサーバーのテスト"""
import json
from unittest.mock import Mock, patch
import pytest
import os

from src.server.server import app
from src.server.rag_system import TodoItem


class TestAPIServer:
    """APIサーバーのテストクラス"""

    @pytest.fixture
    def client(self):
        """Flaskテストクライアント"""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    @pytest.fixture
    def mock_rag_instance(self, mock_rag_system):
        """サーバーのRAGシステムインスタンスをモック"""
        with patch('src.server.server.rag_system', mock_rag_system):
            yield mock_rag_system

    def test_health_check(self, client):
        """ヘルスチェックエンドポイントのテスト"""
        response = client.get('/api/health')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'status' in data
        assert data['status'] == 'ok'
        assert 'rag_system_ready' in data

    def test_query_endpoint_success(self, client, mock_rag_instance, mock_query_response):
        """クエリエンドポイントの成功テスト"""
        # RAGシステムのクエリメソッドをモック
        from unittest.mock import Mock
        mock_query = Mock(return_value=mock_query_response)
        mock_rag_instance.query = mock_query

        with patch('src.server.server.rag_system', mock_rag_instance):
            # リクエストデータ
            request_data = {'query': 'テストクエリ'}

            # APIコール
            response = client.post(
                '/api/query',
                data=json.dumps(request_data),
                content_type='application/json'
            )

            assert response.status_code == 200

            data = json.loads(response.data)
            assert 'answer' in data
            assert 'sources' in data
            assert data['answer'] == mock_query_response['answer']

    def test_query_endpoint_empty_query(self, client, mock_rag_instance):
        """空のクエリに対するエラーテスト"""
        request_data = {'query': ''}

        response = client.post(
            '/api/query',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_query_endpoint_no_query(self, client, mock_rag_instance):
        """クエリなしリクエストのエラーテスト"""
        request_data = {}

        response = client.post(
            '/api/query',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_query_endpoint_rag_system_none(self, client):
        """RAGシステムが初期化されていない場合のテスト"""
        with patch('src.server.server.rag_system', None):
            request_data = {'query': 'テストクエリ'}

            response = client.post(
                '/api/query',
                data=json.dumps(request_data),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'answer' in data
            assert 'sources' in data
            # モックレスポンスが返される
            assert 'モック' in data['answer']

    def test_get_todos_endpoint(self, client, mock_rag_instance, sample_todo_items):
        """TODO取得エンドポイントのテスト"""
        # RAGシステムのget_todosメソッドをモック
        from unittest.mock import Mock
        mock_get_todos = Mock(return_value=sample_todo_items)
        mock_rag_instance.get_todos = mock_get_todos

        with patch('src.server.server.rag_system', mock_rag_instance):
            response = client.get('/api/todos')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'todos' in data
            assert 'count' in data
            assert data['count'] == len(sample_todo_items)

    def test_get_todos_with_status_filter(self, client, mock_rag_instance, sample_todo_items):
        """ステータスフィルタ付きTODO取得のテスト"""
        # pendingステータスのTODOのみ返すようにモック
        pending_todos = [
            todo for todo in sample_todo_items if todo.status == 'pending']
        from unittest.mock import Mock
        mock_get_todos = Mock(return_value=pending_todos)
        mock_rag_instance.get_todos = mock_get_todos

        with patch('src.server.server.rag_system', mock_rag_instance):
            response = client.get('/api/todos?status=pending')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['count'] == len(pending_todos)

    def test_create_todo_endpoint(self, client, mock_rag_instance):
        """TODO作成エンドポイントのテスト"""
        new_todo = TodoItem(
            id="new_test",
            content="新しいタスク",
            status="pending",
            priority="medium",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            source_file="api",
            source_section="manual"
        )

        from unittest.mock import Mock
        mock_add_todo = Mock(return_value=new_todo)
        mock_rag_instance.add_todo = mock_add_todo

        with patch('src.server.server.rag_system', mock_rag_instance):
            request_data = {
                'content': '新しいタスク',
                'priority': 'medium'
            }

            response = client.post(
                '/api/todos',
                data=json.dumps(request_data),
                content_type='application/json'
            )

            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['content'] == '新しいタスク'
            assert data['priority'] == 'medium'

    def test_create_todo_missing_content(self, client, mock_rag_instance):
        """コンテンツなしTODO作成のエラーテスト"""
        request_data = {'priority': 'high'}

        response = client.post(
            '/api/todos',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_update_todo_endpoint(self, client, mock_rag_instance, sample_todo_items):
        """TODO更新エンドポイントのテスト"""
        updated_todo = sample_todo_items[0]
        updated_todo.status = "completed"

        mock_rag_instance.update_todo.return_value = updated_todo

        request_data = {'status': 'completed'}

        response = client.put(
            '/api/todos/test1',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'completed'

    def test_update_todo_not_found(self, client, mock_rag_instance):
        """存在しないTODO更新のテスト"""
        mock_rag_instance.update_todo.return_value = None

        request_data = {'status': 'completed'}

        response = client.put(
            '/api/todos/nonexistent',
            data=json.dumps(request_data),
            content_type='application/json'
        )

        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'error' in data

    def test_delete_todo_endpoint(self, client, mock_rag_instance):
        """TODO削除エンドポイントのテスト"""
        mock_rag_instance.delete_todo.return_value = True

        response = client.delete('/api/todos/test1')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'message' in data

    def test_delete_todo_not_found(self, client, mock_rag_instance):
        """存在しないTODO削除のテスト"""
        mock_rag_instance.delete_todo.return_value = False

        response = client.delete('/api/todos/nonexistent')

        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'error' in data

    def test_aggregate_todos_endpoint(self, client, mock_rag_instance, sample_todo_items):
        """TODO集約エンドポイントのテスト"""
        # 実際のTodoItemインスタンスを使用してモックを設定
        mock_aggregated = {
            "2024-01-01": sample_todo_items
        }
        mock_rag_instance.aggregate_todos_by_date.return_value = mock_aggregated

        response = client.get('/api/todos/aggregate')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert "2024-01-01" in data
        assert len(data["2024-01-01"]) == len(sample_todo_items)

    def test_extract_todos_endpoint(self, client, mock_rag_instance):
        """TODO抽出エンドポイントのテスト"""
        mock_rag_instance.extract_todos_from_documents.return_value = 5

        response = client.post('/api/todos/extract')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'new_todos_count' in data
        assert data['new_todos_count'] == 5

    def test_overdue_todos_endpoint(self, client, mock_rag_instance, sample_todo_items):
        """期限切れTODO取得エンドポイントのテスト"""
        overdue_todo = sample_todo_items[0]
        mock_rag_instance.get_overdue_todos.return_value = [overdue_todo]

        response = client.get('/api/todos/overdue')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'todos' in data
        assert len(data['todos']) == 1

    def test_server_error_handling(self, client, mock_rag_instance):
        """サーバーエラーハンドリングのテスト"""
        # RAGシステムのクエリメソッドでMockを設定
        from unittest.mock import Mock
        mock_query_error = Mock(side_effect=Exception("テストエラー"))
        mock_rag_instance.query = mock_query_error

        with patch('src.server.server.rag_system', mock_rag_instance):
            request_data = {'query': 'テストクエリ'}

            response = client.post(
                '/api/query',
                data=json.dumps(request_data),
                content_type='application/json'
            )

            assert response.status_code == 500
            data = json.loads(response.data)
            assert 'error' in data

    def test_rag_system_none_error_handling(self, client):
        """RAGシステムがNoneの場合のエラーハンドリングテスト"""
        with patch('src.server.server.rag_system', None):
            # TODOエンドポイントのテスト
            response = client.get('/api/todos')
            assert response.status_code == 500

            response = client.post('/api/todos/extract')
            assert response.status_code == 500

    # ファイル管理APIのテスト
    def test_list_files_endpoint(self, client, temp_dir):
        """ファイル一覧取得エンドポイントのテスト"""
        # テストファイルを作成
        test_data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(test_data_dir, exist_ok=True)

        test_file1 = os.path.join(test_data_dir, 'test1.md')
        test_file2 = os.path.join(test_data_dir, 'folder', 'test2.md')
        os.makedirs(os.path.dirname(test_file2), exist_ok=True)

        with open(test_file1, 'w', encoding='utf-8') as f:
            f.write('# テストファイル1')
        with open(test_file2, 'w', encoding='utf-8') as f:
            f.write('# テストファイル2')

        # パッチを適用してAPIを呼び出し
        with patch('src.server.server.current_dir', temp_dir):
            response = client.get('/api/files')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'files' in data
        assert len(data['files']) == 2

        # ファイル情報の確認
        file_paths = [f['path'] for f in data['files']]
        assert 'test1.md' in file_paths
        assert os.path.join('folder', 'test2.md') in file_paths

    def test_get_file_content_endpoint(self, client, temp_dir):
        """ファイル内容取得エンドポイントのテスト"""
        # テストファイルを作成
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
        assert data['path'] == 'test.md'
        assert 'size' in data

    def test_get_file_content_not_found(self, client, temp_dir):
        """存在しないファイルの取得テスト"""
        with patch('src.server.server.current_dir', temp_dir):
            response = client.get('/api/files/nonexistent.md')

        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'error' in data

    def test_get_file_content_security_check(self, client, temp_dir):
        """ファイルアクセスのセキュリティチェックテスト"""
        with patch('src.server.server.current_dir', temp_dir):
            # パストラバーサル攻撃の試行
            response = client.get('/api/files/../../../etc/passwd')

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
        assert '不正' in data['error']

    def test_save_file_content_endpoint(self, client, temp_dir, mock_rag_instance):
        """ファイル保存エンドポイントのテスト"""
        test_content = '# 新しいファイル\n\n保存されたコンテンツです。'
        request_data = {'content': test_content}

        with patch('src.server.server.current_dir', temp_dir):
            response = client.put(
                '/api/files/new_file.md',
                data=json.dumps(request_data),
                content_type='application/json'
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'message' in data
        assert data['path'] == 'new_file.md'

        # ファイルが実際に作成されたことを確認
        test_data_dir = os.path.join(temp_dir, 'data')
        created_file = os.path.join(test_data_dir, 'new_file.md')
        assert os.path.exists(created_file)

        with open(created_file, 'r', encoding='utf-8') as f:
            assert f.read() == test_content

    def test_save_file_content_missing_content(self, client, temp_dir):
        """コンテンツなしファイル保存のエラーテスト"""
        request_data = {}

        with patch('src.server.server.current_dir', temp_dir):
            response = client.put(
                '/api/files/test.md',
                data=json.dumps(request_data),
                content_type='application/json'
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_delete_file_endpoint(self, client, temp_dir, mock_rag_instance):
        """ファイル削除エンドポイントのテスト"""
        # テストファイルを作成
        test_data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(test_data_dir, exist_ok=True)
        test_file = os.path.join(test_data_dir, 'to_delete.md')

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('削除対象ファイル')

        with patch('src.server.server.current_dir', temp_dir):
            response = client.delete('/api/files/to_delete.md')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'message' in data

        # ファイルが削除されたことを確認
        assert not os.path.exists(test_file)

    def test_delete_file_not_found(self, client, temp_dir):
        """存在しないファイルの削除テスト"""
        with patch('src.server.server.current_dir', temp_dir):
            response = client.delete('/api/files/nonexistent.md')

        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'error' in data

    def test_analyze_chunks_endpoint(self, client, temp_dir, mock_rag_instance):
        """チャンク分析エンドポイントのテスト"""
        # テストファイルを作成
        test_data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(test_data_dir, exist_ok=True)
        test_file = os.path.join(test_data_dir, 'analyze_test.md')
        test_content = '''# メインタイトル

メインコンテンツです。

## サブセクション

サブコンテンツです。
'''

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(test_content)

        # モックチャンク分析結果を設定
        mock_chunks = [
            {
                'type': 'header',
                'text': 'メインタイトル',
                'metadata': {
                    'header': 'メインタイトル',
                    'level': 1,
                    'section_id': 0,
                    'folder_name': '',
                    'file_name': 'analyze_test',
                },
                'text_length': 8,
                'preview': 'メインタイトル'
            },
            {
                'type': 'content',
                'text': 'メインコンテンツです。',
                'metadata': {
                    'header': 'メインタイトル',
                    'level': 1,
                    'section_id': 0,
                    'folder_name': '',
                    'file_name': 'analyze_test',
                },
                'text_length': 11,
                'preview': 'メインコンテンツです。'
            }
        ]

        # _parse_markdownメソッドをMockで設定
        from unittest.mock import Mock
        mock_parse = Mock(return_value=[
            Mock(header='メインタイトル', content='メインコンテンツです。', level=1)
        ])
        mock_rag_instance._parse_markdown = mock_parse

        # _create_nodes_from_sectionsメソッドをMockで設定
        mock_create_nodes = Mock(return_value=[
            Mock(
                text='メインタイトル',
                metadata={
                    'type': 'header',
                    'header': 'メインタイトル',
                    'level': 1,
                    'section_id': 0,
                    'folder_name': '',
                    'file_name': 'analyze_test',
                }
            ),
            Mock(
                text='メインコンテンツです。',
                metadata={
                    'type': 'content',
                    'header': 'メインタイトル',
                    'level': 1,
                    'section_id': 0,
                    'folder_name': '',
                    'file_name': 'analyze_test',
                }
            )
        ])
        mock_rag_instance._create_nodes_from_sections = mock_create_nodes

        with patch('src.server.server.current_dir', temp_dir):
            response = client.get('/api/chunks/analyze/analyze_test.md')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'file_path' in data
        assert 'total_chunks' in data
        assert 'header_chunks' in data
        assert 'content_chunks' in data
        assert 'chunks' in data
        assert data['total_chunks'] == 2
        assert data['header_chunks'] == 1
        assert data['content_chunks'] == 1

    def test_analyze_chunks_file_not_found(self, client, temp_dir, mock_rag_instance):
        """存在しないファイルのチャンク分析テスト"""
        with patch('src.server.server.current_dir', temp_dir):
            response = client.get('/api/chunks/analyze/nonexistent.md')

        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'error' in data

    def test_analyze_chunks_rag_system_none(self, client, temp_dir):
        """RAGシステムが初期化されていない場合のチャンク分析テスト"""
        with patch('src.server.server.rag_system', None), \
                patch('src.server.server.current_dir', temp_dir):
            response = client.get('/api/chunks/analyze/test.md')

        assert response.status_code == 500
        data = json.loads(response.data)
        assert 'error' in data

    def test_refresh_index_endpoint(self, client, mock_rag_instance):
        """インデックス更新エンドポイントのテスト"""
        from unittest.mock import Mock
        mock_rag_instance._create_new_index = Mock(return_value=Mock())

        response = client.post('/api/index/refresh')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'message' in data
        mock_rag_instance._create_new_index.assert_called_once()

    def test_refresh_index_rag_system_none(self, client):
        """RAGシステムが初期化されていない場合のインデックス更新テスト"""
        with patch('src.server.server.rag_system', None):
            response = client.post('/api/index/refresh')

        assert response.status_code == 500
        data = json.loads(response.data)
        assert 'error' in data

    def test_file_api_error_handling(self, client, temp_dir):
        """ファイルAPIのエラーハンドリングテスト"""
        # テストファイルを作成
        test_data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(test_data_dir, exist_ok=True)
        test_file = os.path.join(test_data_dir, 'test.md')

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('テストファイル')

        # 権限エラーをシミュレート
        with patch('src.server.server.current_dir', temp_dir), \
                patch('builtins.open', side_effect=PermissionError("Permission denied")):
            response = client.get('/api/files/test.md')

        assert response.status_code == 500
        data = json.loads(response.data)
        assert 'error' in data
