#!/usr/bin/env python3
"""
シンプルなRAGデバッグスクリプト
"""
import sys
import os
sys.path.append('src/server')


def main():
    print("=== RAGデバッグ開始 ===")

    try:
        # RAGシステムの初期化をモック環境で実行
        os.environ['IS_TESTING'] = 'true'

        from rag_system import RAGSystem
        print("RAGシステムインポート完了")

        # 直接クエリ実行を試みる
        rag = RAGSystem()
        print("RAGシステム初期化完了")

        query = "NeoTrack GPS ランニング"
        print(f"クエリ実行: {query}")

        result = rag.query(query)
        print(f"結果: {result}")

    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
