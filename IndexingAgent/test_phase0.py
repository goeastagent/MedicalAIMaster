#!/usr/bin/env python
"""
Phase 0 테스트 스크립트 (LangGraph 기반)

Data Catalog 스키마 생성 및 파일 메타데이터 추출/저장 테스트
LangGraph 워크플로우를 사용하여 phase0_catalog 노드만 실행
"""

import sys
import os
import glob
from pathlib import Path

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from agents.state import AgentState
from agents.nodes.catalog import phase0_catalog_node, get_catalog_stats
from database.schema_catalog import CatalogSchemaManager, init_catalog_schema


def build_phase0_only_agent(checkpointer=None):
    """
    Phase 0만 실행하는 LangGraph 워크플로우 빌드
    
    Graph:
        START → phase0_catalog → END
    
    Returns:
        컴파일된 LangGraph 워크플로우
    """
    workflow = StateGraph(AgentState)
    
    # Phase 0 노드만 추가
    workflow.add_node("phase0_catalog", phase0_catalog_node)
    
    # Entry Point & Exit
    workflow.set_entry_point("phase0_catalog")
    workflow.add_edge("phase0_catalog", END)
    
    # Compile
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
    
    return workflow.compile(**compile_config)


def get_input_files():
    """
    test_agent_with_interrupt.py와 동일한 파일 목록 반환
    
    Returns:
        tuple: (all_files, vital_csv_files, vital_signal_files, inspire_files)
    """
    data_dir = Path(__file__).parent / "data" / "raw"
    
    # CSV 파일
    inspire_files = sorted(glob.glob(str(data_dir / "INSPIRE_130K_1.3/*.csv")))
    vital_csv_files = sorted(glob.glob(str(data_dir / "Open_VitalDB_1.0.0/*.csv")))
    vital_signal_files = sorted(glob.glob(str(data_dir / "Open_VitalDB_1.0.0/vital_files/*.vital")))
    
    # VitalDB 데이터만 처리 (CSV + Signal 처음 2개)
    all_files = vital_csv_files + vital_signal_files[:2]
    
    return all_files, vital_csv_files, vital_signal_files, inspire_files


def test_schema_creation():
    """스키마 생성 테스트"""
    print("=" * 60)
    print("1. Testing Schema Creation")
    print("=" * 60)
    
    schema_manager = init_catalog_schema(reset=True)
    
    # 테이블 존재 확인
    assert schema_manager.table_exists('file_catalog'), "file_catalog table not created"
    assert schema_manager.table_exists('column_metadata'), "column_metadata table not created"
    
    print("✓ Tables created successfully")
    print()


def test_show_table_schema():
    """DB 테이블 스키마 전체 출력"""
    print("=" * 60)
    print("2. Database Table Schema")
    print("=" * 60)
    
    from database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    tables = ['file_catalog', 'column_metadata']
    
    for table_name in tables:
        print(f"\n📋 Table: {table_name}")
        print("-" * 50)
        
        # 컬럼 정보 조회
        cursor.execute("""
            SELECT 
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        
        columns = cursor.fetchall()
        
        # 헤더
        print(f"{'Column':<25} {'Type':<20} {'Nullable':<10} {'Default'}")
        print("-" * 80)
        
        for col in columns:
            col_name = col[0]
            data_type = col[1]
            max_len = col[2]
            nullable = col[3]
            default = col[4]
            
            # 타입 포맷팅
            if max_len:
                type_str = f"{data_type}({max_len})"
            else:
                type_str = data_type
            
            # Default 값 간소화
            if default:
                if 'nextval' in str(default):
                    default_str = 'SERIAL'
                elif len(str(default)) > 20:
                    default_str = str(default)[:17] + "..."
                else:
                    default_str = str(default)
            else:
                default_str = ""
            
            print(f"{col_name:<25} {type_str:<20} {nullable:<10} {default_str}")
        
        # 인덱스 조회
        cursor.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = %s
        """, (table_name,))
        
        indexes = cursor.fetchall()
        if indexes:
            print(f"\n  Indexes:")
            for idx in indexes:
                print(f"    - {idx[0]}")
    
    print()


def test_phase0_workflow(all_files: list):
    """
    LangGraph를 사용한 Phase 0 워크플로우 테스트
    """
    print("=" * 60)
    print("3. Running Phase 0 via LangGraph Workflow")
    print("=" * 60)
    
    print(f"\n📁 Input Files: {len(all_files)}개")
    for f in all_files:
        print(f"   - {os.path.basename(f)}")
    print()
    
    # LangGraph 워크플로우 빌드
    memory = MemorySaver()
    agent = build_phase0_only_agent(checkpointer=memory)
    
    # 초기 상태 설정
    initial_state = {
        # Phase 0 필수 필드
        "input_files": all_files,
        "phase0_result": None,
        "phase0_file_ids": [],
        
        # 기타 필드 (AgentState 호환)
        "current_dataset_id": "test_dataset",
        "current_table_name": None,
        "data_catalog": {},
        "classification_result": None,
        "processing_progress": {
            "phase": "phase0",
            "metadata_processed": [],
            "data_processed": [],
            "current_file": None,
            "current_file_index": 0,
            "total_files": len(all_files)
        },
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
        "project_context": {}
    }
    
    # Thread 설정
    thread_config = {"configurable": {"thread_id": "phase0-test-1"}}
    
    print("▶️  LangGraph Phase 0 워크플로우 실행 중...\n")
    
    # 워크플로우 실행
    final_state = None
    for event in agent.stream(initial_state, thread_config, stream_mode="values"):
        # 로그 출력
        if "logs" in event and event["logs"]:
            for log in event["logs"]:
                if not final_state or log not in final_state.get("logs", []):
                    print(f"📝 {log}")
        final_state = event
    
    # 결과 출력
    phase0_result = final_state.get("phase0_result", {}) if final_state else {}
    file_ids = final_state.get("phase0_file_ids", []) if final_state else []
    
    print()
    print(f"📊 Phase 0 Result (via LangGraph):")
    print(f"   Total: {phase0_result.get('total_files', 0)}")
    print(f"   Processed: {phase0_result.get('processed_files', 0)}")
    print(f"   Skipped: {phase0_result.get('skipped_files', 0)}")
    print(f"   Failed: {phase0_result.get('failed_files', 0)}")
    print(f"   Success Rate: {phase0_result.get('success_rate', 'N/A')}")
    
    # File IDs (state에 저장된 값)
    if file_ids:
        print(f"\n📋 File IDs in State ({len(file_ids)}개):")
        for fid in file_ids:
            print(f"   - {fid}")
    
    # 실패한 파일 상세
    results = phase0_result.get('results', [])
    failed = [r for r in results if not r.get('success', False)]
    if failed:
        print(f"\n❌ Failed Files:")
        for r in failed:
            print(f"   - {os.path.basename(r.get('file_path', 'unknown'))}: {r.get('error', 'unknown')}")
    
    print()
    return phase0_result


def test_catalog_stats():
    """카탈로그 통계 조회 테스트"""
    print("=" * 60)
    print("4. Catalog Statistics")
    print("=" * 60)
    
    stats = get_catalog_stats()
    
    print(f"Total Files: {stats.get('total_files', 0)}")
    print(f"Files by Type: {stats.get('files_by_type', {})}")
    print(f"Total Columns: {stats.get('total_columns', 0)}")
    print(f"Columns by Type: {stats.get('columns_by_type', {})}")
    print()


def test_query_catalog():
    """카탈로그 전체 데이터 출력"""
    print("=" * 60)
    print("5. Full Catalog Data")
    print("=" * 60)
    
    from database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # =========================================================================
    # file_catalog 전체 출력 (모든 컬럼)
    # =========================================================================
    cursor.execute("""
        SELECT 
            file_id,
            file_path,
            file_name,
            file_extension,
            file_size_bytes,
            file_size_mb,
            file_modified_at,
            processor_type,
            is_text_readable,
            semantic_type,
            file_metadata,
            LENGTH(raw_stats::text) as raw_stats_size,
            created_at
        FROM file_catalog
        ORDER BY file_id
    """)
    
    files = cursor.fetchall()
    print(f"\n📂 file_catalog ({len(files)} rows) - ALL COLUMNS:")
    print("=" * 140)
    
    for row in files:
        (file_id, file_path, file_name, file_extension, file_size_bytes, file_size_mb,
         file_modified_at, processor_type, is_text_readable, semantic_type, file_metadata, 
         raw_stats_size, created_at) = row
        
        short_id = str(file_id)[:8]  # UUID 앞 8자리
        print(f"\n┌─ [{short_id}] {file_name}")
        print(f"│  file_path:        {file_path}")
        print(f"│  file_extension:   {file_extension}")
        print(f"│  file_size_bytes:  {file_size_bytes:,}")
        print(f"│  file_size_mb:     {file_size_mb}")
        print(f"│  file_modified_at: {file_modified_at}")
        print(f"│  processor_type:   {processor_type}")
        print(f"│  is_text_readable: {is_text_readable}")
        print(f"│  semantic_type:    {semantic_type or '(null)'}")
        print(f"│  created_at:       {created_at}")
        print(f"│  raw_stats_size:   {raw_stats_size:,} bytes")
        print(f"│  file_metadata:")
        if file_metadata:
            import json
            for key, value in file_metadata.items():
                # 긴 리스트는 축약
                if isinstance(value, list) and len(value) > 5:
                    value_str = f"[{', '.join(map(str, value[:3]))} ... ({len(value)} items)]"
                elif isinstance(value, dict) and len(value) > 3:
                    value_str = f"{{...}} ({len(value)} keys)"
                else:
                    value_str = str(value)
                print(f"│      {key}: {value_str}")
        print(f"└{'─' * 80}")
    print()
    
    # =========================================================================
    # column_metadata 전체 출력 (파일별로 그룹화)
    # =========================================================================
    cursor.execute("""
        SELECT fc.file_id, fc.file_name, cm.col_id, cm.original_name, cm.column_type, 
               cm.data_type, cm.column_info->>'null_ratio' as null_ratio,
               cm.column_info->>'unit' as unit,
               cm.column_info->>'sample_rate' as sample_rate
        FROM column_metadata cm
        JOIN file_catalog fc ON cm.file_id = fc.file_id
        ORDER BY fc.file_id, cm.col_id
    """)
    
    columns = cursor.fetchall()
    print(f"📊 column_metadata ({len(columns)} rows):")
    print("=" * 120)
    
    current_file = None
    for row in columns:
        file_id, file_name, col_id, col_name, col_type, dtype, null_ratio, unit, sample_rate = row
        
        # 파일이 바뀌면 헤더 출력
        if current_file != file_id:
            if current_file is not None:
                print()  # 이전 파일과 구분
            print(f"\n📁 [{file_id}] {file_name}")
            print("-" * 100)
            print(f"  {'ID':<4} {'Column Name':<30} {'Type':<15} {'Dtype':<15} {'Null%':<8} {'Unit':<10} {'SRate'}")
            print("  " + "-" * 95)
            current_file = file_id
        
        # 컬럼 정보 출력
        null_str = f"{float(null_ratio):.1%}" if null_ratio else "-"
        unit_str = unit if unit else "-"
        srate_str = sample_rate if sample_rate else "-"
        print(f"  {col_id:<4} {col_name:<30} {col_type:<15} {dtype:<15} {null_str:<8} {unit_str:<10} {srate_str}")
    
    print()


def main():
    """메인 테스트 실행"""
    print("\n" + "=" * 60)
    print("Phase 0 Data Catalog Test (LangGraph 기반)")
    print("(Using same input files as test_agent_with_interrupt.py)")
    print("=" * 60 + "\n")
    
    # 입력 파일 로드 (test_agent_with_interrupt.py와 동일)
    all_files, vital_csv_files, vital_signal_files, inspire_files = get_input_files()
    
    print(f"📁 Found files:")
    print(f"   📊 VitalDB CSV: {len(vital_csv_files)}개")
    print(f"   📈 VitalDB Signal: {len(vital_signal_files)}개 (using first 2)")
    print(f"   📋 INSPIRE CSV: {len(inspire_files)}개 (not used)")
    print(f"   ➡️  Total to process: {len(all_files)}개")
    print()
    
    if not all_files:
        print(f"❌ 파일을 찾을 수 없습니다")
        return 1
    
    try:
        # 1. 스키마 생성
        test_schema_creation()
        
        # 2. 스키마 확인
        test_show_table_schema()
        
        # 3. LangGraph 워크플로우로 Phase 0 실행
        test_phase0_workflow(all_files)
        
        # 4. 통계 조회
        test_catalog_stats()
        
        # 5. 전체 데이터 출력
        test_query_catalog()
        
        print("=" * 60)
        print("✅ All tests completed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
