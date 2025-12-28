#!/usr/bin/env python
"""
Phase 1A 테스트: MetaData Semantic Analysis

metadata 파일에서 key-desc-unit을 추출하여 data_dictionary에 저장하는 기능을 테스트합니다.

Usage:
    python test_phase1a.py [--reset]

Options:
    --reset: DB 테이블 초기화 후 실행
"""

import os
import sys

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agents.graph import build_phase1a_agent
from src.database.schema_catalog import init_catalog_schema
from src.database.schema_dictionary import init_dictionary_schema, DictionarySchemaManager


def get_test_files():
    """테스트용 파일 목록 반환 (Open_VitalDB만 사용)"""
    base_path = os.path.join(os.path.dirname(__file__), "data/raw/Open_VitalDB_1.0.0")
    
    files = [
        os.path.join(base_path, "clinical_parameters.csv"),
        os.path.join(base_path, "clinical_data.csv"),
        os.path.join(base_path, "lab_parameters.csv"),
        os.path.join(base_path, "lab_data.csv"),
        os.path.join(base_path, "track_names.csv"),
    ]
    
    # 존재하는 파일만 필터링
    existing_files = [f for f in files if os.path.exists(f)]
    
    if not existing_files:
        print("❌ No Open_VitalDB test files found!")
        print(f"   Expected path: {base_path}")
    
    return existing_files


def print_file_catalog_table():
    """file_catalog 테이블 출력"""
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("\n" + "=" * 100)
    print("📁 FILE_CATALOG TABLE")
    print("=" * 100)
    
    cursor.execute("""
        SELECT file_name, processor_type, is_metadata, llm_confidence, 
               file_metadata->>'row_count' as row_count,
               file_metadata->>'column_count' as col_count
        FROM file_catalog
        ORDER BY is_metadata DESC, file_name
    """)
    
    rows = cursor.fetchall()
    if not rows:
        print("   (No entries found)")
        return
    
    print(f"{'File Name':<35} {'Type':<10} {'Is Meta':<10} {'Rows':<10} {'Cols':<8} {'Conf':<6}")
    print("-" * 100)
    
    for row in rows:
        file_name, proc_type, is_meta, conf, row_count, col_count = row
        meta_str = "✅ YES" if is_meta else "❌ NO"
        conf_str = f"{conf:.2f}" if conf else "-"
        row_str = str(row_count) if row_count else "-"
        col_str = str(col_count) if col_count else "-"
        
        print(f"{file_name:<35} {proc_type or '-':<10} {meta_str:<10} {row_str:<10} {col_str:<8} {conf_str:<6}")
    
    print("-" * 100)
    print(f"Total files: {len(rows)}")


def print_column_metadata_table():
    """column_metadata 테이블 출력 (파일별 그룹핑)"""
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("\n" + "=" * 100)
    print("📋 COLUMN_METADATA TABLE")
    print("=" * 100)
    
    # 파일별로 그룹핑
    cursor.execute("""
        SELECT fc.file_name, cm.original_name, cm.column_type, cm.data_type, 
               cm.semantic_name, cm.unit, cm.column_info
        FROM column_metadata cm
        JOIN file_catalog fc ON cm.file_id = fc.file_id
        ORDER BY fc.file_name, cm.col_id
    """)
    
    rows = cursor.fetchall()
    if not rows:
        print("   (No entries found)")
        return
    
    # 파일별로 그룹핑하여 출력
    current_file = None
    file_count = 0
    
    for row in rows:
        file_name, original_name, col_type, data_type, semantic_name, unit, column_info = row
        
        if file_name != current_file:
            if current_file is not None:
                print()
            current_file = file_name
            file_count = 0
            print(f"\n📄 {file_name}")
            print("-" * 95)
            print(f"  {'Column':<20} {'Col Type':<12} {'Data Type':<10} {'Semantic':<15} {'Unit':<10}")
            print("  " + "-" * 93)
        
        file_count += 1
        col_str = original_name[:19] if original_name else "-"
        col_type_str = col_type[:11] if col_type else "-"
        dtype_str = data_type[:9] if data_type else "-"
        sem_str = (semantic_name[:14] if semantic_name else "-")
        unit_str = (unit[:9] if unit else "-")
        
        print(f"  {col_str:<20} {col_type_str:<12} {dtype_str:<10} {sem_str:<15} {unit_str:<10}")
    
    # 전체 컬럼 수
    cursor.execute("SELECT COUNT(*) FROM column_metadata")
    total = cursor.fetchone()[0]
    print("\n" + "-" * 100)
    print(f"Total columns: {total}")


def print_data_dictionary_table():
    """data_dictionary 테이블 전체 출력 (파일별로 그룹핑)"""
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("\n" + "=" * 100)
    print("📖 DATA_DICTIONARY TABLE")
    print("=" * 100)
    
    # 파일별로 그룹핑하여 조회
    cursor.execute("""
        SELECT DISTINCT source_file_name FROM data_dictionary ORDER BY source_file_name
    """)
    files = [row[0] for row in cursor.fetchall()]
    
    if not files:
        print("   (No entries found)")
        return
    
    total_entries = 0
    
    for file_name in files:
        cursor.execute("""
            SELECT parameter_key, parameter_desc, parameter_unit, extra_info, llm_confidence
            FROM data_dictionary
            WHERE source_file_name = %s
            ORDER BY parameter_key
        """, (file_name,))
        
        rows = cursor.fetchall()
        total_entries += len(rows)
        
        print(f"\n📄 {file_name} ({len(rows)} entries)")
        print("-" * 95)
        print(f"  {'Key':<20} {'Description':<35} {'Unit':<15} {'Extra Info':<20}")
        print("  " + "-" * 93)
        
        for row in rows:
            key, desc, unit, extra_info, conf = row
            key_str = (key[:19] if key else "-")
            desc_str = (desc[:34] if desc else "-")
            unit_str = (unit[:14] if unit else "-")
            
            # extra_info는 dict로 저장됨
            extra_str = ""
            if extra_info and isinstance(extra_info, dict):
                extra_parts = [f"{k}={v}" for k, v in list(extra_info.items())[:2]]
                extra_str = ", ".join(extra_parts)[:19]
            
            print(f"  {key_str:<20} {desc_str:<35} {unit_str:<15} {extra_str:<20}")
    
    print("\n" + "-" * 100)
    print(f"Total entries across all files: {total_entries}")


def print_dictionary_sample():
    """data_dictionary 테이블의 샘플 데이터 출력 (간략 버전)"""
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("\n📖 Data Dictionary Sample (first 10 entries):")
    print("-" * 80)
    
    cursor.execute("""
        SELECT source_file_name, parameter_key, parameter_desc, parameter_unit, llm_confidence
        FROM data_dictionary
        ORDER BY source_file_name, parameter_key
        LIMIT 10
    """)
    
    rows = cursor.fetchall()
    if not rows:
        print("   (No entries found)")
        return
    
    print(f"{'File':<25} {'Key':<15} {'Description':<25} {'Unit':<10} {'Conf':<5}")
    print("-" * 80)
    
    for row in rows:
        file_name, key, desc, unit, conf = row
        file_short = file_name[:24] if file_name else "?"
        key_short = key[:14] if key else "?"
        desc_short = (desc[:24] if desc else "")
        unit_short = (unit[:9] if unit else "")
        conf_str = f"{conf:.2f}" if conf else "?"
        
        print(f"{file_short:<25} {key_short:<15} {desc_short:<25} {unit_short:<10} {conf_str:<5}")
    
    # 전체 개수
    cursor.execute("SELECT COUNT(*) FROM data_dictionary")
    total = cursor.fetchone()[0]
    print("-" * 80)
    print(f"Total entries: {total}")


def main(reset: bool = False):
    """Phase 1A 테스트 실행"""
    print("=" * 70)
    print("🧪 Phase 1A Test: MetaData Semantic Analysis")
    print("=" * 70)
    
    # 1. DB 스키마 초기화
    print("\n📦 Initializing database schema...")
    init_catalog_schema(reset=reset)
    init_dictionary_schema(reset=reset)
    
    # 2. 테스트 파일 확인
    test_files = get_test_files()
    if not test_files:
        print("❌ No test files found!")
        return
    
    print(f"\n📂 Test files ({len(test_files)}):")
    for f in test_files:
        print(f"   - {os.path.basename(f)}")
    
    # 3. 워크플로우 빌드 및 실행
    print("\n🚀 Building Phase 1A workflow...")
    agent = build_phase1a_agent()
    
    # 초기 상태
    initial_state = {
        "current_dataset_id": "test_dataset",
        "input_files": test_files,
        "data_catalog": {},
        "logs": [],
        # Phase 0 결과 (빈 상태로 시작)
        "phase0_result": None,
        "phase0_file_ids": [],
        # Phase 0.5 결과
        "phase05_result": None,
        "unique_columns": [],
        "unique_files": [],
        "column_batches": [],
        "file_batches": [],
        # Phase 0.7 결과
        "phase07_result": None,
        "metadata_files": [],
        "data_files": [],
        # Phase 1A 결과
        "phase1a_result": None,
        "data_dictionary_entries": [],
    }
    
    print("\n🔄 Running workflow (Phase 0 → 0.5 → 0.7 → 1A)...")
    print("-" * 70)
    
    # 워크플로우 실행
    result = agent.invoke(initial_state)
    
    print("-" * 70)
    
    # 4. 결과 출력
    print("\n📊 Results:")
    
    # Phase 0.7 결과
    phase07_result = result.get("phase07_result", {})
    metadata_files = result.get("metadata_files", [])
    data_files = result.get("data_files", [])
    
    print(f"\n   🏷️  Phase 0.7 Classification:")
    print(f"      Metadata files: {len(metadata_files)}")
    print(f"      Data files: {len(data_files)}")
    
    # Phase 1A 결과
    phase1a_result = result.get("phase1a_result", {})
    entries = result.get("data_dictionary_entries", [])
    
    print(f"\n   📖 Phase 1A MetaData Semantic:")
    print(f"      Processed files: {phase1a_result.get('processed_files', 0)}")
    print(f"      Total entries extracted: {phase1a_result.get('total_entries_extracted', 0)}")
    print(f"      LLM calls: {phase1a_result.get('llm_calls', 0)}")
    
    if phase1a_result.get('entries_by_file'):
        print(f"\n      Entries by file:")
        for fname, count in phase1a_result.get('entries_by_file', {}).items():
            print(f"         - {fname}: {count} entries")
    
    # 5. 로그 출력
    print("\n📜 Logs:")
    for log in result.get("logs", []):
        print(f"   {log}")
    
    # 6. DB 테이블 출력
    print("\n" + "=" * 100)
    print("💾 DATABASE TABLES")
    print("=" * 100)
    
    # file_catalog 테이블 출력
    print_file_catalog_table()
    
    # column_metadata 테이블 출력
    print_column_metadata_table()
    
    # data_dictionary 테이블 전체 출력
    print_data_dictionary_table()
    
    # 7. 최종 통계
    schema_manager = DictionarySchemaManager()
    stats = schema_manager.get_stats()
    print("\n" + "=" * 100)
    print("📊 FINAL STATISTICS")
    print("=" * 100)
    print(f"   Total dictionary entries: {stats.get('total_entries', 0)}")
    print(f"   Entries with unit: {stats.get('entries_with_unit', 0)}")
    if stats.get('entries_by_file'):
        print(f"   Entries by file:")
        for fname, count in stats.get('entries_by_file', {}).items():
            print(f"      - {fname}: {count}")
    
    print("\n" + "=" * 100)
    print("✅ Phase 1A Test Complete!")
    print("=" * 100)
    
    return result


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    main(reset=reset)

