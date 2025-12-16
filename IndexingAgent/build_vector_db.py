#!/usr/bin/env python3
# build_vector_db.py
"""
VectorDB 구축 스크립트

온톨로지 파일을 읽어서 ChromaDB에 임베딩 생성
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.ontology_manager import get_ontology_manager
from knowledge.vector_store import VectorStore


def main():
    """VectorDB 구축 메인 함수"""
    print("\n" + "="*80)
    print("🚀 VectorDB 구축 시작")
    print("="*80)
    
    # 1. 온톨로지 로드
    print("\n📚 [Step 1] 온톨로지 로드 중...")
    ontology_mgr = get_ontology_manager()
    ontology = ontology_mgr.load()
    
    if not ontology or not ontology.get("definitions"):
        print("❌ 온톨로지가 비어있습니다.")
        print("먼저 test_agent_with_interrupt.py를 실행하세요.")
        return
    
    print(f"✅ 온톨로지 로드 완료")
    print(f"   - 용어: {len(ontology.get('definitions', {}))}개")
    print(f"   - 관계: {len(ontology.get('relationships', []))}개")
    print(f"   - 계층: {len(ontology.get('hierarchy', []))}개")
    print(f"   - 파일: {len(ontology.get('file_tags', {}))}개")
    
    # 2. VectorDB 초기화
    print("\n🔧 [Step 2] VectorDB 초기화 중...")
    
    vector_store = VectorStore()
    
    # 임베딩 모델 선택
    print("\n임베딩 모델 선택:")
    print("  1. OpenAI (정확도 높음, 비용 있음)")
    print("  2. Local (무료, 속도 느림)")
    
    choice = input("\n선택 (1 or 2, 기본값: 1): ").strip()
    
    if choice == "2":
        embedding_model = "local"
        print("✅ Local 모델 사용 (all-MiniLM-L6-v2)")
    else:
        embedding_model = "openai"
        print("✅ OpenAI 모델 사용 (text-embedding-3-small)")
        
        # API 키 확인
        if not os.getenv("OPENAI_API_KEY"):
            print("❌ OPENAI_API_KEY가 설정되지 않았습니다.")
            print(".env 파일에 OPENAI_API_KEY를 설정하세요.")
            return
    
    try:
        vector_store.initialize(embedding_model=embedding_model)
    except Exception as e:
        print(f"❌ VectorDB 초기화 실패: {e}")
        return
    
    # 3. 임베딩 생성
    print("\n📝 [Step 3] 임베딩 생성 중...")
    
    try:
        vector_store.build_index(ontology)
    except Exception as e:
        print(f"❌ 임베딩 생성 실패: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 4. 검증 테스트
    print("\n" + "="*80)
    print("✅ VectorDB 구축 완료!")
    print("="*80)
    
    print("\n🧪 [테스트] 시맨틱 검색 테스트...")
    
    # 테스트 쿼리들
    test_queries = [
        ("혈압 관련 데이터", None),
        ("환자 식별자", "column"),
        ("환자 정보 테이블", "table"),
        ("lab 데이터는 어떻게 연결되나", "relationship")
    ]
    
    for query, filter_type in test_queries:
        print(f"\n📍 Query: '{query}' (filter: {filter_type or 'all'})")
        
        try:
            results = vector_store.semantic_search(query, n_results=3, filter_type=filter_type)
            
            if results:
                for i, result in enumerate(results, 1):
                    meta = result["metadata"]
                    doc_preview = result["document"][:100].replace('\n', ' ')
                    print(f"   {i}. [{meta.get('type', '?')}] {doc_preview}...")
            else:
                print("   결과 없음")
        except Exception as e:
            print(f"   ❌ 검색 실패: {e}")
    
    print("\n" + "="*80)
    print("✅ 모든 작업 완료!")
    print("="*80)
    
    print("\n사용 방법:")
    print("  python test_vector_search.py  # 대화형 검색")


if __name__ == "__main__":
    main()

