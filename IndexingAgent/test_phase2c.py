#!/usr/bin/env python3
"""
Phase 2C (Ontology Enhancement) 테스트 스크립트

전체 파이프라인 실행:
- Phase 0: 파일/컬럼 물리적 정보 수집 (rule-based)
- Phase 0.5: 스키마 집계 (rule-based)
- Phase 0.7: 파일을 metadata/data로 분류 (LLM)
- Phase 1A: metadata 파일에서 data_dictionary 추출 (LLM)
- Phase 1B: data 파일 컬럼 의미 분석 + dictionary 매칭 (LLM)
- Phase 2A: 테이블 Entity 식별 (row_represents, entity_identifier) (LLM)
- Phase 2B: 테이블 간 FK 관계 추론 + Neo4j 3-Level Ontology (LLM + Rule)
- Phase 2C: Ontology Enhancement (Concept Hierarchy, Semantic Edges, Medical Terms)
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
    """테스트 전 DB 초기화
    
    FK 참조 관계로 인해 삭제/생성 순서가 중요:
    - 삭제: Ontology → Dictionary → Catalog (참조하는 것 먼저)
    - 생성: Catalog → Dictionary → Ontology (참조되는 것 먼저)
    """
    print("\n" + "="*60)
    print("🗑️  Resetting Database...")
    print("="*60)
    
    from src.database.schema_catalog import CatalogSchemaManager
    from src.database.schema_dictionary import DictionarySchemaManager
    from src.database.schema_ontology import OntologySchemaManager
    
    # 1. 삭제: FK 참조하는 테이블 먼저 (역순)
    try:
        OntologySchemaManager().drop_tables(confirm=True)
        print("✅ Ontology tables dropped")
    except Exception as e:
        print(f"⚠️  Error: {e}")
    
    try:
        DictionarySchemaManager().drop_tables(confirm=True)
        print("✅ Dictionary tables dropped")
    except Exception as e:
        print(f"⚠️  Error: {e}")
    
    try:
        CatalogSchemaManager().drop_tables(confirm=True)
        print("✅ Catalog tables dropped")
    except Exception as e:
        print(f"⚠️  Error: {e}")
    
    # 2. 생성: FK 참조되는 테이블 먼저 (정순)
    try:
        CatalogSchemaManager().create_tables()
        print("✅ Catalog tables created")
    except Exception as e:
        print(f"⚠️  Error: {e}")
    
    try:
        DictionarySchemaManager().create_tables()
        print("✅ Dictionary tables created")
    except Exception as e:
        print(f"⚠️  Error: {e}")
    
    try:
        OntologySchemaManager().create_tables()
        print("✅ Ontology tables created")
    except Exception as e:
        print(f"⚠️  Error: {e}")


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


def run_phase2c_pipeline():
    """Phase 2C 파이프라인 실행"""
    print("\n" + "="*60)
    print("🚀 Running Phase 2C Pipeline (Ontology Enhancement)")
    print("="*60)
    
    # 데이터 파일 찾기
    input_files = find_data_files()
    
    if not input_files:
        print("❌ No data files found!")
        return None
    
    # Agent 생성
    from src.agents.graph import build_phase2c_agent
    agent = build_phase2c_agent()
    
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
        
        # Phase 2C result placeholders
        "phase2c_result": None,
        "ontology_subcategories": [],
        "semantic_edges": [],
        "medical_term_mappings": [],
        "cross_table_semantics": [],
        
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
            "session_id": f"test_phase2c_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
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


def print_phase2c_summary(final_state):
    """Phase 2C 결과 요약 출력"""
    if not final_state:
        return
    
    phase2c = final_state.get("phase2c_result", {})
    
    if not phase2c:
        print("\n⚠️ No Phase 2C result found")
        return
    
    print("\n" + "="*60)
    print("📊 Phase 2C Result Summary")
    print("="*60)
    
    print(f"\n📁 Task 1 - Concept Hierarchy:")
    print(f"   Subcategories created: {phase2c.get('subcategories_created', 0)}")
    print(f"   High confidence: {phase2c.get('subcategories_high_conf', 0)}")
    
    print(f"\n🔗 Task 2 - Semantic Edges:")
    print(f"   Total edges: {phase2c.get('semantic_edges_created', 0)}")
    print(f"   DERIVED_FROM: {phase2c.get('derived_from_edges', 0)}")
    print(f"   RELATED_TO: {phase2c.get('related_to_edges', 0)}")
    
    print(f"\n🏥 Task 3 - Medical Terms:")
    print(f"   Total mapped: {phase2c.get('medical_terms_mapped', 0)}")
    print(f"   SNOMED: {phase2c.get('snomed_mappings', 0)}")
    print(f"   LOINC: {phase2c.get('loinc_mappings', 0)}")
    
    print(f"\n🔄 Task 4 - Cross-table:")
    print(f"   Semantics found: {phase2c.get('cross_table_semantics', 0)}")
    
    print(f"\n📊 Neo4j Enhancements:")
    print(f"   SubCategory nodes: {phase2c.get('neo4j_subcategory_nodes', 0)}")
    print(f"   MedicalTerm nodes: {phase2c.get('neo4j_medical_term_nodes', 0)}")
    print(f"   Semantic edges: {phase2c.get('neo4j_semantic_edges', 0)}")
    print(f"   Cross-table edges: {phase2c.get('neo4j_cross_table_edges', 0)}")
    
    print(f"\n⚙️ Meta:")
    print(f"   LLM calls: {phase2c.get('llm_calls', 0)}")
    print(f"   Neo4j synced: {phase2c.get('neo4j_synced', False)}")


def print_subcategories(final_state, limit: int = 10):
    """Subcategories 출력"""
    subcats = final_state.get("ontology_subcategories", [])
    
    print("\n" + "="*60)
    print("📁 Subcategories")
    print("="*60)
    
    if not subcats:
        print("(No subcategories found)")
        return
    
    print(f"\n{'Parent':<25} {'Subcategory':<25} {'Params':<8} {'Conf.'}")
    print("-"*70)
    
    for subcat in subcats[:limit]:
        parent = subcat.get('parent_category', '')[:22]
        name = subcat.get('subcategory_name', '')[:22]
        params = len(subcat.get('parameters', []))
        conf = subcat.get('confidence', 0.0)
        
        print(f"{parent:<25} {name:<25} {params:<8} {conf:.2f}")
    
    if len(subcats) > limit:
        print(f"\n... and {len(subcats) - limit} more")


def print_semantic_edges(final_state, limit: int = 15):
    """Semantic Edges 출력"""
    edges = final_state.get("semantic_edges", [])
    
    print("\n" + "="*60)
    print("🔗 Semantic Edges")
    print("="*60)
    
    if not edges:
        print("(No semantic edges found)")
        return
    
    print(f"\n{'Source':<20} {'Relation':<15} {'Target':<20} {'Conf.'}")
    print("-"*65)
    
    for edge in edges[:limit]:
        source = edge.get('source_parameter', '')[:17]
        rel = edge.get('relationship_type', '')[:12]
        target = edge.get('target_parameter', '')[:17]
        conf = edge.get('confidence', 0.0)
        
        print(f"{source:<20} {rel:<15} {target:<20} {conf:.2f}")
    
    if len(edges) > limit:
        print(f"\n... and {len(edges) - limit} more")


def print_medical_terms(final_state, limit: int = 15):
    """Medical Term Mappings 출력"""
    mappings = final_state.get("medical_term_mappings", [])
    
    print("\n" + "="*60)
    print("🏥 Medical Term Mappings")
    print("="*60)
    
    if not mappings:
        print("(No medical term mappings found)")
        return
    
    print(f"\n{'Parameter':<15} {'SNOMED Code':<15} {'LOINC Code':<12} {'Conf.'}")
    print("-"*55)
    
    for m in mappings[:limit]:
        param = m.get('parameter_key', '')[:12]
        snomed = m.get('snomed_code') or '-'
        loinc = m.get('loinc_code') or '-'
        conf = m.get('confidence', 0.0)
        
        print(f"{param:<15} {snomed:<15} {loinc:<12} {conf:.2f}")
    
    if len(mappings) > limit:
        print(f"\n... and {len(mappings) - limit} more")


def print_neo4j_enhanced_stats():
    """Neo4j 확장된 통계 출력"""
    try:
        from neo4j import GraphDatabase
        from src.config import Neo4jConfig
        
        driver = GraphDatabase.driver(
            Neo4jConfig.URI,
            auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
        )
        driver.verify_connectivity()
        
        print("\n" + "="*60)
        print("📊 Neo4j Enhanced Graph Statistics")
        print("="*60)
        
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            # 기존 노드
            result = session.run("MATCH (n:RowEntity) RETURN count(n) as cnt")
            row_entities = result.single()["cnt"]
            
            result = session.run("MATCH (n:ConceptCategory) RETURN count(n) as cnt")
            concepts = result.single()["cnt"]
            
            result = session.run("MATCH (n:Parameter) RETURN count(n) as cnt")
            parameters = result.single()["cnt"]
            
            # Phase 2C 노드
            result = session.run("MATCH (n:SubCategory) RETURN count(n) as cnt")
            subcategories = result.single()["cnt"]
            
            result = session.run("MATCH (n:MedicalTerm) RETURN count(n) as cnt")
            medical_terms = result.single()["cnt"]
            
            # 기존 엣지
            result = session.run("MATCH ()-[r:LINKS_TO]->() RETURN count(r) as cnt")
            links_to = result.single()["cnt"]
            
            result = session.run("MATCH ()-[r:HAS_CONCEPT]->() RETURN count(r) as cnt")
            has_concept = result.single()["cnt"]
            
            result = session.run("MATCH ()-[r:CONTAINS]->() RETURN count(r) as cnt")
            contains = result.single()["cnt"]
            
            # Phase 2C 엣지
            result = session.run("MATCH ()-[r:HAS_SUBCATEGORY]->() RETURN count(r) as cnt")
            has_subcat = result.single()["cnt"]
            
            result = session.run("MATCH ()-[r:DERIVED_FROM]->() RETURN count(r) as cnt")
            derived_from = result.single()["cnt"]
            
            result = session.run("MATCH ()-[r:RELATED_TO]->() RETURN count(r) as cnt")
            related_to = result.single()["cnt"]
            
            result = session.run("MATCH ()-[r:MAPS_TO]->() RETURN count(r) as cnt")
            maps_to = result.single()["cnt"]
            
            print(f"\nNodes:")
            print(f"  RowEntity:       {row_entities}")
            print(f"  ConceptCategory: {concepts}")
            print(f"  SubCategory:     {subcategories} (Phase 2C)")
            print(f"  Parameter:       {parameters}")
            print(f"  MedicalTerm:     {medical_terms} (Phase 2C)")
            
            print(f"\nEdges:")
            print(f"  LINKS_TO:        {links_to}")
            print(f"  HAS_CONCEPT:     {has_concept}")
            print(f"  HAS_SUBCATEGORY: {has_subcat} (Phase 2C)")
            print(f"  CONTAINS:        {contains}")
            print(f"  DERIVED_FROM:    {derived_from} (Phase 2C)")
            print(f"  RELATED_TO:      {related_to} (Phase 2C)")
            print(f"  MAPS_TO:         {maps_to} (Phase 2C)")
            
            # Sample Semantic Edges
            if derived_from > 0 or related_to > 0:
                print("\nSample Semantic Relationships:")
                result = session.run("""
                    MATCH (s:Parameter)-[r:DERIVED_FROM|RELATED_TO]->(t:Parameter)
                    RETURN s.key as source, type(r) as rel_type, t.key as target
                    LIMIT 5
                """)
                for record in result:
                    print(f"  - {record['source']} --[{record['rel_type']}]--> {record['target']}")
        
        driver.close()
        
    except Exception as e:
        print(f"\n⚠️ Neo4j connection failed: {e}")
        print("   (Neo4j may not be running or not configured)")


def main():
    """메인 테스트 함수"""
    print("="*80)
    print("🧪 Phase 2C Full Pipeline Test")
    print("="*80)
    
    # 1. DB 리셋
    reset_database()
    
    # 2. 파이프라인 실행
    final_state = run_phase2c_pipeline()
    
    if final_state:
        # 3. 결과 출력
        print_phase2c_summary(final_state)
        print_subcategories(final_state)
        print_semantic_edges(final_state)
        print_medical_terms(final_state)
        print_neo4j_enhanced_stats()
        
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

