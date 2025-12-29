#!/usr/bin/env python3
"""
Phase -1: Directory Catalog 테스트

디렉토리 구조 분석 및 파일명 샘플 수집 테스트
"""

import os
import sys

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.agents.graph import build_phase_neg1_only_agent, build_phase0_only_agent
from src.database.schema_directory import DirectorySchemaManager, get_directory_by_path
from src.database.connection import get_db_manager


def reset_db_transaction():
    """DB 트랜잭션 상태 초기화 (테스트 간 격리)"""
    try:
        db = get_db_manager()
        conn = db.get_connection()
        conn.rollback()  # 이전 트랜잭션 롤백
    except Exception as e:
        print(f"   ⚠️ Transaction reset warning: {e}")


def test_phase_neg1_basic():
    """기본 Phase -1 테스트"""
    print("\n" + "="*80)
    print("🧪 TEST: Phase -1 Basic")
    print("="*80)
    
    # 트랜잭션 초기화
    reset_db_transaction()
    
    # 테스트 디렉토리 설정 (절대 경로 사용)
    test_dir = os.path.join(PROJECT_ROOT, "data/raw/Open_VitalDB_1.0.0")
    
    if not os.path.isdir(test_dir):
        print(f"❌ Test directory not found: {test_dir}")
        print("   Please run this test from the IndexingAgent directory")
        return False
    
    print(f"📂 Test directory: {test_dir}")
    
    # 스키마 먼저 생성
    schema_manager = DirectorySchemaManager()
    schema_manager.create_tables()
    
    # 에이전트 빌드 및 실행
    agent = build_phase_neg1_only_agent()
    
    result = agent.invoke({
        "input_directory": test_dir
    })
    
    # 결과 확인
    phase_neg1_result = result.get("phase_neg1_result", {})
    dir_ids = result.get("phase_neg1_dir_ids", [])
    
    print(f"\n📊 Result:")
    print(f"   Total directories: {phase_neg1_result.get('total_dirs', 0)}")
    print(f"   Processed: {phase_neg1_result.get('processed_dirs', 0)}")
    print(f"   Total files: {phase_neg1_result.get('total_files', 0)}")
    print(f"   Dir IDs: {len(dir_ids)}")
    
    # 검증
    assert phase_neg1_result.get("total_dirs", 0) > 0, "No directories found"
    assert phase_neg1_result.get("processed_dirs", 0) > 0, "No directories processed"
    assert len(dir_ids) > 0, "No dir_ids returned"
    
    print("\n✅ Phase -1 basic test passed!")
    return True


def test_directory_catalog_content():
    """directory_catalog 테이블 내용 확인"""
    print("\n" + "="*80)
    print("🧪 TEST: Directory Catalog Content")
    print("="*80)
    
    # 트랜잭션 초기화
    reset_db_transaction()
    
    # DB 조회
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # 모든 디렉토리 조회
    cursor.execute("""
        SELECT dir_id, dir_name, dir_path, file_count, file_extensions, 
               filename_sample_count, dir_type
        FROM directory_catalog
        ORDER BY file_count DESC
    """)
    
    rows = cursor.fetchall()
    
    print(f"\n📂 Found {len(rows)} directories in catalog:")
    for row in rows:
        dir_id, dir_name, dir_path, file_count, file_extensions, sample_count, dir_type = row
        print(f"\n   [{dir_id[:8]}] {dir_name}")
        print(f"      Path: {dir_path}")
        print(f"      Files: {file_count}")
        print(f"      Extensions: {file_extensions}")
        print(f"      Samples: {sample_count}")
        print(f"      Type: {dir_type}")
    
    # vital_files 디렉토리 상세 확인
    cursor.execute("""
        SELECT filename_samples
        FROM directory_catalog
        WHERE dir_name = 'vital_files'
    """)
    
    row = cursor.fetchone()
    if row and row[0]:
        samples = row[0]
        print(f"\n📋 vital_files filename samples ({len(samples)}):")
        for s in samples[:10]:
            print(f"      - {s}")
        if len(samples) > 10:
            print(f"      ... and {len(samples) - 10} more")
    
    print("\n✅ Directory catalog content test passed!")
    return True


def test_phase0_with_dir_id():
    """Phase -1 + Phase 0 통합 테스트 (dir_id 연결)"""
    print("\n" + "="*80)
    print("🧪 TEST: Phase -1 + Phase 0 Integration")
    print("="*80)
    
    # 트랜잭션 초기화
    reset_db_transaction()
    
    # 테스트 디렉토리 설정 (절대 경로 사용)
    test_dir = os.path.join(PROJECT_ROOT, "data/raw/Open_VitalDB_1.0.0")
    
    if not os.path.isdir(test_dir):
        print(f"❌ Test directory not found: {test_dir}")
        return False
    
    # Phase -1 + Phase 0 에이전트 빌드
    agent = build_phase0_only_agent()
    
    # input_files 생성 (tabular 파일들만)
    input_files = []
    for f in os.listdir(test_dir):
        if f.endswith('.csv'):
            input_files.append(os.path.join(test_dir, f))
    
    print(f"📂 Input files: {len(input_files)}")
    for f in input_files:
        print(f"   - {os.path.basename(f)}")
    
    # 에이전트 실행
    result = agent.invoke({
        "input_directory": test_dir,
        "input_files": input_files
    })
    
    # 결과 확인
    phase_neg1_result = result.get("phase_neg1_result", {})
    phase0_result = result.get("phase0_result", {})
    
    print(f"\n📊 Phase -1 Result:")
    print(f"   Directories: {phase_neg1_result.get('processed_dirs', 0)}")
    
    print(f"\n📊 Phase 0 Result:")
    print(f"   Files: {phase0_result.get('processed_files', 0)}")
    
    # file_catalog에서 dir_id 확인
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT fc.file_name, fc.dir_id, dc.dir_name
        FROM file_catalog fc
        LEFT JOIN directory_catalog dc ON fc.dir_id = dc.dir_id
        LIMIT 10
    """)
    
    rows = cursor.fetchall()
    print(f"\n📋 file_catalog with dir_id:")
    for row in rows:
        file_name, dir_id, dir_name = row
        dir_id_str = dir_id[:8] if dir_id else "NULL"
        print(f"   - {file_name} → [{dir_id_str}] {dir_name or 'N/A'}")
    
    print("\n✅ Phase -1 + Phase 0 integration test passed!")
    return True


def test_stats():
    """통계 조회 테스트"""
    print("\n" + "="*80)
    print("🧪 TEST: Directory Catalog Stats")
    print("="*80)
    
    # 트랜잭션 초기화
    reset_db_transaction()
    
    schema_manager = DirectorySchemaManager()
    stats = schema_manager.get_stats()
    
    print(f"\n📊 Stats:")
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    print("\n✅ Stats test passed!")
    return True


def main():
    """메인 테스트 실행"""
    print("\n" + "="*80)
    print("🚀 Phase -1: Directory Catalog Tests")
    print("="*80)
    
    tests = [
        ("Phase -1 Basic", test_phase_neg1_basic),
        ("Directory Catalog Content", test_directory_catalog_content),
        ("Phase -1 + Phase 0 Integration", test_phase0_with_dir_id),
        ("Stats", test_stats),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n❌ {name} failed with exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*80)
    print(f"📊 Test Summary: {passed} passed, {failed} failed")
    print("="*80)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

