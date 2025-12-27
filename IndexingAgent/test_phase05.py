#!/usr/bin/env python
"""
Phase 0 + 0.5 테스트 스크립트 (LangGraph 기반)

Phase 0: Data Catalog (파일 스캔 → DB 저장)
Phase 0.5: Schema Aggregation (유니크 컬럼 집계 → LLM 배치 준비)
"""

import sys
import os
import glob
from pathlib import Path

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from langgraph.checkpoint.memory import MemorySaver

from agents.graph import build_phase05_only_agent
from agents.nodes.aggregator import run_aggregation, get_aggregation_stats
from database.schema_catalog import init_catalog_schema
from config import Phase05Config


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


def test_phase05_workflow(all_files: list):
    """
    LangGraph를 사용한 Phase 0 + 0.5 워크플로우 테스트
    """
    print("=" * 60)
    print("🔄 Running Phase 0 + 0.5 via LangGraph Workflow")
    print("=" * 60)
    
    print(f"\n📁 Input Files: {len(all_files)}개")
    for f in all_files[:5]:
        print(f"   - {os.path.basename(f)}")
    if len(all_files) > 5:
        print(f"   ... and {len(all_files) - 5} more")
    print()
    
    # LangGraph 워크플로우 빌드
    memory = MemorySaver()
    agent = build_phase05_only_agent(checkpointer=memory)
    
    # 초기 상태 설정
    initial_state = {
        # Phase 0 필수 필드
        "input_files": all_files,
        "phase0_result": None,
        "phase0_file_ids": [],
        
        # Phase 0.5 필수 필드
        "phase05_result": None,
        "unique_columns": [],
        "llm_batches": [],
        
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
    thread_config = {"configurable": {"thread_id": "phase05-test-1"}}
    
    print("▶️  LangGraph Phase 0 + 0.5 워크플로우 실행 중...\n")
    
    # 워크플로우 실행
    final_state = None
    for event in agent.stream(initial_state, thread_config, stream_mode="values"):
        final_state = event
    
    return final_state


def test_show_aggregation_result(final_state: dict):
    """집계 결과 상세 출력"""
    print("\n" + "=" * 60)
    print("📊 Aggregation Result Details")
    print("=" * 60)
    
    if not final_state:
        print("❌ No final state available")
        return
    
    # Phase 0.5 결과
    phase05_result = final_state.get("phase05_result", {})
    unique_columns = final_state.get("unique_columns", [])
    llm_batches = final_state.get("llm_batches", [])
    
    print(f"\n📈 Summary:")
    print(f"   Total columns in DB: {phase05_result.get('total_columns_in_db', 0):,}")
    print(f"   Unique columns: {phase05_result.get('unique_column_count', 0):,}")
    print(f"   Batch size: {phase05_result.get('batch_size', 0)}")
    print(f"   Total batches: {phase05_result.get('total_batches', 0)}")
    
    # 유니크 컬럼 상세 (처음 20개)
    if unique_columns:
        print(f"\n📋 Unique Columns (top 20 by frequency):")
        print("-" * 90)
        print(f"  {'#':<4} {'Column Name':<35} {'Type':<12} {'Freq':<6} {'Stats'}")
        print("-" * 90)
        
        for i, col in enumerate(unique_columns[:20]):
            name = col.get('original_name', '?')[:33]
            col_type = col.get('column_type', 'unknown')[:10]
            freq = col.get('frequency', 0)
            
            # 통계 요약
            stats = []
            if col.get('avg_min') is not None:
                stats.append(f"range=[{col.get('avg_min'):.1f}, {col.get('avg_max'):.1f}]")
            if col.get('avg_unique_ratio') is not None:
                stats.append(f"unique_ratio={col.get('avg_unique_ratio'):.2f}")
            if col.get('sample_values'):
                values = list(col['sample_values'].keys())[:3]
                stats.append(f"values={values}")
            
            stats_str = ", ".join(stats) if stats else "-"
            print(f"  {i+1:<4} {name:<35} {col_type:<12} {freq:<6} {stats_str}")
        
        if len(unique_columns) > 20:
            print(f"  ... and {len(unique_columns) - 20} more")
    
    # 배치 정보
    if llm_batches:
        print(f"\n📦 LLM Batches Preview:")
        print("-" * 50)
        for i, batch in enumerate(llm_batches[:3]):
            batch_cols = [c.get('original_name', '?') for c in batch[:5]]
            batch_preview = ", ".join(batch_cols)
            if len(batch) > 5:
                batch_preview += f" ... (+{len(batch) - 5})"
            print(f"   Batch {i+1}: [{batch_preview}] ({len(batch)} columns)")
        
        if len(llm_batches) > 3:
            print(f"   ... and {len(llm_batches) - 3} more batches")
    
    print()


def test_show_column_type_distribution(unique_columns: list):
    """컬럼 타입별 분포"""
    print("\n" + "=" * 60)
    print("📊 Column Type Distribution")
    print("=" * 60)
    
    if not unique_columns:
        print("❌ No unique columns available")
        return
    
    # 타입별 집계
    type_counts = {}
    for col in unique_columns:
        col_type = col.get('column_type', 'unknown')
        type_counts[col_type] = type_counts.get(col_type, 0) + 1
    
    total = len(unique_columns)
    print(f"\n{'Type':<15} {'Count':<10} {'Percentage'}")
    print("-" * 40)
    
    for col_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        bar = "█" * int(pct / 5)
        print(f"{col_type:<15} {count:<10} {pct:5.1f}% {bar}")
    
    print(f"\n{'Total':<15} {total}")
    print()


def test_standalone_aggregation():
    """독립 실행 테스트 (LangGraph 없이)"""
    print("\n" + "=" * 60)
    print("🔧 Standalone Aggregation Test (without LangGraph)")
    print("=" * 60)
    
    result = run_aggregation(verbose=True)
    
    print(f"\n📊 Stats:")
    stats = result.get('stats', {})
    for key, value in stats.items():
        print(f"   {key}: {value}")


def main():
    """메인 테스트 실행"""
    print("\n" + "=" * 60)
    print("Phase 0 + 0.5 Schema Aggregation Test")
    print(f"(Batch Size: {Phase05Config.BATCH_SIZE})")
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
        # 1. 스키마 초기화 (Phase 0 테스트에서 이미 데이터가 있을 수 있음)
        print("=" * 60)
        print("1. Ensuring Schema Exists")
        print("=" * 60)
        init_catalog_schema(reset=True)  # 깨끗한 상태로 시작
        print("✓ Schema ready\n")
        
        # 2. LangGraph 워크플로우 실행 (Phase 0 + 0.5)
        final_state = test_phase05_workflow(all_files)
        
        # 3. 집계 결과 상세 출력
        test_show_aggregation_result(final_state)
        
        # 4. 컬럼 타입 분포
        unique_columns = final_state.get("unique_columns", []) if final_state else []
        test_show_column_type_distribution(unique_columns)
        
        # 5. State에 저장된 file_ids 확인
        print("=" * 60)
        print("📋 State Summary")
        print("=" * 60)
        
        if final_state:
            file_ids = final_state.get("phase0_file_ids", [])
            print(f"\n   phase0_file_ids: {len(file_ids)} files")
            
            unique_cols = final_state.get("unique_columns", [])
            print(f"   unique_columns: {len(unique_cols)} columns")
            
            batches = final_state.get("llm_batches", [])
            print(f"   llm_batches: {len(batches)} batches")
            print(f"      → Ready for Phase 1 LLM processing!")
        
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

