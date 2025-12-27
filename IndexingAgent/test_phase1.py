#!/usr/bin/env python
"""
Phase 0 + 0.5 + 1 테스트 스크립트 (LangGraph 기반)

Phase 0: Data Catalog (파일 스캔 → DB 저장)
Phase 0.5: Schema Aggregation (유니크 컬럼/파일 집계 → LLM 배치 준비)
Phase 1: Semantic Analysis (LLM으로 컬럼/파일 의미 분석 → DB 업데이트)
"""

import sys
import os
import glob
from pathlib import Path

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from langgraph.checkpoint.memory import MemorySaver

from agents.graph import build_phase1_only_agent
from database.schema_catalog import init_catalog_schema
from config import Phase1Config, Phase05Config


def get_input_files():
    """
    test_agent_with_interrupt.py와 동일한 파일 목록 반환
    """
    data_dir = Path(__file__).parent / "data" / "raw"
    
    # CSV 파일
    vital_csv_files = sorted(glob.glob(str(data_dir / "Open_VitalDB_1.0.0/*.csv")))
    vital_signal_files = sorted(glob.glob(str(data_dir / "Open_VitalDB_1.0.0/vital_files/*.vital")))
    
    # VitalDB 데이터만 처리 (CSV + Signal 처음 2개)
    all_files = vital_csv_files + vital_signal_files[:2]
    
    return all_files, vital_csv_files, vital_signal_files


def test_phase1_workflow(all_files: list):
    """
    LangGraph를 사용한 Phase 0 + 0.5 + 1 워크플로우 테스트
    """
    print("=" * 60)
    print("🧠 Running Phase 0 + 0.5 + 1 via LangGraph Workflow")
    print("=" * 60)
    
    print(f"\n📁 Input Files: {len(all_files)}개")
    for f in all_files[:5]:
        print(f"   - {os.path.basename(f)}")
    if len(all_files) > 5:
        print(f"   ... and {len(all_files) - 5} more")
    print()
    
    # LangGraph 워크플로우 빌드
    memory = MemorySaver()
    agent = build_phase1_only_agent(checkpointer=memory)
    
    # 초기 상태 설정
    initial_state = {
        # Phase 0 필수 필드
        "input_files": all_files,
        "phase0_result": None,
        "phase0_file_ids": [],
        
        # Phase 0.5 필수 필드
        "phase05_result": None,
        "unique_columns": [],
        "unique_files": [],
        "column_batches": [],
        "file_batches": [],
        "llm_batches": [],
        
        # Phase 1 필수 필드
        "phase1_result": None,
        "column_semantic_mappings": [],
        "file_semantic_mappings": [],
        
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
    thread_config = {"configurable": {"thread_id": "phase1-test-1"}}
    
    print("▶️  LangGraph Phase 0 + 0.5 + 1 워크플로우 실행 중...\n")
    
    # 워크플로우 실행
    final_state = None
    for event in agent.stream(initial_state, thread_config, stream_mode="values"):
        final_state = event
    
    return final_state


def test_show_semantic_results(final_state: dict):
    """의미 분석 결과 상세 출력"""
    print("\n" + "=" * 60)
    print("📊 Semantic Analysis Results")
    print("=" * 60)
    
    if not final_state:
        print("❌ No final state available")
        return
    
    # Phase 1 결과
    phase1_result = final_state.get("phase1_result", {})
    column_mappings = final_state.get("column_semantic_mappings", [])
    file_mappings = final_state.get("file_semantic_mappings", [])
    
    print(f"\n📈 Summary:")
    print(f"   Columns analyzed: {phase1_result.get('total_columns_analyzed', 0)}")
    print(f"   Files analyzed: {phase1_result.get('total_files_analyzed', 0)}")
    print(f"   Total LLM calls: {phase1_result.get('total_llm_calls', 0)}")
    print(f"   Duration: {phase1_result.get('duration_seconds', 0):.1f}s")
    
    # 컬럼 매핑 결과
    if column_mappings:
        print(f"\n📋 Column Semantic Mappings ({len(column_mappings)} columns):")
        print("-" * 90)
        print(f"  {'Original':<30} {'Semantic':<25} {'Unit':<10} {'Concept'}")
        print("-" * 90)
        
        for mapping in column_mappings[:20]:
            orig = mapping.get('original', '?')[:28]
            sem = mapping.get('semantic', '?')[:23]
            unit = mapping.get('unit', '-') or '-'
            concept = mapping.get('concept', '?')
            print(f"  {orig:<30} {sem:<25} {unit:<10} {concept}")
        
        if len(column_mappings) > 20:
            print(f"  ... and {len(column_mappings) - 20} more")
    
    # 파일 매핑 결과
    if file_mappings:
        print(f"\n📁 File Semantic Mappings ({len(file_mappings)} files):")
        print("-" * 100)
        
        for mapping in file_mappings:
            name = mapping.get('file_name', '?')
            sem_type = mapping.get('semantic_type', '?')
            sem_name = mapping.get('semantic_name', '?')
            entity = mapping.get('primary_entity', '?')
            
            print(f"\n  📄 {name}")
            print(f"     Type: {sem_type}")
            print(f"     Name: {sem_name}")
            print(f"     Entity: {entity}")
            print(f"     Purpose: {mapping.get('purpose', '-')[:60]}...")
    
    print()


def test_query_db_results():
    """DB에서 분석 결과 조회"""
    print("\n" + "=" * 60)
    print("🗄️ Database Results (After Phase 1)")
    print("=" * 60)
    
    from database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # 파일 semantic 정보 조회
    cursor.execute("""
        SELECT 
            file_name,
            semantic_type,
            semantic_name,
            primary_entity,
            domain,
            llm_confidence
        FROM file_catalog
        WHERE semantic_type IS NOT NULL
        ORDER BY file_name
    """)
    
    files = cursor.fetchall()
    print(f"\n📁 Files with Semantic Info ({len(files)}):")
    
    for row in files:
        name, sem_type, sem_name, entity, domain, conf = row
        conf_str = f"{conf:.2f}" if conf else "0.00"
        print(f"  {name}: {sem_type} | {domain} | entity={entity} | conf={conf_str}")
    
    # 컬럼 semantic 정보 조회 (유니크)
    cursor.execute("""
        SELECT DISTINCT
            original_name,
            semantic_name,
            unit,
            concept_category,
            llm_confidence
        FROM column_metadata
        WHERE semantic_name IS NOT NULL
        ORDER BY original_name
        LIMIT 30
    """)
    
    columns = cursor.fetchall()
    print(f"\n📊 Columns with Semantic Info (showing 30 of {len(columns)}):")
    print("-" * 100)
    print(f"  {'Original':<30} {'Semantic':<25} {'Unit':<10} {'Concept':<20} {'Conf'}")
    print("-" * 100)
    
    for row in columns:
        orig, sem, unit, concept, conf = row
        orig_str = (orig or '?')[:28]
        sem_str = (sem or '?')[:23]
        unit_str = (unit or '-')[:8]
        concept_str = (concept or '?')[:18]
        conf_str = f"{conf:.2f}" if conf else "?"
        print(f"  {orig_str:<30} {sem_str:<25} {unit_str:<10} {concept_str:<20} {conf_str}")
    
    print()


def main():
    """메인 테스트 실행"""
    print("\n" + "=" * 60)
    print("Phase 0 + 0.5 + 1 Semantic Analysis Test")
    print(f"Column Batch Size: {Phase1Config.COLUMN_BATCH_SIZE}")
    print(f"File Batch Size: {Phase1Config.FILE_BATCH_SIZE}")
    print("=" * 60 + "\n")
    
    # 입력 파일 로드
    all_files, vital_csv_files, vital_signal_files = get_input_files()
    
    print(f"📁 Found files:")
    print(f"   📊 VitalDB CSV: {len(vital_csv_files)}개")
    print(f"   📈 VitalDB Signal: {len(vital_signal_files)}개 (using first 2)")
    print(f"   ➡️  Total to process: {len(all_files)}개")
    print()
    
    if not all_files:
        print(f"❌ 파일을 찾을 수 없습니다")
        return 1
    
    try:
        # 1. 스키마 초기화
        print("=" * 60)
        print("1. Ensuring Schema Exists (with reset)")
        print("=" * 60)
        init_catalog_schema(reset=True)
        print("✓ Schema ready\n")
        
        # 2. LangGraph 워크플로우 실행 (Phase 0 + 0.5 + 1)
        final_state = test_phase1_workflow(all_files)
        
        # 3. 의미 분석 결과 출력
        test_show_semantic_results(final_state)
        
        # 4. DB 결과 조회
        test_query_db_results()
        
        # 5. State 요약
        print("=" * 60)
        print("📋 Final State Summary")
        print("=" * 60)
        
        if final_state:
            print(f"\n   phase0_file_ids: {len(final_state.get('phase0_file_ids', []))} files")
            print(f"   unique_columns: {len(final_state.get('unique_columns', []))} columns")
            print(f"   unique_files: {len(final_state.get('unique_files', []))} files")
            print(f"   column_semantic_mappings: {len(final_state.get('column_semantic_mappings', []))} mappings")
            print(f"   file_semantic_mappings: {len(final_state.get('file_semantic_mappings', []))} mappings")
        
        print("\n" + "=" * 60)
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

