"""APIサーバーのテスト"""
import json
from unittest.mock import Mock, patch
import pytest

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
        mock_rag_instance.query.return_value = mock_query_response

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
        mock_rag_instance.get_todos.return_value = sample_todo_items

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
        mock_rag_instance.get_todos.return_value = pending_todos

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

        mock_rag_instance.add_todo.return_value = new_todo

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
        # RAGシステムのクエリメソッドで例外を発生
        mock_rag_instance.query.side_effect = Exception("テストエラー")

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
        """RAGシステムがNoneの場合のエラーハンドリング"""
        with patch('src.server.server.rag_system', None):
            response = client.get('/api/todos')
            assert response.status_code == 500

            data = json.loads(response.data)
            assert 'error' in data
