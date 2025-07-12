#!/usr/bin/env python3
"""
クエリ実行時のsentence boundary chunkingデバッグ
"""

from src.server.rag_system import RAGSystem
import sys
import os
import time
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def test_query_execution():
    print("=== クエリ実行テスト ===")

    # RAGSystemインスタンスを作成
    try:
        print("RAGSystem作成開始...")
        rag_system = RAGSystem()
        print("RAGSystem作成成功")
    except Exception as e:
        print(f"RAGSystem作成失敗: {e}")
        return

    # 簡単なクエリを実行
    test_queries = [
        "NeoTrackとは何ですか？",
        "インフラストラクチャについて教えてください",
        "セキュリティ設計について",
    ]

    for query in test_queries:
        print(f"\n--- クエリ: {query} ---")
        try:
            print("クエリ実行開始...")
            start_time = time.time()

            # タイムアウトを設定してクエリを実行
            result = rag_system.query(query)

            query_time = time.time() - start_time
            print(f"クエリ実行完了 ({query_time:.2f}秒)")

            # 結果を表示
            if isinstance(result, dict):
                answer = result.get('answer', 'No answer')
                sources = result.get('sources', [])
                print(f"回答: {answer[:100]}...")
                print(f"ソース数: {len(sources)}")
            else:
                print(f"結果: {str(result)[:100]}...")

        except Exception as e:
            print(f"クエリ実行中にエラー: {e}")
            import traceback
            traceback.print_exc()


def test_document_processing():
    print("\n=== ドキュメント処理テスト ===")

    try:
        print("RAGSystem作成開始...")
        rag_system = RAGSystem()
        print("RAGSystem作成成功")
    except Exception as e:
        print(f"RAGSystem作成失敗: {e}")
        return

    # ドキュメントの更新チェック
    try:
        print("ドキュメント更新チェック...")
        updated_files = rag_system._check_document_updates()
        print(f"更新されたファイル数: {len(updated_files)}")

        for file_path in updated_files:
            print(f"  更新ファイル: {file_path}")

        # 手動でドキュメントを読み込み
        print("ドキュメント読み込み...")
        documents = rag_system.load_documents()
        print(f"読み込み完了: {len(documents)}個のドキュメント")

    except Exception as e:
        print(f"ドキュメント処理中にエラー: {e}")
        import traceback
        traceback.print_exc()


def test_retrieval_only():
    print("\n=== 検索のみテスト ===")

    try:
        print("RAGSystem作成開始...")
        rag_system = RAGSystem()
        print("RAGSystem作成成功")
    except Exception as e:
        print(f"RAGSystem作成失敗: {e}")
        return

    # 検索のみ実行（LLMは使わない）
    test_query = "NeoTrackとは何ですか？"

    try:
        print("検索開始...")
        retriever = rag_system.index.as_retriever(similarity_top_k=5)
        nodes = retriever.retrieve(test_query)
        print(f"検索完了: {len(nodes)}個のノード")

        for i, node in enumerate(nodes):
            print(f"ノード {i+1}: {node.metadata.get('header', 'no header')}")
            print(f"  スコア: {node.score}")
            print(f"  テキスト: {node.text[:50]}...")
            print()

    except Exception as e:
        print(f"検索中にエラー: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_document_processing()
    test_retrieval_only()
    test_query_execution()
