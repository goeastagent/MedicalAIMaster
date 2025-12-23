#!/usr/bin/env python3
# view_ontology.py
"""
온톨로지 DB 확인 스크립트 (Neo4j 기반)

Neo4j에 구축된 온톨로지 지식 그래프를 조회하여 내용을 출력합니다.
"""

import sys
import os
import logging

# 로깅 설정 (라이브러리 로그는 경고 이상만)
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("view_ontology")
logger.setLevel(logging.INFO)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.utils.ontology_manager import get_ontology_manager
from src.database.neo4j_connection import Neo4jConnection

def main():
    """온톨로지 내용 확인"""
    print("\n" + "="*80)
    print("🧠 Ontology Knowledge Graph Viewer (Neo4j)")
    print("="*80)
    
    # 1. Neo4j 연결 확인
    print("🔌 Neo4j 연결 확인 중...")
    try:
        neo4j_conn = Neo4jConnection()
        neo4j_conn.connect()
        print("✅ Neo4j 연결 성공")
    except Exception as e:
        print(f"\n❌ Neo4j 연결 실패: {e}")
        print("----------------------------------------------------------------")
        print("💡 Tip: .env 파일의 NEO4J_USER, NEO4J_PASSWORD 설정을 확인하세요.")
        print("        또는 run_postgres_neo4j.sh 스크립트가 실행 중인지 확인하세요.")
        print("----------------------------------------------------------------")
        return

    # 2. 온톨로지 로드
    print("\n📥 온톨로지 데이터 로드 중...")
    try:
        manager = get_ontology_manager()
        ontology = manager.load()
    except Exception as e:
        print(f"❌ 데이터 로드 중 오류 발생: {e}")
        return
    
    # 3. 데이터 검증
    definitions = ontology.get("definitions", {})
    relationships = ontology.get("relationships", [])
    hierarchy = ontology.get("hierarchy", [])
    
    if not definitions and not relationships:
        print("\n⚠️  온톨로지가 비어있습니다 (데이터 없음).")
        print("   먼저 test_agent_with_interrupt.py를 실행하여 데이터를 인덱싱하세요.")
        return
    
    # 4. 요약 출력
    print(manager.export_summary())
    
    # 5. 상세 내용 출력 (사용자 인터랙션)
    while True:
        print("\n" + "-"*50)
        print("🔍 상세 조회 메뉴:")
        print("1. Definitions (용어 사전) 보기")
        print("2. Relationships (관계) 보기")
        print("3. Hierarchy (계층 구조) 보기")
        print("q. 종료")
        print("-" * 50)
        
        choice = input("선택 >>> ").strip().lower()
        
        if choice == 'q':
            break
            
        elif choice == '1':
            print("\n" + "="*80)
            print("📖 Definitions (Top 20)")
            print("="*80)
            for i, (key, val) in enumerate(sorted(definitions.items())[:20]):
                print(f"\n{i+1}. {key}")
                print(f"   {val}")
            if len(definitions) > 20:
                print(f"\n... (총 {len(definitions)}개 중 20개 표시됨)")

        elif choice == '2':
            print("\n" + "="*80)
            print("🔗 Relationships (Top 20)")
            print("="*80)
            for i, rel in enumerate(relationships[:20]):
                print(f"\n{i+1}. {rel['source_table']} -> {rel['target_table']}")
                print(f"   Type: {rel['relation_type']}")
                print(f"   On: {rel.get('source_column', '')} = {rel.get('target_column', '')}")
            if len(relationships) > 20:
                print(f"\n... (총 {len(relationships)}개 중 20개 표시됨)")

        elif choice == '3':
            print("\n" + "="*80)
            print("🏗️  Hierarchy")
            print("="*80)
            for h in sorted(hierarchy, key=lambda x: x['level']):
                print(f"\nLevel {h['level']}: {h['entity_name']}")
                print(f"  - Anchor: {h.get('anchor_column', 'N/A')}")
                print(f"  - Confidence: {h.get('confidence', 0):.1%}")

    print("\n👋 종료합니다.")

if __name__ == "__main__":
    main()
