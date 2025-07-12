#!/usr/bin/env python3
"""
インデックス化問題のデバッグスクリプト
"""
import sys
import os
sys.path.append('src/server')


def debug_indexing():
    """インデックス化の問題を詳細に調査"""
    print("=== インデックス化デバッグ ===")

    try:
        from rag_system import RAGSystem

        # RAGシステム初期化（テスト環境でOllamaなしで実行）
        os.environ['IS_TESTING'] = 'true'

        # 直接ドキュメント読み込みをテスト
        print("1. 直接ドキュメント読み込みテスト")
        from llama_index.core import SimpleDirectoryReader

        # samplememo.mdを直接読み込み
        samplememo_path = "data/project1/samplememo.md"
        print(f"samplememo.mdパス: {samplememo_path}")
        print(f"ファイル存在確認: {os.path.exists(samplememo_path)}")

        if os.path.exists(samplememo_path):
            reader = SimpleDirectoryReader(input_files=[samplememo_path])
            docs = reader.load_data()
            print(f"読み込まれたドキュメント数: {len(docs)}")

            if docs:
                doc = docs[0]
                print(f"ドキュメントID: {doc.doc_id}")
                print(f"テキスト長: {len(doc.text)}")
                print(f"テキスト開始部分: {doc.text[:200]}...")

                # RAGシステムでセクション分割をテスト
                print("\n2. セクション分割テスト")
                rag = object.__new__(RAGSystem)
                from markdown_it import MarkdownIt
                rag.md_parser = MarkdownIt()
                rag.data_dir = "./data"
                rag.todos = []

                # 実際のメソッドを取得
                from rag_system import RAGSystem as RealRAG
                real_rag = RealRAG.__new__(RealRAG)

                sections = real_rag._parse_markdown.__func__(rag, doc.text)
                print(f"分割されたセクション数: {len(sections)}")

                for i, section in enumerate(sections[:5]):  # 最初の5つのセクション
                    print(
                        f"  セクション {i}: '{section.header}' (レベル{section.level})")
                    print(f"    コンテンツ長: {len(section.content)}")
                    print(f"    コンテンツ開始: {section.content[:100]}...")

                # ノード作成をテスト
                print("\n3. ノード作成テスト")
                nodes = real_rag._create_nodes_from_sections.__func__(
                    rag, sections, doc.doc_id
                )
                print(f"作成されたノード数: {len(nodes)}")

                for i, node in enumerate(nodes[:5]):  # 最初の5つのノード
                    print(f"  ノード {i}:")
                    print(f"    タイプ: {node.metadata.get('type')}")
                    print(f"    ヘッダー: {node.metadata.get('header')}")
                    print(f"    ファイル名: {node.metadata.get('file_name')}")
                    print(f"    テキスト長: {len(node.text)}")
                    print(f"    テキスト: {node.text[:100]}...")
        else:
            print("❌ samplememo.mdファイルが見つかりません！")

        # 全体のディレクトリ構造確認
        print("\n4. データディレクトリ構造確認")
        for root, dirs, files in os.walk("data"):
            level = root.replace("data", "").count(os.sep)
            indent = " " * 2 * level
            print(f"{indent}{os.path.basename(root)}/")
            subindent = " " * 2 * (level + 1)
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
                    file_size = os.path.getsize(file_path)
                    print(f"{subindent}{file} ({file_size} bytes)")

    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    debug_indexing()
