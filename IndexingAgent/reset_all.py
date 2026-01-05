#!/usr/bin/env python3
"""
IndexingAgent 전체 초기화 스크립트

- PostgreSQL: 모든 테이블 삭제 (file_catalog, column_metadata 포함)
- Neo4j: 모든 노드/관계 삭제
- 온톨로지 JSON: 초기화

사용법:
    python reset_all.py              # 확인 후 삭제
    python reset_all.py -y           # 확인 없이 삭제
    python reset_all.py --no-recreate    # 테이블 삭제만 (재생성 안 함)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dotenv import load_dotenv
load_dotenv()


def reset_postgres(recreate_tables=True):
    """PostgreSQL 모든 테이블 삭제 및 재생성
    
    모든 public 스키마의 테이블을 CASCADE로 강제 삭제한 후,
    필요시 빈 테이블을 재생성합니다.
    
    Args:
        recreate_tables: True면 삭제 후 빈 테이블 재생성
    """
    print("\n" + "=" * 60)
    print("🗄️  [PostgreSQL] 초기화 중...")
    print("=" * 60)
    
    try:
        from src.database import (
            CatalogSchemaManager,
            DictionarySchemaManager,
            OntologySchemaManager,
            DirectorySchemaManager,
            ParameterSchemaManager,
            get_db_manager,
        )
        db = get_db_manager()
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # 1. 현재 테이블 목록 조회
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        if tables:
            print(f"   - 삭제 대상 테이블: {len(tables)}개")
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"     • {table} ({count}개 row)")
        else:
            print("   - 삭제할 테이블 없음")
        
        # 2. 모든 테이블 강제 삭제 (CASCADE)
        print("\n   📤 모든 테이블 강제 삭제 (CASCADE)...")
        cursor.execute("""
            DO $$ 
            DECLARE 
                r RECORD;
            BEGIN
                -- 모든 public 스키마 테이블 삭제
                FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') 
                LOOP
                    EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE';
                END LOOP;
            END $$;
        """)
        conn.commit()
        
        # 삭제 확인
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
        """)
        remaining = cursor.fetchall()
        if remaining:
            print(f"   ⚠️ 남은 테이블: {[r[0] for r in remaining]}")
        else:
            print("   ✅ 모든 테이블 삭제됨")
        
        # 3. 테이블 재생성 (FK 참조 순서대로)
        # 순서: Directory → Catalog → Dictionary → Parameter → Ontology
        if recreate_tables:
            print("\n   📥 테이블 생성 (FK 참조 순서)...")
            try:
                DirectorySchemaManager().create_tables()
            except Exception as e:
                print(f"      ⚠️ Directory: {e}")
            
            try:
                CatalogSchemaManager().create_tables()
            except Exception as e:
                print(f"      ⚠️ Catalog: {e}")
            
            try:
                DictionarySchemaManager().create_tables()
            except Exception as e:
                print(f"      ⚠️ Dictionary: {e}")
            
            try:
                ParameterSchemaManager().create_tables()
            except Exception as e:
                print(f"      ⚠️ Parameter: {e}")
            
            try:
                OntologySchemaManager().create_tables()
            except Exception as e:
                print(f"      ⚠️ Ontology: {e}")
        
        print("✅ [PostgreSQL] 초기화 완료")
        
    except Exception as e:
        print(f"❌ [PostgreSQL] 오류: {e}")
        import traceback
        traceback.print_exc()


def reset_neo4j():
    """Neo4j 모든 노드/관계 삭제"""
    print("\n" + "=" * 60)
    print("🔗 [Neo4j] 초기화 중...")
    print("=" * 60)
    
    try:
        from src.database import get_neo4j_connection
        
        neo4j = get_neo4j_connection()
        neo4j.connect()
        
        # 노드 수 확인
        result = neo4j.execute_query("MATCH (n) RETURN count(n) as count")
        node_count = result[0]["count"] if result else 0
        
        result = neo4j.execute_query("MATCH ()-[r]->() RETURN count(r) as count")
        rel_count = result[0]["count"] if result else 0
        
        print(f"   - 삭제 대상: 노드 {node_count}개, 관계 {rel_count}개")
        
        if node_count > 0 or rel_count > 0:
            # 모든 노드와 관계 삭제
            neo4j.execute_query("MATCH (n) DETACH DELETE n")
            print("   ✅ 모든 노드/관계 삭제됨")
        else:
            print("   - 삭제할 데이터 없음")
        
        print("✅ [Neo4j] 초기화 완료")
        
    except Exception as e:
        print(f"❌ [Neo4j] 오류: {e}")


def reset_ontology_json():
    """온톨로지 JSON 파일 초기화"""
    print("\n" + "=" * 60)
    print("📚 [온톨로지 JSON] 초기화 중...")
    print("=" * 60)
    
    ontology_path = os.path.join(
        os.path.dirname(__file__), 
        "data", "processed", "ontology_db.json"
    )
    
    if os.path.exists(ontology_path):
        os.remove(ontology_path)
        print(f"   ✅ 삭제됨: {ontology_path}")
    else:
        print(f"   - 파일 없음: {ontology_path}")
    
    print("✅ [온톨로지 JSON] 초기화 완료")


def print_help():
    """도움말 출력"""
    print("""
사용법: python reset_all.py [옵션]

옵션:
    -y, --yes          확인 없이 실행
    --no-recreate      테이블 삭제만 (재생성 안 함)
    -h, --help         도움말 출력

예시:
    python reset_all.py              # 확인 후 삭제/재생성
    python reset_all.py -y           # 확인 없이 삭제/재생성
    python reset_all.py --no-recreate -y  # 테이블 삭제만 (재생성 안 함)
""")


def main():
    print("\n" + "=" * 60)
    print("🔄 IndexingAgent 전체 초기화")
    print("=" * 60)
    
    # 도움말
    if "-h" in sys.argv or "--help" in sys.argv:
        print_help()
        return
    
    # 옵션 파싱
    skip_confirm = "-y" in sys.argv or "--yes" in sys.argv
    no_recreate = "--no-recreate" in sys.argv
    
    if not skip_confirm:
        print("\n⚠️  경고: 모든 데이터가 삭제됩니다!")
        print("   - PostgreSQL 테이블 (file_catalog, column_metadata 등)")
        if no_recreate:
            print("     → 테이블 삭제만 (재생성 안 함)")
        else:
            print("     → 삭제 후 빈 테이블 재생성")
        print("   - Neo4j 노드/관계")
        print("   - 온톨로지 JSON")
        
        confirm = input("\n계속하시겠습니까? (y/N): ").strip().lower()
        if confirm != 'y':
            print("취소되었습니다.")
            return
    
    # 초기화 실행
    reset_postgres(recreate_tables=not no_recreate)
    reset_neo4j()
    reset_ontology_json()
    
    print("\n" + "=" * 60)
    print("✅ 전체 초기화 완료!")
    print("=" * 60)
    print("\n이제 IndexingAgent를 다시 실행할 수 있습니다:")
    print("  python test_full_pipeline_results.py")
    print()


if __name__ == "__main__":
    main()

