#!/usr/bin/env python3
"""
NeoTrackクエリの問題をデバッグするスクリプト
"""
import json
from rag_system import RAGSystem
import os
import sys
sys.path.append('src/server')


def debug_neotrack_query():
    """NeoTrackクエリの問題を詳細に調査"""
    print("=== NeoTrackクエリデバッグ開始 ===")

    try:
        # RAGシステム初期化
        print("1. RAGシステムを初期化中...")
        rag_system = RAGSystem(
            persist_dir="./storage",
            data_dir="./data"
        )
        print("   ✓ 初期化完了")

        # インデックス情報確認
        print("2. インデックス情報を確認中...")
        if hasattr(rag_system.index, '_docstore'):
            print(
                f"   ドキュメント数: {len(rag_system.index._docstore.docs) if rag_system.index._docstore else 'N/A'}")

        # クエリ実行
        query_text = "NeoTrackは、GPSベースのランニングトラッキングアプリケーションですか？"
        print(f"3. クエリ実行: '{query_text}'")

        # 詳細なデバッグ情報付きでクエリ実行
        result = rag_system.query(query_text)

        print("\n=== 検索結果 ===")
        print(f"回答: {result['answer']}")
        print(f"\nソース数: {len(result['sources'])}")

        for i, source in enumerate(result['sources'], 1):
            print(f"\n--- ソース {i} ---")
            print(f"ファイル: {source.get('file_name', 'N/A')}")
            print(f"フォルダ: {source.get('folder_name', 'N/A')}")
            print(f"ヘッダー: {source.get('header', 'N/A')}")
            print(f"スコア: {source.get('score', 'N/A'):.4f}")
            print(f"タイプ: {source.get('type', 'N/A')}")
            print(f"テキスト長: {source.get('text_length', 'N/A')}")
            print(f"内容: {source.get('content', '')[:200]}...")

        # samplememo.mdが含まれているかチェック
        samplememo_found = any('samplememo' in source.get('file_name', '').lower()
                               for source in result['sources'])

        print(f"\n=== 分析結果 ===")
        print(f"samplememo.md がトップ3に含まれている: {samplememo_found}")

        if not samplememo_found:
            print("\n🔍 問題: samplememo.mdがトップ3に含まれていません！")

            # より詳細な分析のため、retrieverを直接呼び出し
            print("\n4. Retrieverを直接テスト中...")
            retriever = rag_system.index.as_retriever(similarity_top_k=10)
            all_nodes = retriever.retrieve(query_text)

            print(f"Retrieverから取得したノード数: {len(all_nodes)}")

            # samplememo.mdのノードを探す
            samplememo_nodes = []
            for i, node in enumerate(all_nodes):
                if 'samplememo' in node.metadata.get('doc_id', '').lower():
                    samplememo_nodes.append((i, node))

            print(f"samplememo.mdのノード数: {len(samplememo_nodes)}")

            if samplememo_nodes:
                print("\nsamplememo.mdのノード詳細:")
                for rank, (orig_index, node) in enumerate(samplememo_nodes[:5]):
                    print(f"  ランク {orig_index+1}: スコア={node.score:.4f}")
                    print(f"    ヘッダー: {node.metadata.get('header', 'N/A')}")
                    print(f"    タイプ: {node.metadata.get('type', 'N/A')}")
                    print(f"    内容: {node.text[:100]}...")
                    print()
            else:
                print("❌ samplememo.mdのノードが全く見つかりませんでした！")
                print("   これはインデックス化の問題の可能性があります。")

    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    debug_neotrack_query()
