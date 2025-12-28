#!/usr/bin/env python3
"""
Phase 2B (Relationship Inference + Neo4j) 테스트 스크립트

전체 파이프라인 실행:
- Phase 0: 파일/컬럼 물리적 정보 수집 (rule-based)
- Phase 0.5: 스키마 집계 (rule-based)
- Phase 0.7: 파일을 metadata/data로 분류 (LLM)
- Phase 1A: metadata 파일에서 data_dictionary 추출 (LLM)
- Phase 1B: data 파일 컬럼 의미 분석 + dictionary 매칭 (LLM)
- Phase 2A: 테이블 Entity 식별 (row_represents, entity_identifier) (LLM)
- Phase 2B: 테이블 간 FK 관계 추론 + Neo4j 3-Level Ontology (LLM + Rule)
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


def run_phase2b_pipeline():
    """Phase 2B 파이프라인 실행"""
    print("\n" + "="*60)
    print("🚀 Running Phase 2B Pipeline (Relationship Inference + Neo4j)")
    print("="*60)
    
    # 데이터 파일 찾기
    input_files = find_data_files()
    
    if not input_files:
        print("❌ No data files found!")
        return None
    
    # Agent 생성
    from src.agents.graph import build_phase2b_agent
    agent = build_phase2b_agent()
    
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
        
        # Phase 2B result placeholders
        "phase2b_result": None,
        "table_relationships": [],
        
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
            "session_id": f"test_phase2b_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
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


def print_table_entities(limit: int = 10):
    """table_entities 테이블 출력"""
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📊 table_entities")
    print("="*80)
    
    try:
        cursor.execute("""
            SELECT 
                fc.file_name,
                te.row_represents,
                te.entity_identifier,
                te.confidence
            FROM table_entities te
            JOIN file_catalog fc ON te.file_id = fc.file_id
            ORDER BY te.confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        if not rows:
            print("(No entities found)")
        else:
            print(f"\n{'File':<40} {'Row Represents':<20} {'Identifier':<15} {'Conf.'}")
            print("-"*85)
            
            for row in rows:
                file_name, row_represents, entity_identifier, confidence = row
                file_short = file_name[:37] + "..." if len(file_name) > 40 else file_name
                id_col = entity_identifier or "(none)"
                
                print(f"{file_short:<40} {row_represents:<20} {id_col:<15} {confidence:.2f}")
            
            print(f"\nShowing {len(rows)} entities")
    
    except Exception as e:
        print(f"Error: {e}")


def print_table_relationships(limit: int = 10):
    """table_relationships 테이블 출력"""
    from src.database.connection import get_db_manager
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("🔗 table_relationships")
    print("="*80)
    
    try:
        cursor.execute("""
            SELECT 
                fc1.file_name as source_file,
                fc2.file_name as target_file,
                tr.source_column,
                tr.target_column,
                tr.cardinality,
                tr.confidence,
                tr.reasoning
            FROM table_relationships tr
            JOIN file_catalog fc1 ON tr.source_file_id = fc1.file_id
            JOIN file_catalog fc2 ON tr.target_file_id = fc2.file_id
            ORDER BY tr.confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        if not rows:
            print("(No relationships found)")
        else:
            print(f"\n{'Source':<30} {'Target':<30} {'Columns':<25} {'Card.':<6} {'Conf.'}")
            print("-"*100)
            
            for row in rows:
                (source_file, target_file, source_col, target_col, 
                 cardinality, confidence, reasoning) = row
                
                source_short = source_file[:27] + "..." if len(source_file) > 30 else source_file
                target_short = target_file[:27] + "..." if len(target_file) > 30 else target_file
                col_str = f"{source_col}→{target_col}"
                col_short = col_str[:22] + "..." if len(col_str) > 25 else col_str
                
                print(f"{source_short:<30} {target_short:<30} {col_short:<25} {cardinality:<6} {confidence:.2f}")
            
            print(f"\nShowing {len(rows)} relationships")
    
    except Exception as e:
        print(f"Error: {e}")


def print_neo4j_stats():
    """Neo4j 통계 출력"""
    try:
        from neo4j import GraphDatabase
        from src.config import Neo4jConfig
        
        driver = GraphDatabase.driver(
            Neo4jConfig.URI,
            auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
        )
        driver.verify_connectivity()
        
        print("\n" + "="*80)
        print("📊 Neo4j Graph Statistics")
        print("="*80)
        
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            # Node counts
            result = session.run("MATCH (n:RowEntity) RETURN count(n) as cnt")
            row_entities = result.single()["cnt"]
            
            result = session.run("MATCH (n:ConceptCategory) RETURN count(n) as cnt")
            concepts = result.single()["cnt"]
            
            result = session.run("MATCH (n:Parameter) RETURN count(n) as cnt")
            parameters = result.single()["cnt"]
            
            # Edge counts
            result = session.run("MATCH ()-[r:LINKS_TO]->() RETURN count(r) as cnt")
            links_to = result.single()["cnt"]
            
            result = session.run("MATCH ()-[r:HAS_CONCEPT]->() RETURN count(r) as cnt")
            has_concept = result.single()["cnt"]
            
            result = session.run("MATCH ()-[r:CONTAINS]->() RETURN count(r) as cnt")
            contains = result.single()["cnt"]
            
            result = session.run("MATCH ()-[r:HAS_COLUMN]->() RETURN count(r) as cnt")
            has_column = result.single()["cnt"]
            
            print(f"\nNodes:")
            print(f"  RowEntity:       {row_entities}")
            print(f"  ConceptCategory: {concepts}")
            print(f"  Parameter:       {parameters}")
            
            print(f"\nEdges:")
            print(f"  LINKS_TO:        {links_to}")
            print(f"  HAS_CONCEPT:     {has_concept}")
            print(f"  CONTAINS:        {contains}")
            print(f"  HAS_COLUMN:      {has_column}")
            
            # Sample RowEntity nodes
            if row_entities > 0:
                print("\nSample RowEntity nodes:")
                result = session.run("""
                    MATCH (e:RowEntity)
                    RETURN e.file_name as file_name, e.name as row_represents
                    LIMIT 5
                """)
                for record in result:
                    print(f"  - {record['file_name']}: {record['row_represents']}")
            
            # Sample relationships
            if links_to > 0:
                print("\nSample LINKS_TO relationships:")
                result = session.run("""
                    MATCH (s:RowEntity)-[r:LINKS_TO]->(t:RowEntity)
                    RETURN s.file_name as source, t.file_name as target, 
                           r.source_column as col, r.cardinality as card
                    LIMIT 5
                """)
                for record in result:
                    print(f"  - {record['source']} → {record['target']} ({record['col']}, {record['card']})")
        
        driver.close()
        
    except Exception as e:
        print(f"\n⚠️ Neo4j connection failed: {e}")
        print("   (Neo4j may not be running or not configured)")


def print_phase2b_summary(final_state):
    """Phase 2B 결과 요약 출력"""
    if not final_state:
        return
    
    phase2b = final_state.get("phase2b_result", {})
    
    if not phase2b:
        print("\n⚠️ No Phase 2B result found")
        return
    
    print("\n" + "="*60)
    print("📊 Phase 2B Result Summary")
    print("="*60)
    
    print(f"\n🔗 Relationships:")
    print(f"   Found: {phase2b.get('relationships_found', 0)}")
    print(f"   High confidence: {phase2b.get('relationships_high_conf', 0)}")
    
    print(f"\n📊 Neo4j Graph:")
    print(f"   RowEntity nodes: {phase2b.get('row_entity_nodes', 0)}")
    print(f"   ConceptCategory nodes: {phase2b.get('concept_category_nodes', 0)}")
    print(f"   Parameter nodes: {phase2b.get('parameter_nodes', 0)}")
    
    print(f"\n🔗 Edges:")
    print(f"   LINKS_TO: {phase2b.get('edges_links_to', 0)}")
    print(f"   HAS_CONCEPT: {phase2b.get('edges_has_concept', 0)}")
    print(f"   CONTAINS: {phase2b.get('edges_contains', 0)}")
    print(f"   HAS_COLUMN: {phase2b.get('edges_has_column', 0)}")
    
    print(f"\n⚙️ Meta:")
    print(f"   LLM calls: {phase2b.get('llm_calls', 0)}")
    print(f"   Neo4j synced: {phase2b.get('neo4j_synced', False)}")


def main():
    """메인 테스트 함수"""
    print("="*80)
    print("🧪 Phase 2B Full Pipeline Test")
    print("="*80)
    
    # 1. DB 리셋
    reset_database()
    
    # 2. 파이프라인 실행
    final_state = run_phase2b_pipeline()
    
    if final_state:
        # 3. 결과 출력
        print_phase2b_summary(final_state)
        print_table_entities()
        print_table_relationships()
        print_neo4j_stats()
        
        # 4. 에러/경고 출력
        errors = final_state.get('errors', [])
        warnings = final_state.get('warnings', [])
        
        if errors:
            print(f"\n⚠️ Errors ({len(errors)}):")
            for err in errors[:5]:
                print(f"   - {err}")
        
        if warnings:
            print(f"\n⚠️ Warnings ({len(warnings)}):")
            for warn in warnings[:5]:
                print(f"   - {warn}")


if __name__ == "__main__":
    main()
