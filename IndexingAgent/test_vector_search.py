#!/usr/bin/env python3
# test_vector_search.py
"""
VectorDB 시맨틱 검색 테스트 (대화형)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from knowledge.vector_store import VectorStore
from utils.ontology_manager import get_ontology_manager


def main():
    """대화형 시맨틱 검색"""
    print("\n" + "="*80)
    print("🔍 VectorDB Semantic Search - Interactive Mode")
    print("="*80)
    
    # VectorDB 로드
    print("\n📚 VectorDB 로드 중...")
    vector_store = VectorStore()
    
    try:
        vector_store.initialize(embedding_model="openai")  # 또는 "local"
    except Exception as e:
        print(f"❌ VectorDB 초기화 실패: {e}")
        print("\n먼저 build_vector_db.py를 실행하세요.")
        return
    
    # 온톨로지 로드 (Context Assembly용)
    ontology_mgr = get_ontology_manager()
    ontology = ontology_mgr.load()
    
    print("✅ VectorDB 준비 완료")
    print("\n" + "="*80)
    print("사용 방법:")
    print("  - 자연어로 질문하세요")
    print("  - 'table:', 'column:', 'rel:' 접두사로 필터 가능")
    print("  - 'quit' 또는 'exit'로 종료")
    print("="*80)
    
    # 대화형 루프
    while True:
        print("\n" + "-"*80)
        query = input("🔍 검색어: ").strip()
        
        if not query:
            continue
        
        if query.lower() in ['quit', 'exit', 'q']:
            print("👋 종료합니다.")
            break
        
        # 필터 타입 파싱
        filter_type = None
        if query.startswith("table:"):
            filter_type = "table_summary"
            query = query[6:].strip()
        elif query.startswith("column:") or query.startswith("col:"):
            filter_type = "column_definition"
            query = query[query.index(':')+1:].strip()
        elif query.startswith("rel:") or query.startswith("relationship:"):
            filter_type = "relationship"
            query = query[query.index(':')+1:].strip()
        
        # 검색
        try:
            results = vector_store.semantic_search(
                query=query,
                n_results=5,
                filter_type=filter_type
            )
            
            if not results:
                print("❌ 결과 없음")
                continue
            
            print(f"\n📊 결과: {len(results)}개")
            print("─"*80)
            
            for i, result in enumerate(results, 1):
                meta = result["metadata"]
                doc = result["document"]
                
                result_type = meta.get("type", "unknown")
                
                # 아이콘
                icons = {
                    "table_summary": "📊",
                    "column_definition": "📋",
                    "relationship": "🔗"
                }
                icon = icons.get(result_type, "•")
                
                print(f"\n{icon} Result {i} [{result_type}]")
                print("─"*80)
                
                # 타입별 출력
                if result_type == "table_summary":
                    print(doc)
                elif result_type == "column_definition":
                    col_name = meta.get("column_name", "?")
                    print(f"Column: {col_name}")
                    print(doc)
                elif result_type == "relationship":
                    source = meta.get("source", "?")
                    target = meta.get("target", "?")
                    print(f"{source} → {target}")
                    print(doc)
                else:
                    print(doc[:200])
            
            # Context Assembly 옵션
            print("\n" + "─"*80)
            assemble = input("🔧 Context Assembly 실행? (y/n, 기본값: n): ").strip().lower()
            
            if assemble == 'y':
                context = vector_store.assemble_context(results, ontology)
                
                print("\n📦 Assembled Context:")
                print(f"   - Primary Results: {len(context['primary_results'])}개")
                print(f"   - Related Tables: {context['related_tables']}")
                print(f"   - JOIN Paths: {context['join_paths']}")
                
                print("\n💡 이 컨텍스트를 LLM에게 전달하여 SQL 생성 가능")
        
        except Exception as e:
            print(f"❌ 검색 실패: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n✅ 검색 세션 종료")


if __name__ == "__main__":
    main()

