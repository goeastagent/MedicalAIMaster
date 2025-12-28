#!/usr/bin/env python3
"""
Phase 2A (Entity Identification) 테스트 스크립트

전체 파이프라인 실행:
- Phase 0: 파일/컬럼 물리적 정보 수집 (rule-based)
- Phase 0.5: 스키마 집계 (rule-based)
- Phase 0.7: 파일을 metadata/data로 분류 (LLM)
- Phase 1A: metadata 파일에서 data_dictionary 추출 (LLM)
- Phase 1B: data 파일 컬럼 의미 분석 + dictionary 매칭 (LLM)
- Phase 2A: 테이블 Entity 식별 (row_represents, entity_identifier) (LLM)
"""

import sys
import os

# 프로젝트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from pathlib import Path

# 데이터 경로 설정 (Open VitalDB만 테스트)
DATA_DIR = Path(__file__).parent / "data" / "raw" / "Open_VitalDB_1.0.0"


def reset_database():
    """테스트 전 DB 초기화"""
    print("\n" + "="*60)
    print("🗑️  Resetting Database...")
    print("="*60)
    
    from src.database.schema_catalog import CatalogSchemaManager
    from src.database.schema_dictionary import DictionarySchemaManager
    from src.database.schema_ontology import OntologySchemaManager
    
    # 기존 테이블 삭제 및 재생성 (schema_catalog)
    try:
        catalog_manager = CatalogSchemaManager()
        catalog_manager.drop_tables(confirm=True)
        catalog_manager.create_tables()
        print("✅ Schema catalog tables reset")
    except Exception as e:
        print(f"⚠️  Error resetting schema catalog tables: {e}")
    
    # 기존 테이블 삭제 및 재생성 (schema_dictionary)
    try:
        dict_manager = DictionarySchemaManager()
        dict_manager.drop_tables(confirm=True)
        dict_manager.create_tables()
        print("✅ Schema dictionary tables reset")
    except Exception as e:
        print(f"⚠️  Error resetting schema dictionary tables: {e}")
    
    # 온톨로지 스키마 재생성
    try:
        ontology_manager = OntologySchemaManager()
        ontology_manager.drop_tables(confirm=True)
        ontology_manager.create_tables()
        print("✅ Ontology tables reset")
    except Exception as e:
        print(f"⚠️  Error resetting ontology tables: {e}")


def find_data_files() -> list:
    """Open VitalDB 데이터 파일 찾기"""
    print(f"\n📂 Scanning: {DATA_DIR}")
    
    files = []
    
    if not DATA_DIR.exists():
        print(f"⚠️  Data directory not found: {DATA_DIR}")
        return files
    
    # CSV 파일 찾기
    for f in DATA_DIR.rglob("*.csv"):
        files.append(str(f))
        print(f"   Found: {f.name}")
    
    print(f"\n📁 Total files found: {len(files)}")
    return files


def run_phase2a_pipeline():
    """Phase 2A 파이프라인 실행"""
    print("\n" + "="*60)
    print("🚀 Running Phase 2A Pipeline (Entity Identification)")
    print("="*60)
    
    # 데이터 파일 찾기
    input_files = find_data_files()
    
    if not input_files:
        print("❌ No data files found!")
        return None
    
    # Agent 생성
    from src.agents.graph import build_phase2a_agent
    agent = build_phase2a_agent()
    
    # 초기 상태 설정
    initial_state = {
        # Dataset context
        "current_dataset_id": "open_vitaldb_v1.0.0",
        "current_table_name": None,
        "data_catalog": {},
        
        # Phase 0 result placeholders
        "phase0_result": None,
        "phase0_file_ids": [],
        
        # Phase 0.5 result placeholders
        "phase05_result": None,
        "unique_columns": [],
        "unique_files": [],
        "column_batches": [],
        "file_batches": [],
        
        # Phase 0.7 result placeholders
        "phase07_result": None,
        "metadata_files": [],
        "data_files": [],
        
        # Phase 1A result placeholders
        "phase1a_result": None,
        "data_dictionary_entries": [],
        
        # Phase 1B result placeholders
        "phase1b_result": None,
        "data_semantic_entries": [],
        
        # Phase 2A result placeholders
        "phase2a_result": None,
        "table_entity_results": [],
        
        # Legacy Phase 1 result placeholders
        "phase1_result": None,
        "column_semantic_mappings": [],
        "file_semantic_mappings": [],
        
        # Phase 1 Human Review placeholders
        "phase1_review_queue": None,
        "phase1_current_batch": None,
        "phase1_human_feedback": None,
        "phase1_all_batch_states": [],
        
        # Multi-Phase Workflow Context
        "input_files": input_files,
        "classification_result": None,
        "processing_progress": {
            "phase": "classification",
            "metadata_processed": [],
            "data_processed": [],
            "current_file": None,
            "current_file_index": 0,
            "total_files": len(input_files),
        },
        
        # Current File Context
        "file_path": "",
        "file_type": None,
        
        # Technical Metadata
        "raw_metadata": {},
        
        # Semantic Analysis Result
        "entity_identification": None,
        "finalized_schema": [],
        "entity_understanding": None,
        
        # Human-in-the-Loop
        "needs_human_review": False,
        "human_question": "",
        "human_feedback": None,
        "review_type": None,
        "conversation_history": {
            "session_id": f"test_phase2a_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "dataset_id": "open_vitaldb_v1.0.0",
            "started_at": datetime.now().isoformat(),
            "turns": [],
            "classification_decisions": [],
            "entity_decisions": [],
            "user_preferences": {},
        },
        
        # System Logs
        "logs": [],
        
        # Ontology Context
        "ontology_context": {},
        "skip_indexing": False,
        
        # Execution Context
        "retry_count": 0,
        "error_message": None,
        "project_context": {
            "master_entity_identifier": None,
            "known_aliases": [],
            "example_id_values": [],
        },
    }
    
    # 파이프라인 실행
    print("\n🏃 Starting pipeline execution...")
    start_time = datetime.now()
    
    try:
        final_state = agent.invoke(initial_state)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print("\n" + "="*60)
        print("✅ Pipeline Completed!")
        print(f"   Duration: {duration:.1f} seconds")
        print("="*60)
        
        return final_state
        
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def print_table_entities():
    """table_entities 테이블 내용 출력"""
    print("\n" + "="*60)
    print("📋 Table Entities (Phase 2A Results)")
    print("="*60)
    
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # table_entities 조회 (file_catalog와 JOIN하여 파일명 가져오기)
        cursor.execute("""
            SELECT 
                fc.file_name,
                te.row_represents,
                te.entity_identifier,
                te.confidence,
                te.reasoning,
                te.llm_analyzed_at
            FROM table_entities te
            JOIN file_catalog fc ON te.file_id = fc.file_id
            ORDER BY fc.file_name
        """)
        
        rows = cursor.fetchall()
        
        if not rows:
            print("No table entities found.")
            return
        
        print(f"\nTotal: {len(rows)} table entities\n")
        print("-"*80)
        
        for row in rows:
            file_name, row_represents, entity_identifier, confidence, reasoning, analyzed_at = row
            
            identifier_str = entity_identifier or "(none)"
            conf_emoji = "🟢" if confidence and confidence >= 0.8 else "🟡"
            
            print(f"{conf_emoji} {file_name}")
            print(f"   row_represents: {row_represents}")
            print(f"   entity_identifier: {identifier_str}")
            print(f"   confidence: {confidence:.2f}" if confidence else "   confidence: N/A")
            if reasoning:
                # 긴 reasoning은 자르기
                reasoning_short = reasoning[:100] + "..." if len(reasoning) > 100 else reasoning
                print(f"   reasoning: {reasoning_short}")
            print()
        
    except Exception as e:
        print(f"Error reading table_entities: {e}")
        import traceback
        traceback.print_exc()


def print_summary(state):
    """전체 파이프라인 결과 요약"""
    if not state:
        return
    
    print("\n" + "="*60)
    print("📊 Pipeline Summary")
    print("="*60)
    
    # Phase 0.7 결과
    phase07 = state.get('phase07_result', {})
    if phase07:
        print(f"\n[Phase 0.7: File Classification]")
        print(f"   Metadata files: {len(state.get('metadata_files', []))}")
        print(f"   Data files: {len(state.get('data_files', []))}")
    
    # Phase 1A 결과
    phase1a = state.get('phase1a_result', {})
    if phase1a:
        print(f"\n[Phase 1A: Metadata Semantic]")
        print(f"   Total entries extracted: {phase1a.get('total_entries_extracted', 0)}")
    
    # Phase 1B 결과
    phase1b = state.get('phase1b_result', {})
    if phase1b:
        print(f"\n[Phase 1B: Data Semantic]")
        print(f"   Columns analyzed: {phase1b.get('total_columns_analyzed', 0)}")
        print(f"   Columns matched: {phase1b.get('columns_matched', 0)}")
    
    # Phase 2A 결과
    phase2a = state.get('phase2a_result', {})
    if phase2a:
        print(f"\n[Phase 2A: Entity Identification]")
        print(f"   Tables analyzed: {phase2a.get('tables_analyzed', 0)}")
        print(f"   Entities identified: {phase2a.get('entities_identified', 0)}")
        print(f"   With unique identifier: {phase2a.get('identifiers_found', 0)}")
        print(f"   High confidence: {phase2a.get('high_confidence', 0)}")
        print(f"   Low confidence: {phase2a.get('low_confidence', 0)}")
        print(f"   LLM calls: {phase2a.get('llm_calls', 0)}")


def main():
    """메인 실행"""
    print("\n" + "="*60)
    print("🧪 Phase 2A Test: Entity Identification")
    print("="*60)
    print(f"Started at: {datetime.now().isoformat()}")
    
    # 1. DB 초기화
    reset_database()
    
    # 2. 파이프라인 실행
    final_state = run_phase2a_pipeline()
    
    # 3. table_entities 테이블 출력
    print_table_entities()
    
    # 4. 전체 요약
    print_summary(final_state)
    
    print("\n" + "="*60)
    print(f"✅ Test completed at: {datetime.now().isoformat()}")
    print("="*60)


if __name__ == "__main__":
    main()

