#!/usr/bin/env python3
"""
Test Full Pipeline: Phase 0 → Phase 0.5 → Phase 1

Phase 0부터 Phase 1까지 전체 파이프라인을 테스트합니다.
Human Review는 CLI에서 직접 input()으로 수집합니다 (no interrupt).
"""

import os
import sys
import glob
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.database.connection import get_db_manager
from src.database.schema_catalog import init_catalog_schema
from src.config import Phase1Config


# =============================================================================
# Input File Loader (same as test_phase0.py)
# =============================================================================

def get_input_files():
    """
    test_phase0.py / test_agent_with_interrupt.py와 동일한 파일 목록 반환
    
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


# =============================================================================
# Helper Functions
# =============================================================================

def print_separator(title: str = "", char: str = "=", width: int = 70):
    """구분선 출력"""
    if title:
        padding = (width - len(title) - 2) // 2
        print(f"\n{char * padding} {title} {char * padding}")
    else:
        print(char * width)


def show_db_status():
    """DB 상태 출력"""
    print_separator("DB Status Check", "-")
    
    db = get_db_manager()
    conn = None
    cursor = None
    
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # file_catalog 통계
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(semantic_type) as with_semantic,
                AVG(llm_confidence) as avg_conf
            FROM file_catalog
        """)
        row = cursor.fetchone()
        
        print(f"\n📁 file_catalog:")
        print(f"   Total files: {row[0]}")
        print(f"   With semantic: {row[1]}")
        print(f"   Avg confidence: {row[2]:.2f}" if row[2] else "   Avg confidence: N/A")
        
        # column_metadata 통계
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(semantic_name) as with_semantic,
                AVG(llm_confidence) as avg_conf
            FROM column_metadata
        """)
        row = cursor.fetchone()
        
        print(f"\n📊 column_metadata:")
        print(f"   Total columns: {row[0]}")
        print(f"   With semantic: {row[1]}")
        print(f"   Avg confidence: {row[2]:.2f}" if row[2] else "   Avg confidence: N/A")
        
        conn.commit()
        
    except Exception as e:
        print(f"   ❌ Error querying DB: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()


def show_sample_results():
    """샘플 결과 출력"""
    print_separator("Sample Results", "-")
    
    db = get_db_manager()
    conn = None
    cursor = None
    
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # 파일 전체
        cursor.execute("""
            SELECT file_name, semantic_type, semantic_name, domain, llm_confidence
            FROM file_catalog
            WHERE llm_confidence IS NOT NULL
            ORDER BY llm_confidence DESC
        """)
        rows = cursor.fetchall()
        
        if rows:
            print(f"\n📁 File Analysis Results (all {len(rows)} files):")
            for r in rows:
                conf = f"{r[4]:.2f}" if r[4] else "N/A"
                print(f"   {r[0]:30} → {r[1] or 'N/A':20} [{r[3] or 'N/A':15}] conf={conf}")
        
        # 컬럼 샘플
        cursor.execute("""
            SELECT original_name, semantic_name, concept_category, llm_confidence
            FROM column_metadata
            WHERE llm_confidence IS NOT NULL
            ORDER BY llm_confidence DESC
            LIMIT 10
        """)
        rows = cursor.fetchall()
        
        if rows:
            print(f"\n📊 Column Analysis Results (top 10):")
            for r in rows:
                conf = f"{r[3]:.2f}" if r[3] else "N/A"
                print(f"   {r[0]:30} → {r[1] or 'N/A':25} [{r[2] or 'N/A':15}] conf={conf}")
        
        conn.commit()
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()


def reset_database():
    """DB 초기화"""
    print_separator("Resetting Database", "-")
    
    try:
        init_catalog_schema(reset=True)
        print("   ✅ Database reset complete")
    except Exception as e:
        print(f"   ❌ Error resetting database: {e}")
        raise


# =============================================================================
# Main Test
# =============================================================================

def run_full_pipeline():
    """전체 파이프라인 실행"""
    
    # 입력 파일 로드 (test_phase0.py와 동일)
    all_files, vital_csv_files, vital_signal_files, inspire_files = get_input_files()
    
    print_separator("🚀 FULL PIPELINE TEST", "=", 70)
    print(f"   Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Input files: {len(all_files)}")
    print(f"   Confidence threshold: {Phase1Config.CONFIDENCE_THRESHOLD}")
    print(f"   Max review retries: {Phase1Config.MAX_REVIEW_RETRIES}")
    
    # 파일 구성 출력
    print(f"\n📁 Found files:")
    print(f"   📊 VitalDB CSV: {len(vital_csv_files)}개")
    print(f"   📈 VitalDB Signal: {len(vital_signal_files)}개 (using first 2)")
    print(f"   📋 INSPIRE CSV: {len(inspire_files)}개 (not used)")
    print(f"   ➡️  Total to process: {len(all_files)}개")
    
    # 1. DB 초기화
    reset_database()
    
    # 2. 파일 존재 확인
    print_separator("Checking Input Files", "-")
    valid_files = []
    
    for f in all_files:
        fp = Path(f)
        if fp.exists():
            print(f"   ✅ {fp.name} ({fp.stat().st_size / 1024:.1f} KB)")
            valid_files.append(str(fp))
        else:
            print(f"   ❌ {fp.name} (not found)")
    
    if not valid_files:
        print("\n❌ No valid input files found!")
        return
    
    # 3. LangGraph Agent 빌드 및 실행
    print_separator("Building LangGraph Agent", "-")
    
    from src.agents.graph import build_phase1_only_agent
    from src.agents.state import AgentState
    
    agent = build_phase1_only_agent()
    print("   ✅ Agent built successfully")
    
    # 4. Initial State 설정
    initial_state: AgentState = {
        "messages": [],
        "input_files": valid_files,
        "input_directory": None,
        "phase0_result": None,
        "phase0_file_ids": [],
        "phase05_result": None,
        "unique_columns": [],
        "unique_files": [],
        "column_batches": [],
        "file_batches": [],
        "phase1_result": None,
        "column_semantic_mappings": [],
        "file_semantic_mappings": [],
        "phase1_all_batch_states": [],
        "phase1_review_queue": None,
        "phase1_current_batch": None,
        "phase1_human_feedback": None,
    }
    
    config = {"configurable": {"thread_id": "full_pipeline_test_001"}}
    
    # 5. 파이프라인 실행
    print_separator("🎬 Running Pipeline", "=", 70)
    print("\n💡 When prompted for Human Review:")
    print("   [1] accept  - Accept current analysis")
    print("   [2] correct - Provide corrections (JSON)")
    print("   [3] skip    - Skip this batch")
    print("   [q] quit    - Exit immediately")
    print("")
    
    started_at = datetime.now()
    
    try:
        # 단순 invoke - interrupt 없이 노드 내부에서 Human Review 수행
        final_state = agent.invoke(initial_state, config)
        
        # 6. 결과 출력
        print_separator("📊 Pipeline Results", "=", 70)
        
        # Phase 0 결과
        phase0 = final_state.get("phase0_result", {})
        print(f"\n📁 Phase 0 (Data Catalog):")
        print(f"   Files processed: {phase0.get('processed_files', 0)}")
        print(f"   Files skipped: {phase0.get('skipped_files', 0)}")
        print(f"   Files failed: {phase0.get('failed_files', 0)}")
        
        # Phase 0.5 결과
        phase05 = final_state.get("phase05_result", {})
        print(f"\n📋 Phase 0.5 (Aggregation):")
        print(f"   Unique columns: {phase05.get('unique_column_count', 0)}")
        print(f"   Unique files: {phase05.get('unique_file_count', 0)}")
        print(f"   Column batches: {phase05.get('column_batch_count', 0)}")
        print(f"   File batches: {phase05.get('file_batch_count', 0)}")
        
        # Phase 1 결과
        phase1 = final_state.get("phase1_result", {})
        print(f"\n🧠 Phase 1 (Semantic Analysis):")
        print(f"   Columns analyzed: {phase1.get('total_columns_analyzed', 0)}")
        print(f"      - High confidence: {phase1.get('columns_high_conf', 0)}")
        print(f"      - Low confidence: {phase1.get('columns_low_conf', 0)}")
        print(f"   Files analyzed: {phase1.get('total_files_analyzed', 0)}")
        print(f"      - High confidence: {phase1.get('files_high_conf', 0)}")
        print(f"      - Low confidence: {phase1.get('files_low_conf', 0)}")
        print(f"   Review requests: {phase1.get('total_review_requests', 0)}")
        print(f"   Re-analyzes: {phase1.get('total_reanalyzes', 0)}")
        print(f"   Force accepted: {phase1.get('batches_force_accepted', 0)}")
        print(f"   Total LLM calls: {phase1.get('total_llm_calls', 0)}")
        
        # Duration
        ended_at = datetime.now()
        duration = (ended_at - started_at).total_seconds()
        print(f"\n⏱️ Total Duration: {duration:.1f}s")
        
        # DB 상태
        show_db_status()
        
        # 샘플 결과
        show_sample_results()
        
        print_separator("✅ TEST COMPLETED SUCCESSFULLY", "=", 70)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Pipeline interrupted by user")
        show_db_status()
        
    except Exception as e:
        print(f"\n❌ Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        show_db_status()
        raise


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    run_full_pipeline()