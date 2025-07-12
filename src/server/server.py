from rag_system import RAGSystem
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import sys
import logging
from typing import Dict, Any
from dataclasses import asdict

# 現在のディレクトリをsys.pathに追加
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)


app = Flask(__name__)
CORS(app)

# ログの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# RAGシステムのインスタンスを初期化
rag_system = None


def initialize_rag_system():
    """RAGシステムを初期化する"""
    global rag_system
    try:
        logger.info("RAGシステムの初期化を開始します...")

        # プロジェクトルートからの相対パスを使用
        project_root = os.path.join(current_dir, '..', '..')
        persist_dir = os.path.join(project_root, 'storage')
        data_dir = os.path.join(project_root, 'data')

        logger.info(f"データディレクトリ: {data_dir}")
        logger.info(f"永続化ディレクトリ: {persist_dir}")

        # ディレクトリの存在確認
        if not os.path.exists(data_dir):
            logger.warning(f"データディレクトリが存在しません: {data_dir}")
            os.makedirs(data_dir, exist_ok=True)
            logger.info("データディレクトリを作成しました")

        if not os.path.exists(persist_dir):
            logger.info(f"永続化ディレクトリが存在しません。"
                        f"作成します: {persist_dir}")
            os.makedirs(persist_dir, exist_ok=True)

        rag_system = RAGSystem(
            persist_dir=persist_dir,
            data_dir=data_dir
        )
        logger.info("RAGシステムの初期化が完了しました")

    except ImportError as e:
        logger.error(f"必要なパッケージがインストールされていません: {e}")
        logger.error("pip install -r requirements.txt または "
                     "uv sync を実行してください")
        rag_system = None
    except ConnectionError as e:
        logger.error(f"Ollamaサーバーへの接続に失敗しました: {e}")
        logger.error("Ollamaが起動していることを確認してください")
        rag_system = None
    except Exception as e:
        logger.error(f"RAGシステムの初期化に失敗しました: {e}")
        logger.error("フォールバックとして、モックシステムを使用します")
        import traceback
        traceback.print_exc()
        rag_system = None


@app.route('/api/health', methods=['GET'])
def health_check():
    """ヘルスチェックエンドポイント"""
    return jsonify({
        'status': 'ok',
        'rag_system_ready': rag_system is not None
    })


@app.route('/api/query', methods=['POST'])
def query_endpoint():
    """質問に対する回答を取得するエンドポイント"""
    try:
        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({'error': 'クエリが指定されていません'}), 400

        query_text = data['query']
        if not query_text.strip():
            return jsonify({'error': 'クエリが空です'}), 400

        logger.info(f"クエリを受信: {query_text}")

        # RAGシステムが利用可能な場合
        if rag_system is not None:
            result = rag_system.query(query_text)
            logger.info("RAGシステムからの回答を返しました")
            return jsonify(result)

        # フォールバックとして、モックレスポンスを返す
        logger.warning("RAGシステムが利用できません。モックレスポンスを返します")
        mock_response = get_mock_response(query_text)
        return jsonify(mock_response)

    except Exception as e:
        logger.error(f"クエリ処理中にエラーが発生しました: {e}")
        return jsonify({'error': f'内部エラーが発生しました: {str(e)}'}), 500


def get_mock_response(query_text: str) -> Dict[str, Any]:
    """モックレスポンスを生成する"""
    answer_text = (
        f'質問「{query_text}」に対する回答です。これはモックの回答で、'
        f'実際のRAGシステムからの応答ではありません。\n\n'
        f'実際のシステムでは、この部分に関連するドキュメントから抽出された'
        f'情報に基づいた回答が表示されます。'
    )

    return {
        'answer': answer_text,
        'sources': [
            {
                'header': 'サンプル見出し1',
                'content': (
                    'これは引用元のサンプルコンテンツです。実際のシステムでは、'
                    'ここに関連するドキュメントの内容が表示されます。'
                ),
                'doc_id': 'sample_doc_1.md',
                'section_id': 1,
                'level': 2,
                'score': 0.95
            },
            {
                'header': 'サンプル見出し2',
                'content': (
                    '別の引用元のサンプルコンテンツです。複数の引用元がある場合は、'
                    'このように複数表示されます。'
                ),
                'doc_id': 'sample_doc_2.md',
                'section_id': 3,
                'level': 1,
                'score': 0.87
            },
            {
                'header': 'サンプル見出し3',
                'content': (
                    'さらに別の引用元です。関連度スコアによって順序が決まります。'
                ),
                'doc_id': 'sample_doc_1.md',
                'section_id': 7,
                'level': 3,
                'score': 0.82
            }
        ]
    }


@app.route('/api/todos', methods=['GET'])
def get_todos():
    """TODOリストを取得するエンドポイント"""
    try:
        if rag_system is None:
            return jsonify({'error': 'RAGシステムが初期化されていません'}), 500

        status = request.args.get('status')
        todos = rag_system.get_todos(status)

        # dataclassをdictに変換
        todos_dict = [asdict(todo) for todo in todos]

        return jsonify({
            'todos': todos_dict,
            'count': len(todos_dict)
        })
    except Exception as e:
        logger.error(f"TODO取得中にエラーが発生しました: {e}")
        return jsonify({'error': f'TODO取得に失敗しました: {str(e)}'}), 500


@app.route('/api/todos', methods=['POST'])
def create_todo():
    """新しいTODOを作成するエンドポイント"""
    try:
        if rag_system is None:
            return jsonify({'error': 'RAGシステムが初期化されていません'}), 500

        data = request.get_json()
        if not data or 'content' not in data:
            return jsonify({'error': 'コンテンツが指定されていません'}), 400

        content = data['content']
        priority = data.get('priority', 'medium')
        source_file = data.get('source_file', 'manual')
        source_section = data.get('source_section', 'manual')

        todo = rag_system.add_todo(
            content, priority, source_file, source_section)

        return jsonify(asdict(todo)), 201
    except Exception as e:
        logger.error(f"TODO作成中にエラーが発生しました: {e}")
        return jsonify({'error': f'TODO作成に失敗しました: {str(e)}'}), 500


@app.route('/api/todos/<todo_id>', methods=['PUT'])
def update_todo(todo_id):
    """TODOを更新するエンドポイント"""
    try:
        if rag_system is None:
            return jsonify({'error': 'RAGシステムが初期化されていません'}), 500

        data = request.get_json()
        if not data:
            return jsonify({'error': '更新データが指定されていません'}), 400

        todo = rag_system.update_todo(todo_id, **data)

        if todo is None:
            return jsonify({'error': 'TODOが見つかりません'}), 404

        return jsonify(asdict(todo))
    except Exception as e:
        logger.error(f"TODO更新中にエラーが発生しました: {e}")
        return jsonify({'error': f'TODO更新に失敗しました: {str(e)}'}), 500


@app.route('/api/todos/<todo_id>', methods=['DELETE'])
def delete_todo(todo_id):
    """TODOを削除するエンドポイント"""
    try:
        if rag_system is None:
            return jsonify({'error': 'RAGシステムが初期化されていません'}), 500

        success = rag_system.delete_todo(todo_id)

        if not success:
            return jsonify({'error': 'TODOが見つかりません'}), 404

        return jsonify({'message': 'TODOが削除されました'})
    except Exception as e:
        logger.error(f"TODO削除中にエラーが発生しました: {e}")
        return jsonify({'error': f'TODO削除に失敗しました: {str(e)}'}), 500


@app.route('/api/todos/aggregate', methods=['GET'])
def aggregate_todos():
    """日付別にTODOを集約するエンドポイント"""
    try:
        if rag_system is None:
            return jsonify({'error': 'RAGシステムが初期化されていません'}), 500

        aggregated = rag_system.aggregate_todos_by_date()

        # dataclassをdictに変換
        result = {}
        for date, todos in aggregated.items():
            result[date] = [asdict(todo) for todo in todos]

        return jsonify(result)
    except Exception as e:
        logger.error(f"TODO集約中にエラーが発生しました: {e}")
        return jsonify({'error': f'TODO集約に失敗しました: {str(e)}'}), 500


@app.route('/api/todos/extract', methods=['POST'])
def extract_todos():
    """メモ書きからTODOを抽出するエンドポイント"""
    try:
        if rag_system is None:
            return jsonify({'error': 'RAGシステムが初期化されていません'}), 500

        new_todos_count = rag_system.extract_todos_from_documents()

        return jsonify({
            'message': f'{new_todos_count}個の新しいTODOが抽出されました',
            'new_todos_count': new_todos_count
        })
    except Exception as e:
        logger.error(f"TODO抽出中にエラーが発生しました: {e}")
        return jsonify({'error': f'TODO抽出に失敗しました: {str(e)}'}), 500


@app.route('/api/todos/overdue', methods=['GET'])
def get_overdue_todos():
    """期限切れのTODOを取得するエンドポイント"""
    try:
        if rag_system is None:
            return jsonify({'error': 'RAGシステムが初期化されていません'}), 500

        overdue_todos = rag_system.get_overdue_todos()
        todos_dict = [asdict(todo) for todo in overdue_todos]

        return jsonify({
            'todos': todos_dict,
            'count': len(todos_dict)
        })
    except Exception as e:
        logger.error(f"期限切れTODO取得中にエラーが発生しました: {e}")
        return jsonify({'error': f'期限切れTODO取得に失敗しました: {str(e)}'}), 500

# 静的ファイルを提供するエンドポイント


@app.route('/')
def serve_frontend():
    """フロントエンドのindex.htmlを提供"""
    frontend_dir = os.path.join(current_dir, '..', 'frontend')
    return send_from_directory(frontend_dir, 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    """静的ファイルを提供"""
    frontend_dir = os.path.join(current_dir, '..', 'frontend')
    return send_from_directory(frontend_dir, path)


@app.errorhandler(404)
def not_found(error):
    """404エラーハンドラー"""
    return jsonify({'error': 'エンドポイントが見つかりません'}), 404


@app.errorhandler(500)
def internal_error(error):
    """500エラーハンドラー"""
    logger.error(f"内部エラー: {error}")
    return jsonify({'error': '内部サーバーエラーが発生しました'}), 500


@app.route('/api/files', methods=['GET'])
def list_files():
    """ファイル一覧を取得するエンドポイント"""
    try:
        # テスト環境ではcurrent_dirがプロジェクトルートを指す場合があるため、
        # dataディレクトリの存在を確認して適切なパスを決定
        data_dir = None
        possible_paths = [
            os.path.join(current_dir, 'data'),  # テスト環境用
            os.path.join(current_dir, '..', '..', 'data'),  # 通常実行用
        ]

        for path in possible_paths:
            if os.path.exists(path):
                data_dir = path
                break

        if data_dir is None:
            # dataディレクトリが存在しない場合は最初のパスを使用して作成
            data_dir = possible_paths[0]
            os.makedirs(data_dir, exist_ok=True)

        files = []
        if os.path.exists(data_dir):
            for root, _, filenames in os.walk(data_dir):
                for filename in filenames:
                    if filename.endswith('.md'):
                        full_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(full_path, data_dir)

                        # ファイル情報
                        stat = os.stat(full_path)
                        files.append({
                            'path': rel_path,
                            'name': filename,
                            'folder': os.path.dirname(rel_path) or '.',
                            'size': stat.st_size,
                            'modified': int(stat.st_mtime)
                        })

        return jsonify({'files': files})
    except Exception as e:
        logger.error(f"ファイル一覧取得中にエラーが発生しました: {e}")
        return jsonify({'error': f'ファイル一覧取得に失敗しました: {str(e)}'}), 500


@app.route('/api/files/<path:file_path>', methods=['GET'])
def get_file_content(file_path):
    """ファイル内容を取得するエンドポイント"""
    try:
        # テスト環境ではcurrent_dirがプロジェクトルートを指す場合があるため、
        # dataディレクトリの存在を確認して適切なパスを決定
        data_dir = None
        possible_paths = [
            os.path.join(current_dir, 'data'),  # テスト環境用
            os.path.join(current_dir, '..', '..', 'data'),  # 通常実行用
        ]

        for path in possible_paths:
            if os.path.exists(path):
                data_dir = path
                break

        if data_dir is None:
            data_dir = possible_paths[0]

        full_path = os.path.join(data_dir, file_path)

        # セキュリティチェック：data_dir以外へのアクセスを防ぐ
        try:
            # パスを正規化してディレクトリトラバーサル攻撃を防ぐ
            normalized_data_dir = os.path.normpath(os.path.abspath(data_dir))
            normalized_full_path = os.path.normpath(
                os.path.abspath(full_path))

            if not normalized_full_path.startswith(
                    normalized_data_dir + os.sep):
                return jsonify({'error': '不正なファイルパスです'}), 400
        except (ValueError, OSError):
            return jsonify({'error': '不正なファイルパスです'}), 400

        if not os.path.exists(full_path):
            return jsonify({'error': 'ファイルが見つかりません'}), 404

        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return jsonify({
            'content': content,
            'path': file_path,
            'size': len(content.encode('utf-8'))
        })
    except Exception as e:
        logger.error(f"ファイル読み込み中にエラーが発生しました: {e}")
        return jsonify({'error': f'ファイル読み込みに失敗しました: {str(e)}'}), 500


@app.route('/api/files/<path:file_path>', methods=['PUT'])
def save_file_content(file_path):
    """ファイル内容を保存するエンドポイント"""
    try:
        data = request.get_json()
        if not data or 'content' not in data:
            return jsonify({'error': 'コンテンツが指定されていません'}), 400

        # データディレクトリのパスを決定
        data_dir = None
        possible_paths = [
            os.path.join(current_dir, 'data'),  # テスト環境用
            os.path.join(current_dir, '..', '..', 'data'),  # 通常実行用
        ]

        for path in possible_paths:
            if os.path.exists(path):
                data_dir = path
                break

        if data_dir is None:
            data_dir = possible_paths[0]

        full_path = os.path.join(data_dir, file_path)

        # セキュリティチェック：data_dir以外へのアクセスを防ぐ
        try:
            # パスを正規化してディレクトリトラバーサル攻撃を防ぐ
            normalized_data_dir = os.path.normpath(os.path.abspath(data_dir))
            normalized_full_path = os.path.normpath(
                os.path.abspath(full_path))

            if not normalized_full_path.startswith(
                    normalized_data_dir + os.sep):
                return jsonify({'error': '不正なファイルパスです'}), 400
        except (ValueError, OSError):
            return jsonify({'error': '不正なファイルパスです'}), 400

        # ディレクトリが存在しない場合は作成
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(data['content'])

        # RAGシステムが利用可能な場合、インデックスを更新
        if rag_system is not None:
            try:
                # ドキュメントハッシュを更新して、次回の初期化時に更新を検出
                rag_system.document_hashes[full_path] = "updated"
                rag_system._save_document_hashes()
            except Exception as e:
                logger.warning(f"ドキュメントハッシュの更新に失敗: {e}")

        return jsonify({
            'message': 'ファイルが保存されました',
            'path': file_path,
            'size': len(data['content'].encode('utf-8'))
        })
    except Exception as e:
        logger.error(f"ファイル保存中にエラーが発生しました: {e}")
        return jsonify({'error': f'ファイル保存に失敗しました: {str(e)}'}), 500


@app.route('/api/files/<path:file_path>', methods=['DELETE'])
def delete_file(file_path):
    """ファイルを削除するエンドポイント"""
    try:
        # データディレクトリのパスを決定
        data_dir = None
        possible_paths = [
            os.path.join(current_dir, 'data'),  # テスト環境用
            os.path.join(current_dir, '..', '..', 'data'),  # 通常実行用
        ]

        for path in possible_paths:
            if os.path.exists(path):
                data_dir = path
                break

        if data_dir is None:
            data_dir = possible_paths[0]

        full_path = os.path.join(data_dir, file_path)

        # セキュリティチェック：data_dir以外へのアクセスを防ぐ
        try:
            # パスを正規化してディレクトリトラバーサル攻撃を防ぐ
            normalized_data_dir = os.path.normpath(os.path.abspath(data_dir))
            normalized_full_path = os.path.normpath(
                os.path.abspath(full_path))

            if not normalized_full_path.startswith(
                    normalized_data_dir + os.sep):
                return jsonify({'error': '不正なファイルパスです'}), 400
        except (ValueError, OSError):
            return jsonify({'error': '不正なファイルパスです'}), 400

        if not os.path.exists(full_path):
            return jsonify({'error': 'ファイルが見つかりません'}), 404

        os.remove(full_path)

        # RAGシステムが利用可能な場合、ハッシュからも削除
        if rag_system is not None:
            try:
                if full_path in rag_system.document_hashes:
                    del rag_system.document_hashes[full_path]
                    rag_system._save_document_hashes()
            except Exception as e:
                logger.warning(f"ドキュメントハッシュの削除に失敗: {e}")

        return jsonify({'message': 'ファイルが削除されました'})
    except Exception as e:
        logger.error(f"ファイル削除中にエラーが発生しました: {e}")
        return jsonify({'error': f'ファイル削除に失敗しました: {str(e)}'}), 500


@app.route('/api/chunks/analyze/<path:file_path>', methods=['GET'])
def analyze_chunks(file_path):
    """ファイルのチャンク分析を実行するエンドポイント"""
    try:
        if rag_system is None:
            return jsonify({'error': 'RAGシステムが初期化されていません'}), 500

        # データディレクトリのパスを決定
        data_dir = None
        possible_paths = [
            os.path.join(current_dir, 'data'),  # テスト環境用
            os.path.join(current_dir, '..', '..', 'data'),  # 通常実行用
        ]

        for path in possible_paths:
            if os.path.exists(path):
                data_dir = path
                break

        if data_dir is None:
            data_dir = possible_paths[0]

        full_path = os.path.join(data_dir, file_path)

        # セキュリティチェック：data_dir以外へのアクセスを防ぐ
        try:
            # パスを正規化してディレクトリトラバーサル攻撃を防ぐ
            normalized_data_dir = os.path.normpath(os.path.abspath(data_dir))
            normalized_full_path = os.path.normpath(
                os.path.abspath(full_path))

            if not normalized_full_path.startswith(
                    normalized_data_dir + os.sep):
                return jsonify({'error': '不正なファイルパスです'}), 400
        except (ValueError, OSError):
            return jsonify({'error': '不正なファイルパスです'}), 400

        if not os.path.exists(full_path):
            return jsonify({'error': 'ファイルが見つかりません'}), 404

        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Markdownをパースしてセクションに分割
        sections = rag_system._parse_markdown(content)

        # ノードを生成
        nodes = rag_system._create_nodes_from_sections(sections, full_path)

        # 結果を整理
        chunks = []
        header_count = 0
        content_count = 0

        for node in nodes:
            chunk_info = {
                'type': node.metadata.get('type', ''),
                'text': node.text,
                'metadata': {
                    'header': node.metadata.get('header', ''),
                    'level': node.metadata.get('level', 1),
                    'section_id': node.metadata.get('section_id', 0),
                    'folder_name': node.metadata.get('folder_name', ''),
                    'file_name': node.metadata.get('file_name', ''),
                },
                'text_length': len(node.text),
                'preview': (
                    node.text[:100] +
                    ('...' if len(node.text) > 100 else '')
                )
            }
            chunks.append(chunk_info)

            if chunk_info['type'] == 'header':
                header_count += 1
            else:
                content_count += 1

        return jsonify({
            'file_path': file_path,
            'total_chunks': len(chunks),
            'header_chunks': header_count,
            'content_chunks': content_count,
            'chunks': chunks
        })
    except Exception as e:
        logger.error(f"チャンク分析中にエラーが発生しました: {e}")
        return jsonify({'error': f'チャンク分析に失敗しました: {str(e)}'}), 500


@app.route('/api/index/refresh', methods=['POST'])
def refresh_index():
    """インデックスを強制的に更新するエンドポイント"""
    try:
        if rag_system is None:
            return jsonify({'error': 'RAGシステムが初期化されていません'}), 500

        # インデックスを再構築
        rag_system.index = rag_system._create_new_index()

        return jsonify({'message': 'インデックスが更新されました'})
    except Exception as e:
        logger.error(f"インデックス更新中にエラーが発生しました: {e}")
        return jsonify({'error': f'インデックス更新に失敗しました: {str(e)}'}), 500


@app.route('/api/index/stats', methods=['GET'])
def get_index_stats():
    """インデックス統計情報を取得するエンドポイント"""
    try:
        if rag_system is None:
            return jsonify({'error': 'RAGシステムが初期化されていません'}), 500

        stats = rag_system.get_system_info()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"インデックス統計取得中にエラーが発生しました: {e}")
        return jsonify({'error': f'インデックス統計取得に失敗しました: {str(e)}'}), 500


if __name__ == '__main__':
    # RAGシステムの初期化
    initialize_rag_system()

    # デバッグモードでサーバーを起動
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
