#!/usr/bin/env python
"""
Phase 1B 테스트: Data Semantic Analysis

데이터 파일의 컬럼을 의미론적으로 분석하고 data_dictionary와 연결하는 기능을 테스트합니다.

Workflow:
  Phase 0 → Phase 0.5 → Phase 0.7 → Phase 1A → Phase 1B

Usage:
    python test_phase1b.py [--reset]

Options:
    --reset: DB 테이블 초기화 후 실행
"""

import os
import sys

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agents.graph import build_phase1b_agent
from src.database.schema_catalog import init_catalog_schema
from src.database.schema_dictionary import init_dictionary_schema


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


def print_file_catalog_table(limit=20):
    """file_catalog 테이블 내용 출력"""
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("\n" + "=" * 120)
    print("📁 FILE_CATALOG TABLE")
    print("=" * 120)
    
    cursor.execute(f"""
        SELECT file_id, file_name, processor_type, is_metadata, 
               file_metadata->>'row_count' as row_count,
               file_metadata->>'column_count' as col_count,
               llm_confidence, semantic_type
        FROM file_catalog
        ORDER BY is_metadata DESC, file_name
        LIMIT {limit}
    """)
    
    rows = cursor.fetchall()
    
    # 전체 개수
    cursor.execute("SELECT COUNT(*) FROM file_catalog")
    total = cursor.fetchone()[0]
    
    print(f"\n{'File ID':<10} {'File Name':<30} {'Type':<10} {'Meta':<6} {'Rows':<10} {'Cols':<6} {'Conf':<6} {'Semantic Type':<20}")
    print("-" * 120)
    
    for row in rows:
        file_id, name, proc_type, is_meta, row_count, col_count, conf, sem_type = row
        id_str = str(file_id)[:8] if file_id else "-"
        name_str = (name[:29] if name else "-")
        proc_str = proc_type or "-"
        meta_str = "✅" if is_meta else "❌"
        row_str = str(row_count) if row_count else "-"
        col_str = str(col_count) if col_count else "-"
        conf_str = f"{conf:.2f}" if conf else "-"
        sem_str = (sem_type[:19] if sem_type else "-")
        
        print(f"{id_str:<10} {name_str:<30} {proc_str:<10} {meta_str:<6} {row_str:<10} {col_str:<6} {conf_str:<6} {sem_str:<20}")
    
    print("-" * 120)
    print(f"Showing {len(rows)}/{total} rows")


def print_data_dictionary_table(limit=20):
    """data_dictionary 테이블 내용 출력"""
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("\n" + "=" * 130)
    print("📖 DATA_DICTIONARY TABLE")
    print("=" * 130)
    
    cursor.execute(f"""
        SELECT dict_id, source_file_name, parameter_key, parameter_desc, parameter_unit, llm_confidence
        FROM data_dictionary
        ORDER BY source_file_name, parameter_key
        LIMIT {limit}
    """)
    
    rows = cursor.fetchall()
    
    # 전체 개수
    cursor.execute("SELECT COUNT(*) FROM data_dictionary")
    total = cursor.fetchone()[0]
    
    # 파일별 통계
    cursor.execute("""
        SELECT source_file_name, COUNT(*) as cnt
        FROM data_dictionary
        GROUP BY source_file_name
        ORDER BY source_file_name
    """)
    file_stats = cursor.fetchall()
    
    print(f"\n📊 Summary: {total} entries from {len(file_stats)} files")
    for fname, cnt in file_stats:
        print(f"   - {fname}: {cnt} entries")
    
    print(f"\n{'Dict ID':<10} {'Source File':<25} {'Key':<20} {'Description':<40} {'Unit':<10} {'Conf':<6}")
    print("-" * 130)
    
    for row in rows:
        dict_id, src_file, key, desc, unit, conf = row
        id_str = str(dict_id)[:8] if dict_id else "-"
        src_str = (src_file[:24] if src_file else "-")
        key_str = (key[:19] if key else "-")
        desc_str = (desc[:39] if desc else "-")
        unit_str = (unit[:9] if unit else "-")
        conf_str = f"{conf:.2f}" if conf else "-"
        
        print(f"{id_str:<10} {src_str:<25} {key_str:<20} {desc_str:<40} {unit_str:<10} {conf_str:<6}")
    
    print("-" * 130)
    print(f"Showing {len(rows)}/{total} rows")


def print_column_metadata_table(per_file=5):
    """column_metadata 테이블 내용 출력 (Phase 1B 결과 포함, 파일별로 N개씩)"""
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("\n" + "=" * 140)
    print("📋 COLUMN_METADATA TABLE (with Phase 1B results)")
    print("=" * 140)
    
    # 전체 통계
    cursor.execute("SELECT COUNT(*) FROM column_metadata")
    total = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT dict_match_status, COUNT(*) 
        FROM column_metadata 
        WHERE dict_match_status IS NOT NULL
        GROUP BY dict_match_status
    """)
    status_stats = dict(cursor.fetchall())
    
    print(f"\n📊 Summary: {total} columns")
    print(f"   Phase 1B analyzed: {sum(status_stats.values())}")
    print(f"   ✅ Matched: {status_stats.get('matched', 0)}")
    print(f"   ⚠️ Not found: {status_stats.get('not_found', 0)}")
    print(f"   ➖ Null from LLM: {status_stats.get('null_from_llm', 0)}")
    
    # 데이터 파일 목록 조회
    cursor.execute("""
        SELECT DISTINCT fc.file_name, COUNT(*) as col_count
        FROM column_metadata cm
        JOIN file_catalog fc ON cm.file_id = fc.file_id
        WHERE fc.is_metadata = false
        GROUP BY fc.file_name
        ORDER BY fc.file_name
    """)
    data_files = cursor.fetchall()
    
    shown_count = 0
    
    for file_name, col_count in data_files:
        # 파일별 컬럼 조회 (per_file 개씩)
        cursor.execute(f"""
            SELECT cm.original_name, cm.column_type, cm.semantic_name, 
                   cm.unit, cm.concept_category, cm.dict_match_status, dd.parameter_key
            FROM column_metadata cm
            JOIN file_catalog fc ON cm.file_id = fc.file_id
            LEFT JOIN data_dictionary dd ON cm.dict_entry_id = dd.dict_id
            WHERE fc.file_name = %s AND fc.is_metadata = false
            ORDER BY cm.col_id
            LIMIT {per_file}
        """, (file_name,))
        
        rows = cursor.fetchall()
        
        print(f"\n📄 {file_name} ({col_count} columns, showing {len(rows)})")
        print("-" * 130)
        print(f"  {'Original':<18} {'Type':<12} {'Semantic':<20} {'Unit':<10} {'Concept':<15} {'Status':<12} {'Dict Key':<15}")
        print("  " + "-" * 128)
        
        for row in rows:
            original, col_type, semantic, unit, concept, status, dict_key = row
            orig_str = (original[:17] if original else "-")
            type_str = (col_type[:11] if col_type else "-")
            sem_str = (semantic[:19] if semantic else "-")
            unit_str = (unit[:9] if unit else "-")
            concept_str = (concept[:14] if concept else "-")
            dict_str = (dict_key[:14] if dict_key else "-")
            
            # 상태별 아이콘
            if status == 'matched':
                status_str = "✅matched"
            elif status == 'not_found':
                status_str = "⚠️not_found"
            elif status == 'null_from_llm':
                status_str = "➖null"
            else:
                status_str = "-"
            
            print(f"  {orig_str:<18} {type_str:<12} {sem_str:<20} {unit_str:<10} {concept_str:<15} {status_str:<12} {dict_str:<15}")
        
        shown_count += len(rows)
        
        if col_count > per_file:
            print(f"  ... and {col_count - per_file} more columns")
    
    # 데이터 파일 컬럼 수 조회
    cursor.execute("""
        SELECT COUNT(*) FROM column_metadata cm
        JOIN file_catalog fc ON cm.file_id = fc.file_id
        WHERE fc.is_metadata = false
    """)
    data_cols = cursor.fetchone()[0]
    
    print("\n" + "=" * 140)
    print(f"📊 Total: {len(data_files)} data files, {data_cols} columns (showing {per_file} per file)")


def print_phase1b_result(result):
    """Phase 1B 결과 출력"""
    if not result:
        print("\n⚠️ No Phase 1B result")
        return
    
    print("\n" + "=" * 80)
    print("📋 PHASE 1B RESULT SUMMARY")
    print("=" * 80)
    
    print(f"   Data files processed: {result.get('processed_files', 0)}")
    print(f"   Total columns: {result.get('total_columns_analyzed', 0)}")
    print(f"   Dictionary matches: {result.get('columns_matched', 0)}")
    print(f"   Not found in dict: {result.get('columns_not_found', 0)}")
    print(f"   Null from LLM: {result.get('columns_null_from_llm', 0)}")
    print(f"   LLM calls: {result.get('llm_calls', 0)}")
    print(f"   Batches: {result.get('batches_processed', 0)}")
    
    if result.get('columns_by_file'):
        print(f"\n   Columns by file:")
        for fname, cnt in result['columns_by_file'].items():
            print(f"      - {fname}: {cnt}")


def drop_all_tables():
    """모든 테이블 삭제"""
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DROP TABLE IF EXISTS data_dictionary CASCADE")
        cursor.execute("DROP TABLE IF EXISTS column_metadata CASCADE")
        cursor.execute("DROP TABLE IF EXISTS file_catalog CASCADE")
        conn.commit()
        print("🗑️ All tables dropped")
    except Exception as e:
        conn.rollback()
        print(f"❌ Error dropping tables: {e}")


def main():
    """메인 테스트 실행"""
    print("=" * 80)
    print("🧪 Phase 1B Test: Data Semantic Analysis")
    print("=" * 80)
    
    # --reset 옵션 처리
    if "--reset" in sys.argv:
        print("\n🔄 Resetting database...")
        drop_all_tables()
    
    # 스키마 초기화
    print("\n📐 Initializing schemas...")
    init_catalog_schema()
    init_dictionary_schema()
    
    # 테스트 파일 목록
    test_files = get_test_files()
    if not test_files:
        return
    
    print(f"\n📁 Test files: {len(test_files)}")
    for f in test_files:
        print(f"   - {os.path.basename(f)}")
    
    # 초기 상태
    dataset_id = "open_vitaldb_v1.0.0"
    initial_state = {
        "current_dataset_id": dataset_id,
        "current_table_name": None,
        "data_catalog": {},
        "phase0_result": None,
        "phase0_file_ids": [],
        "phase05_result": None,
        "unique_columns": [],
        "unique_files": [],
        "column_batches": [],
        "file_batches": [],
        "phase07_result": None,
        "metadata_files": [],
        "data_files": [],
        "phase1a_result": None,
        "data_dictionary_entries": [],
        "phase1b_result": None,
        "data_semantic_entries": [],
        "phase1_result": None,
        "column_semantic_mappings": [],
        "file_semantic_mappings": [],
        "phase1_review_queue": None,
        "phase1_current_batch": None,
        "phase1_human_feedback": None,
        "phase1_all_batch_states": [],
        "input_files": test_files,
        "classification_result": None,
        "processing_progress": {},
        "file_path": "",
        "file_type": None,
        "raw_metadata": {},
        "entity_identification": None,
        "finalized_schema": [],
        "entity_understanding": None,
        "needs_human_review": False,
        "human_question": "",
        "human_feedback": None,
        "review_type": None,
        "conversation_history": {},
        "logs": [],
        "ontology_context": {},
        "skip_indexing": False,
        "retry_count": 0,
        "error_message": None,
        "project_context": {},
    }
    
    # 에이전트 빌드 및 실행
    print("\n🚀 Building Phase 1B agent...")
    agent = build_phase1b_agent()
    
    print("\n▶️ Running Phase 0 → 0.5 → 0.7 → 1A → 1B pipeline...")
    print("   This may take a while due to LLM calls...\n")
    
    try:
        result = agent.invoke(initial_state)
        
        # 결과 출력: Phase 1B 결과 테이블 (파일별 5개씩)
        print_column_metadata_table(per_file=5)
        print_phase1b_result(result.get('phase1b_result'))
        
        print("\n" + "=" * 80)
        print("✅ Phase 1B Test Complete!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error during execution: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

