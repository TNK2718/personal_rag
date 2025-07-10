from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import sys
import logging
from typing import Dict, Any

# 現在のディレクトリをsys.pathに追加
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from rag_system import RAGSystem

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
        # プロジェクトルートからの相対パスを使用
        project_root = os.path.join(current_dir, '..', '..')
        persist_dir = os.path.join(project_root, 'storage')
        data_dir = os.path.join(project_root, 'data')
        
        rag_system = RAGSystem(
            persist_dir=persist_dir,
            data_dir=data_dir
        )
        logger.info("RAGシステムの初期化が完了しました")
    except Exception as e:
        logger.error(f"RAGシステムの初期化に失敗しました: {e}")
        # フォールバックとして、モックシステムを使用
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
    return {
        'answer': f'質問「{query_text}」に対する回答です。これはモックの回答で、実際のRAGシステムからの応答ではありません。\n\n実際のシステムでは、この部分に関連するドキュメントから抽出された情報に基づいた回答が表示されます。',
        'sources': [
            {
                'header': 'サンプル見出し1',
                'content': 'これは引用元のサンプルコンテンツです。実際のシステムでは、ここに関連するドキュメントの内容が表示されます。',
                'doc_id': 'sample_doc_1.md',
                'section_id': 1,
                'level': 2,
                'score': 0.95
            },
            {
                'header': 'サンプル見出し2',
                'content': '別の引用元のサンプルコンテンツです。複数の引用元がある場合は、このように複数表示されます。',
                'doc_id': 'sample_doc_2.md',
                'section_id': 3,
                'level': 1,
                'score': 0.87
            },
            {
                'header': 'サンプル見出し3',
                'content': 'さらに別の引用元です。関連度スコアによって順序が決まります。',
                'doc_id': 'sample_doc_1.md',
                'section_id': 7,
                'level': 3,
                'score': 0.82
            }
        ]
    }

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

if __name__ == '__main__':
    # RAGシステムの初期化
    initialize_rag_system()
    
    # デバッグモードでサーバーを起動
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)