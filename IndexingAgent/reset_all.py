#!/usr/bin/env python3
"""
IndexingAgent 전체 초기화 스크립트

- PostgreSQL: 모든 테이블 삭제 (file_catalog, column_metadata 포함)
- Neo4j: 모든 노드/관계 삭제
- VectorDB: ChromaDB 컬렉션 삭제
- 온톨로지 JSON: 초기화
- LLM 캐시: 삭제

사용법:
    python reset_all.py              # 확인 후 삭제 (캐시 제외)
    python reset_all.py -y           # 확인 없이 삭제 (캐시 제외)
    python reset_all.py --clear-cache   # 캐시도 삭제 (확인 필요)
    python reset_all.py --all -y     # 전체 삭제 (캐시 포함, 확인 없이)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dotenv import load_dotenv
load_dotenv()


def reset_postgres(recreate_tables=True):
    """PostgreSQL 모든 테이블 삭제 및 재생성
    
    FK 참조 관계로 인해 삭제/생성 순서가 중요:
    - 삭제: Ontology → Dictionary → Catalog (참조하는 것 먼저)
    - 생성: Catalog → Dictionary → Ontology (참조되는 것 먼저)
    
    Args:
        recreate_tables: True면 삭제 후 빈 테이블 재생성
    """
    print("\n" + "=" * 60)
    print("🗄️  [PostgreSQL] 초기화 중...")
    print("=" * 60)
    
    try:
        from database.schema_catalog import CatalogSchemaManager
        from database.schema_dictionary import DictionarySchemaManager
        from database.schema_ontology import OntologySchemaManager
        from database.schema_directory import DirectorySchemaManager
        
        # 현재 테이블 목록 조회
        from database.connection import get_db_manager
        db = get_db_manager()
        conn = db.get_connection()
        cursor = conn.cursor()
        
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
                print(f"     • {table}")
        else:
            print("   - 삭제할 테이블 없음")
        
        # 1. 삭제: FK 참조하는 테이블 먼저 (역순)
        # 순서: Ontology → Dictionary → Catalog → Directory
        print("\n   📤 테이블 삭제 (FK 참조 순서)...")
        try:
            OntologySchemaManager().drop_tables(confirm=True)
        except Exception as e:
            print(f"      ⚠️ Ontology: {e}")
        
        try:
            DictionarySchemaManager().drop_tables(confirm=True)
        except Exception as e:
            print(f"      ⚠️ Dictionary: {e}")
        
        try:
            CatalogSchemaManager().drop_tables(confirm=True)
        except Exception as e:
            print(f"      ⚠️ Catalog: {e}")
        
        try:
            DirectorySchemaManager().drop_tables(confirm=True)
        except Exception as e:
            print(f"      ⚠️ Directory: {e}")
        
        # 2. 생성: FK 참조되는 테이블 먼저 (정순)
        # 순서: Directory → Catalog → Dictionary → Ontology
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
                OntologySchemaManager().create_tables()
            except Exception as e:
                print(f"      ⚠️ Ontology: {e}")
        
        print("✅ [PostgreSQL] 초기화 완료")
        
    except Exception as e:
        print(f"❌ [PostgreSQL] 오류: {e}")


def reset_neo4j():
    """Neo4j 모든 노드/관계 삭제"""
    print("\n" + "=" * 60)
    print("🔗 [Neo4j] 초기화 중...")
    print("=" * 60)
    
    try:
        from database.neo4j_connection import get_neo4j_connection
        
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


def reset_vector_db():
    """VectorDB (ChromaDB) 초기화"""
    print("\n" + "=" * 60)
    print("🔢 [VectorDB] 초기화 중...")
    print("=" * 60)
    
    import shutil
    
    vector_db_path = os.path.join(
        os.path.dirname(__file__), 
        "data", "processed", "vector_db"
    )
    
    if os.path.exists(vector_db_path):
        file_count = sum(1 for _ in os.scandir(vector_db_path) if _.is_file())
        shutil.rmtree(vector_db_path)
        os.makedirs(vector_db_path, exist_ok=True)
        print(f"   ✅ 삭제됨: {vector_db_path} ({file_count}개 파일)")
    else:
        print(f"   - 폴더 없음: {vector_db_path}")
    
    print("✅ [VectorDB] 초기화 완료")


def reset_llm_cache(confirm=False):
    """LLM 캐시 삭제 (JSON 캐시 + diskcache 모두 삭제)"""
    print("\n" + "=" * 60)
    print("🧠 [LLM 캐시] 초기화 중...")
    print("=" * 60)
    
    import shutil
    
    # 캐시 디렉토리 목록 (JSON 캐시 + diskcache)
    cache_dirs = [
        os.path.join(os.path.dirname(__file__), "data", "cache", "llm"),       # 옛 JSON 캐시
        os.path.join(os.path.dirname(__file__), "data", "cache", "llm_disk"),  # diskcache
    ]
    
    total_deleted = 0
    
    for cache_dir in cache_dirs:
        dir_name = os.path.basename(cache_dir)
        
        if os.path.exists(cache_dir):
            cache_files = os.listdir(cache_dir)
            print(f"   - [{dir_name}] 캐시 파일: {len(cache_files)}개")
            
            if confirm:
                shutil.rmtree(cache_dir)
                os.makedirs(cache_dir)
                print(f"   ✅ [{dir_name}] 삭제됨")
                total_deleted += len(cache_files)
            else:
                print(f"   ⚠️  [{dir_name}] 삭제 스킵 (--clear-cache 옵션으로 삭제)")
        else:
            print(f"   - [{dir_name}] 폴더 없음")
    
    if confirm and total_deleted > 0:
        print(f"   📊 총 {total_deleted}개 캐시 항목 삭제됨")
    
    print("✅ [LLM 캐시] 처리 완료")


def print_help():
    """도움말 출력"""
    print("""
사용법: python reset_all.py [옵션]

옵션:
    -y, --yes          확인 없이 실행
    --clear-cache      LLM 캐시도 삭제
    --all              전체 삭제 (캐시 포함)
    --no-recreate      테이블 삭제만 (재생성 안 함)
    -h, --help         도움말 출력

예시:
    python reset_all.py              # 확인 후 삭제/재생성 (캐시 제외)
    python reset_all.py -y           # 확인 없이 삭제/재생성 (캐시 제외)
    python reset_all.py --all -y     # 전체 삭제/재생성 (캐시 포함, 확인 없이)
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
    clear_all = "--all" in sys.argv
    clear_cache = "--clear-cache" in sys.argv or clear_all
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
        print("   - VectorDB (ChromaDB)")
        print("   - 온톨로지 JSON")
        if clear_cache:
            print("   - LLM 캐시 ✓")
        else:
            print("   - LLM 캐시 (--all 또는 --clear-cache로 삭제)")
        
        confirm = input("\n계속하시겠습니까? (y/N): ").strip().lower()
        if confirm != 'y':
            print("취소되었습니다.")
            return
    
    # 초기화 실행
    reset_postgres(recreate_tables=not no_recreate)
    reset_neo4j()
    reset_vector_db()
    reset_ontology_json()
    reset_llm_cache(confirm=clear_cache)
    
    print("\n" + "=" * 60)
    print("✅ 전체 초기화 완료!")
    print("=" * 60)
    print("\n이제 IndexingAgent를 다시 실행할 수 있습니다:")
    print("  python test_full_pipeline_results.py")
    print()


if __name__ == "__main__":
    main()

