#!/usr/bin/env python3
"""
Pipeline Test + Results Viewer (relationship_inference까지)

파이프라인 실행 후 DB 테이블 결과를 출력합니다.
현재 테스트는 relationship_inference(900)까지만 실행합니다.
ontology_enhancement(1000)는 제외되어 있습니다.

실행 Nodes (12-Node Pipeline - ontology_enhancement 제외):
- [directory_catalog]: 디렉토리 구조 분석, 파일명 샘플 수집 (Rule-based)
- [file_catalog]: 파일/컬럼 물리적 정보 수집 (Rule-based)
- [schema_aggregation]: 스키마 집계 (Rule-based)
- [file_grouping_prep]: 디렉토리별 파일 통계/패턴 관찰 (Rule-based) ✨ NEW
- [file_classification]: 파일을 metadata/data로 분류 (LLM)
- [file_grouping]: 파일 그룹화 전략 결정 및 그룹 생성 (LLM) ✨ NEW
- [column_classification]: 컬럼 역할 분류 + parameter 생성 (LLM)
- [metadata_semantic]: metadata 파일에서 data_dictionary 추출 (LLM)
- [parameter_semantic]: parameter 테이블 의미 분석 + dictionary 매칭 (LLM)
- [directory_pattern]: 디렉토리 파일명 패턴 분석 + ID 추출 (LLM)
- [entity_identification]: 테이블 Entity 식별 (row_represents, entity_identifier) (LLM)
- [relationship_inference]: 테이블 간 FK 관계 추론 + Neo4j 3-Level Ontology (LLM + Rule)

⏸️ [ontology_enhancement]: Ontology Enhancement (테스트에서 제외)

결과 DB Tables:
- directory_catalog: 디렉토리 메타데이터 + 파일명 패턴
- file_catalog: 파일 메타데이터 + filename_values + group_id
- file_group: 파일 그룹 정보 + entity 정보 ✨ NEW
- column_metadata: 컬럼 물리 정보 + column_role
- parameter: 파라미터 통합 관리 (Wide/Long format) + semantic 정보 + group_id
- data_dictionary: 파라미터 정의 (key, desc, unit)
- table_entities: 테이블 Entity 정보
- table_relationships: FK 관계

(ontology_enhancement 제외로 아래 테이블은 비어있음):
- ontology_subcategories: SubCategory 세분화
- semantic_edges: Parameter 간 의미 관계
- medical_term_mappings: SNOMED/LOINC 매핑
- cross_table_semantics: 테이블 간 시맨틱 관계
"""

import sys
import os

# 프로젝트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from pathlib import Path

# 데이터 경로 설정 (Open VitalDB만 테스트)
DATA_DIR = Path(__file__).parent / "data" / "raw" / "Open_VitalDB_1.0.0"


# =============================================================================
# Database Setup
# =============================================================================

def reset_database():
    """테스트 전 DB 초기화
    
    FK 참조 관계:
    - file_catalog.dir_id → directory_catalog.dir_id
    - file_catalog.group_id → file_group.group_id
    - parameter.group_id → file_group.group_id
    - table_entities.file_id → file_catalog.file_id
    - table_relationships.source_file_id/target_file_id → file_catalog.file_id
    - cross_table_semantics.source_file_id/target_file_id → file_catalog.file_id
    - data_dictionary.source_file_id → file_catalog.file_id
    
    순서:
    - 삭제: FK 참조하는 테이블 먼저 (Ontology → Dictionary → Catalog → FileGroup → Directory)
    - 생성: FK 참조되는 테이블 먼저 (Directory → FileGroup → Catalog → Dictionary → Ontology)
    """
    print("\n" + "="*80)
    print("🗑️  Resetting Database...")
    print("="*80)
    
    from src.database import (
        CatalogSchemaManager,
        DictionarySchemaManager,
        OntologySchemaManager,
        DirectorySchemaManager,
        ParameterSchemaManager,
    )
    from src.database.managers.file_group import FileGroupSchemaManager
    
    # 1. 삭제: FK 참조하는 테이블 먼저 삭제 (역순)
    try:
        ontology_manager = OntologySchemaManager()
        ontology_manager.drop_tables(confirm=True)
        print("✅ Ontology tables dropped")
    except Exception as e:
        print(f"⚠️  Error dropping ontology: {e}")
    
    try:
        param_manager = ParameterSchemaManager()
        param_manager.drop_tables(confirm=True)
        print("✅ Parameter tables dropped")
    except Exception as e:
        print(f"⚠️  Error dropping parameter: {e}")
    
    try:
        dict_manager = DictionarySchemaManager()
        dict_manager.drop_tables(confirm=True)
        print("✅ Dictionary tables dropped")
    except Exception as e:
        print(f"⚠️  Error dropping dictionary: {e}")
    
    try:
        catalog_manager = CatalogSchemaManager()
        catalog_manager.drop_tables(confirm=True)
        print("✅ Catalog tables dropped")
    except Exception as e:
        print(f"⚠️  Error dropping catalog: {e}")
    
    try:
        file_group_manager = FileGroupSchemaManager()
        file_group_manager.drop_tables(confirm=True)
        print("✅ FileGroup tables dropped")
    except Exception as e:
        print(f"⚠️  Error dropping file_group: {e}")
    
    try:
        directory_manager = DirectorySchemaManager()
        directory_manager.drop_tables(confirm=True)
        print("✅ Directory tables dropped")
    except Exception as e:
        print(f"⚠️  Error dropping directory: {e}")
    
    # 2. 생성: FK 참조되는 테이블 먼저 생성 (정순)
    try:
        directory_manager = DirectorySchemaManager()
        directory_manager.create_tables()
        print("✅ Directory tables created")
    except Exception as e:
        print(f"⚠️  Error creating directory: {e}")
    
    try:
        file_group_manager = FileGroupSchemaManager()
        file_group_manager.create_tables()
        print("✅ FileGroup tables created")
    except Exception as e:
        print(f"⚠️  Error creating file_group: {e}")
    
    try:
        catalog_manager = CatalogSchemaManager()
        catalog_manager.create_tables()
        print("✅ Catalog tables created")
    except Exception as e:
        print(f"⚠️  Error creating catalog: {e}")
    
    try:
        dict_manager = DictionarySchemaManager()
        dict_manager.create_tables()
        print("✅ Dictionary tables created")
    except Exception as e:
        print(f"⚠️  Error creating dictionary: {e}")
    
    try:
        param_manager = ParameterSchemaManager()
        param_manager.create_tables()
        print("✅ Parameter tables created")
    except Exception as e:
        print(f"⚠️  Error creating parameter: {e}")
    
    try:
        ontology_manager = OntologySchemaManager()
        ontology_manager.create_tables()
        print("✅ Ontology tables created")
    except Exception as e:
        print(f"⚠️  Error creating ontology: {e}")
    
    # 3. file_group FK 제약조건 추가 (모든 테이블 생성 후)
    # file_catalog와 parameter 테이블이 이제 존재하므로 FK 추가 가능
    try:
        from src.database.schemas.file_group import (
            ADD_FILE_CATALOG_GROUP_FK_SQL,
            ADD_PARAMETER_GROUP_FK_SQL,
        )
        from src.database.connection import get_db_manager
        
        db = get_db_manager()
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(ADD_FILE_CATALOG_GROUP_FK_SQL)
        cursor.execute(ADD_PARAMETER_GROUP_FK_SQL)
        
        conn.commit()
        print("✅ FileGroup FK constraints added")
    except Exception as e:
        print(f"⚠️  Error adding file_group FK: {e}")


# =============================================================================
# Pipeline Execution
# =============================================================================

def find_data_files() -> list:
    """Open VitalDB 데이터 파일 찾기 (CSV + Vital 파일)"""
    print(f"\n📂 Scanning: {DATA_DIR}")
    
    files = []
    
    if not DATA_DIR.exists():
        print(f"⚠️  Data directory not found: {DATA_DIR}")
        return files
    
    # CSV 파일 스캔
    for f in DATA_DIR.rglob("*.csv"):
        files.append(str(f))
        print(f"   Found: {f.name}")
    
    # Vital 파일 스캔 (생체신호 데이터) - 테스트용으로 5개만
    vital_files = list(DATA_DIR.rglob("*.vital"))[:5]
    for f in vital_files:
        files.append(str(f))
        print(f"   Found: {f.name} (signal)")
    
    print(f"\n📁 Total files found: {len(files)}")
    return files


def run_full_pipeline():
    """전체 파이프라인 실행 (relationship_inference까지만)"""
    print("\n" + "="*80)
    print("🚀 Running Pipeline (directory_catalog → relationship_inference)")
    print("   ℹ️  ontology_enhancement is excluded for testing")
    print("="*80)
    
    input_files = find_data_files()
    
    if not input_files:
        print("❌ No data files found!")
        return None
    
    from src.agents.graph import build_agent
    # ontology_enhancement (order 1000) 제외 - relationship_inference (900)까지만 테스트
    agent = build_agent(exclude_nodes=["ontology_enhancement"])
    
    initial_state = {
        # Input Directory
        "input_directory": str(DATA_DIR),
        
        # Dataset Context
        "current_dataset_id": "open_vitaldb_v1.0.0",
        "current_table_name": None,
        "data_catalog": {},
        
        # [directory_catalog] Result
        "directory_catalog_result": None,
        "catalog_dir_ids": [],
        
        # [file_catalog] Result
        "file_catalog_result": None,
        "catalog_file_ids": [],
        
        # [schema_aggregation] Result
        "schema_aggregation_result": None,
        "unique_columns": [],
        "unique_files": [],
        "column_batches": [],
        "file_batches": [],
        
        # [file_grouping_prep] Result ✨ NEW
        "grouping_prep_result": None,
        "directories_for_grouping": [],
        
        # [file_classification] Result
        "file_classification_result": None,
        "metadata_files": [],
        "data_files": [],
        
        # [file_grouping] Result ✨ NEW
        "file_grouping_result": None,
        "file_groups": [],
        
        # [column_classification] Result
        "column_classification_result": None,
        
        # [metadata_semantic] Result
        "metadata_semantic_result": None,
        "data_dictionary_entries": [],
        
        # [parameter_semantic] Result
        "parameter_semantic_result": None,
        
        # [directory_pattern] Result
        "directory_pattern_result": None,
        "directory_patterns": {},
        
        # [entity_identification] Result
        "entity_identification_result": None,
        "entity_result": None,
        "table_entity_results": [],
        "group_files_propagated": 0,
        
        # [relationship_inference] Result
        "relationship_inference_result": None,
        "table_relationships": [],
        
        # [ontology_enhancement] Result
        "ontology_enhancement_result": None,
        "ontology_subcategories": [],
        "semantic_edges": [],
        "medical_term_mappings": [],
        "cross_table_semantics": [],
        
        # Multi-Node Workflow Context
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
        "raw_metadata": {},
        
        # Semantic Analysis
        "entity_identification": None,
        "finalized_schema": [],
        "entity_understanding": None,
        
        # Human-in-the-Loop
        "needs_human_review": False,
        "human_question": "",
        "human_feedback": None,
        "review_type": None,
        "conversation_history": {
            "session_id": f"full_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "dataset_id": "open_vitaldb_v1.0.0",
            "started_at": datetime.now().isoformat(),
            "turns": [],
            "classification_decisions": [],
            "entity_decisions": [],
            "user_preferences": {},
        },
        
        # System
        "logs": [],
        "ontology_context": {},
        "skip_indexing": False,
        "retry_count": 0,
        "error_message": None,
        "project_context": {
            "master_entity_identifier": None,
            "known_aliases": [],
            "example_id_values": [],
        },
    }
    
    print("\n🏃 Starting pipeline execution...")
    start_time = datetime.now()
    
    try:
        final_state = agent.invoke(initial_state)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print("\n" + "="*80)
        print("✅ Pipeline Completed!")
        print(f"   Duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")
        print("="*80)
        
        return final_state
        
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# DB Table Viewers
# =============================================================================

def get_fresh_connection():
    """새로운 DB 커넥션 가져오기 (트랜잭션 격리)"""
    from src.database.connection import get_db_manager
    db = get_db_manager()
    conn = db.get_connection()
    try:
        conn.rollback()  # 기존 트랜잭션 정리
    except:
        pass
    return conn


def print_directory_catalog(limit: int = 10):
    """directory_catalog 테이블 출력 (directory_catalog / directory_pattern 결과)"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📂 TABLE: directory_catalog (directory_catalog + directory_pattern)")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM directory_catalog")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT dir_id, dir_name, dir_type, file_count, 
                   filename_pattern, pattern_confidence
            FROM directory_catalog
            ORDER BY file_count DESC
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        print(f"\n{'Dir ID':<12} {'Dir Name':<25} {'Type':<15} {'Files':<8} {'Pattern':<25} {'Conf.'}")
        print("-"*100)
        
        for row in rows:
            dir_id, dir_name, dir_type, file_count, pattern, confidence = row
            dir_id_short = str(dir_id)[:8] + "..."
            name_short = dir_name[:22] + "..." if len(dir_name) > 25 else dir_name
            type_short = (dir_type or '-')[:12]
            pattern_short = (pattern or '-')[:22] if pattern else '-'
            conf_str = f"{confidence:.2f}" if confidence else '-'
            
            print(f"{dir_id_short:<12} {name_short:<25} {type_short:<15} {file_count:<8} {pattern_short:<25} {conf_str}")
        
        print(f"\nTotal: {total} directories")
        
        # 패턴 분석 결과 상세
        cursor.execute("""
            SELECT dir_name, filename_pattern, filename_columns, pattern_reasoning
            FROM directory_catalog
            WHERE filename_pattern IS NOT NULL
        """)
        pattern_dirs = cursor.fetchall()
        
        if pattern_dirs:
            print("\n📋 Directories with Patterns (directory_pattern):")
            for dir_name, pattern, columns, reasoning in pattern_dirs:
                print(f"\n   📁 {dir_name}")
                print(f"      Pattern: {pattern}")
                print(f"      Columns: {columns}")
                if reasoning:
                    print(f"      Reasoning: {reasoning[:80]}...")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_file_catalog(limit: int = 10):
    """file_catalog 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📁 TABLE: file_catalog")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM file_catalog")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT fc.file_id, fc.file_name, fc.processor_type, fc.is_metadata, 
                   dc.dir_name, fc.group_id, fc.filename_values
            FROM file_catalog fc
            LEFT JOIN directory_catalog dc ON fc.dir_id = dc.dir_id
            ORDER BY fc.file_name
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        print(f"\n{'File ID':<12} {'File Name':<25} {'Proc.':<8} {'Meta?':<5} {'Directory':<15} {'Group':<10} {'Values'}")
        print("-"*100)
        
        for row in rows:
            file_id, file_name, processor_type, is_meta, dir_name, group_id, filename_values = row
            file_id_short = str(file_id)[:8] + "..."
            name_short = file_name[:22] + "..." if len(file_name) > 25 else file_name
            is_meta_str = "✓" if is_meta else "-"
            dir_short = (dir_name or '-')[:12] + "..." if dir_name and len(dir_name) > 15 else (dir_name or '-')
            group_short = str(group_id)[:8] + "." if group_id else "-"
            values_str = str(filename_values)[:12] if filename_values and filename_values != {} else '-'
            
            print(f"{file_id_short:<12} {name_short:<25} {processor_type or '-':<8} {is_meta_str:<5} {dir_short:<15} {group_short:<10} {values_str}")
        
        print(f"\nTotal: {total} files")
        
        # filename_values 통계
        cursor.execute("""
            SELECT COUNT(*) FROM file_catalog 
            WHERE filename_values IS NOT NULL AND filename_values != '{}'::jsonb
        """)
        files_with_values = cursor.fetchone()[0]
        print(f"Files with filename_values: {files_with_values}")
        
        # group_id 통계
        cursor.execute("""
            SELECT COUNT(*) FROM file_catalog 
            WHERE group_id IS NOT NULL
        """)
        files_with_group = cursor.fetchone()[0]
        print(f"Files with group_id: {files_with_group}")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_file_group(limit: int = 10):
    """file_group 테이블 출력 ✨ NEW"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📦 TABLE: file_group (파일 그룹핑)")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM file_group")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT group_id, group_name, file_count, status, 
                   row_represents, entity_identifier_source, entity_identifier_key,
                   confidence, grouping_criteria
            FROM file_group
            ORDER BY file_count DESC
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        if not rows:
            print("\n(No file groups found)")
        else:
            print(f"\n{'Group ID':<12} {'Group Name':<25} {'Files':<6} {'Status':<12} {'Row Represents':<25} {'Entity Key':<12} {'Conf.'}")
            print("-"*110)
            
            for row in rows:
                group_id, group_name, file_count, status, row_rep, entity_src, entity_key, conf, criteria = row
                group_id_short = str(group_id)[:8] + "..."
                name_short = group_name[:22] + "..." if len(group_name) > 25 else group_name
                row_rep_short = (row_rep or '-')[:22] if row_rep else '-'
                entity_key_short = (entity_key or '-')[:10]
                conf_str = f"{conf:.2f}" if conf else '-'
                
                print(f"{group_id_short:<12} {name_short:<25} {file_count:<6} {status or '-':<12} {row_rep_short:<25} {entity_key_short:<12} {conf_str}")
        
        print(f"\nTotal: {total} groups")
        
        # 상세 정보 (grouping_criteria)
        if rows:
            print("\n📋 Group Details:")
            cursor.execute("""
                SELECT group_name, grouping_criteria, reasoning
                FROM file_group
                LIMIT 3
            """)
            for group_name, criteria, reasoning in cursor.fetchall():
                print(f"\n   📦 {group_name}")
                if criteria:
                    import json
                    print(f"      Criteria: {json.dumps(criteria, ensure_ascii=False)[:80]}...")
                if reasoning:
                    print(f"      Reasoning: {reasoning[:80]}...")
        
        # status 통계
        cursor.execute("""
            SELECT status, COUNT(*) 
            FROM file_group 
            GROUP BY status
        """)
        stats = cursor.fetchall()
        print("\nGroup Status Distribution:")
        for status, cnt in stats:
            print(f"   {status or 'null'}: {cnt}")
        
        # needs_human_review 통계 (status 기반)
        cursor.execute("""
            SELECT COUNT(*) FROM file_group 
            WHERE status = 'needs_human_review'
        """)
        needs_review = cursor.fetchone()[0]
        if needs_review > 0:
            print(f"\n⚠️ Groups needing human review: {needs_review}")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_column_metadata(limit: int = 20):
    """column_metadata 테이블 출력 (물리 정보 + column_role)"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📊 TABLE: column_metadata (물리 정보 + column_role)")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM column_metadata")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT fc.file_name, cm.original_name, cm.column_type,
                   cm.data_type, cm.column_role
            FROM column_metadata cm
            JOIN file_catalog fc ON cm.file_id = fc.file_id
            ORDER BY fc.file_name, cm.col_id
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        print(f"\n{'File':<25} {'Column':<18} {'Column Type':<15} {'Data Type':<12} {'Role'}")
        print("-"*90)
        
        for row in rows:
            file_name, orig, col_type, data_type, col_role = row
            file_short = file_name[:22] + "..." if len(file_name) > 25 else file_name
            orig_short = (orig or '-')[:15]
            col_type_short = (col_type or '-')[:12]
            data_type_short = (data_type or '-')[:10]
            role_short = (col_role or '-')[:15]
            
            print(f"{file_short:<25} {orig_short:<18} {col_type_short:<15} {data_type_short:<12} {role_short}")
        
        print(f"\nTotal: {total} columns")
        
        # column_role 통계
        cursor.execute("""
            SELECT column_role, COUNT(*) 
            FROM column_metadata 
            GROUP BY column_role
            ORDER BY COUNT(*) DESC
        """)
        stats = cursor.fetchall()
        print("\nColumn Role Distribution:")
        for role, cnt in stats:
            print(f"   {role or 'null'}: {cnt}")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_parameter(limit: int = 20):
    """parameter 테이블 출력 (semantic 정보)"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("🏷️  TABLE: parameter (Wide/Long format 통합 + semantic)")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM parameter")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT 
                COALESCE(fc.file_name, fg.group_name) as source_name,
                p.param_key, p.source_type, 
                p.semantic_name, p.concept_category, p.unit, 
                p.dict_match_status,
                CASE WHEN p.group_id IS NOT NULL THEN 'group' ELSE 'file' END as param_scope
            FROM parameter p
            LEFT JOIN file_catalog fc ON p.file_id = fc.file_id
            LEFT JOIN file_group fg ON p.group_id = fg.group_id
            ORDER BY source_name, p.param_id
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        print(f"\n{'Source':<20} {'Param Key':<15} {'Src Type':<12} {'Semantic':<15} {'Category':<12} {'Unit':<6} {'Match':<8} {'Scope'}")
        print("-"*110)
        
        for row in rows:
            source_name, param_key, source_type, semantic, category, unit, match_status, scope = row
            source_short = (source_name or '-')[:17] + "..." if source_name and len(source_name) > 20 else (source_name or '-')
            key_short = (param_key or '-')[:12]
            source_short_type = (source_type or '-')[:10]
            semantic_short = (semantic or '-')[:12]
            category_short = (category or '-')[:10]
            unit_short = (unit or '-')[:4]
            match_short = (match_status or '-')[:6]
            
            print(f"{source_short:<20} {key_short:<15} {source_short_type:<12} {semantic_short:<15} {category_short:<12} {unit_short:<6} {match_short:<8} {scope}")
        
        print(f"\nTotal: {total} parameters")
        
        # source_type 통계
        cursor.execute("""
            SELECT source_type, COUNT(*) 
            FROM parameter 
            GROUP BY source_type
        """)
        stats = cursor.fetchall()
        print("\nSource Type Distribution:")
        for stype, cnt in stats:
            print(f"   {stype or 'null'}: {cnt}")
        
        # file vs group 통계
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN file_id IS NOT NULL AND group_id IS NULL THEN 1 ELSE 0 END) as file_params,
                SUM(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) as group_params
            FROM parameter
        """)
        file_params, group_params = cursor.fetchone()
        print(f"\nParameter Scope:")
        print(f"   File-level: {file_params or 0}")
        print(f"   Group-level: {group_params or 0}")
        
        # match_status 통계
        cursor.execute("""
            SELECT dict_match_status, COUNT(*) 
            FROM parameter 
            GROUP BY dict_match_status
        """)
        stats = cursor.fetchall()
        print("\nMatch Status Distribution:")
        for status, cnt in stats:
            print(f"   {status or 'null'}: {cnt}")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_data_dictionary(limit: int = 20):
    """data_dictionary 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📖 TABLE: data_dictionary")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM data_dictionary")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT source_file_name, parameter_key, parameter_desc, parameter_unit
            FROM data_dictionary
            ORDER BY source_file_name, parameter_key
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        print(f"\n{'Source File':<25} {'Key':<20} {'Description':<35} {'Unit'}")
        print("-"*95)
        
        for row in rows:
            source, key, desc, unit = row
            source_short = (source or '-')[:22]
            key_short = (key or '-')[:17]
            desc_short = (desc or '-')[:32] + "..." if desc and len(desc) > 35 else (desc or '-')
            
            print(f"{source_short:<25} {key_short:<20} {desc_short:<35} {unit or '-'}")
        
        print(f"\nTotal: {total} entries")
        
        # 파일별 통계
        cursor.execute("""
            SELECT source_file_name, COUNT(*) 
            FROM data_dictionary 
            GROUP BY source_file_name
        """)
        stats = cursor.fetchall()
        print("\nEntries by Source File:")
        for fname, cnt in stats:
            print(f"   {fname}: {cnt}")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_table_entities(limit: int = 10):
    """table_entities 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("🏷️  TABLE: table_entities")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM table_entities")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT fc.file_name, te.row_represents, te.entity_identifier, 
                   te.confidence, fc.group_id
            FROM table_entities te
            JOIN file_catalog fc ON te.file_id = fc.file_id
            ORDER BY te.confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        print(f"\n{'File':<30} {'Row Represents':<25} {'Identifier':<12} {'Conf.':<6} {'Grouped?'}")
        print("-"*85)
        
        for row in rows:
            file_name, row_rep, identifier, conf, group_id = row
            file_short = file_name[:27] + "..." if len(file_name) > 30 else file_name
            grouped = "✓" if group_id else "-"
            
            print(f"{file_short:<30} {row_rep or '-':<25} {identifier or '(none)':<12} {conf:.2f}  {grouped}")
        
        print(f"\nTotal: {total} entities")
        
        # 그룹화된 파일 통계
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN fc.group_id IS NOT NULL THEN 1 END) as grouped
            FROM table_entities te
            JOIN file_catalog fc ON te.file_id = fc.file_id
        """)
        total_entities, grouped_entities = cursor.fetchone()
        print(f"Entities from grouped files: {grouped_entities or 0}/{total_entities or 0}")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_table_relationships(limit: int = 10):
    """table_relationships 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("🔗 TABLE: table_relationships")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM table_relationships")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT fc1.file_name, fc2.file_name, tr.source_column, 
                   tr.target_column, tr.cardinality, tr.confidence
            FROM table_relationships tr
            JOIN file_catalog fc1 ON tr.source_file_id = fc1.file_id
            JOIN file_catalog fc2 ON tr.target_file_id = fc2.file_id
            ORDER BY tr.confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        if not rows:
            print("\n(No relationships found)")
        else:
            print(f"\n{'Source':<25} {'Target':<25} {'Columns':<25} {'Card.':<6} {'Conf.'}")
            print("-"*90)
            
            for row in rows:
                src, tgt, src_col, tgt_col, card, conf = row
                src_short = src[:22] + "..." if len(src) > 25 else src
                tgt_short = tgt[:22] + "..." if len(tgt) > 25 else tgt
                col_str = f"{src_col}→{tgt_col}"[:22]
                
                print(f"{src_short:<25} {tgt_short:<25} {col_str:<25} {card:<6} {conf:.2f}")
        
        print(f"\nTotal: {total} relationships")
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_ontology_subcategories(limit: int = 15):
    """ontology_subcategories 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📂 TABLE: ontology_subcategories (ontology_enhancement)")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM ontology_subcategories")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT parent_category, subcategory_name, confidence, reasoning
            FROM ontology_subcategories
            ORDER BY parent_category, subcategory_name
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        if not rows:
            print("\n(No subcategories found)")
        else:
            print(f"\n{'Parent Category':<25} {'Subcategory':<30} {'Conf.'}")
            print("-"*65)
            
            for row in rows:
                parent, subcat, conf, reasoning = row
                parent_short = parent[:22] if parent else '-'
                subcat_short = subcat[:27] if subcat else '-'
                
                print(f"{parent_short:<25} {subcat_short:<30} {conf:.2f}")
        
        print(f"\nTotal: {total} subcategories")
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_semantic_edges(limit: int = 20):
    """semantic_edges 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("🔗 TABLE: semantic_edges (ontology_enhancement)")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM semantic_edges")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT source_parameter, target_parameter, relationship_type, confidence
            FROM semantic_edges
            ORDER BY relationship_type, confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        if not rows:
            print("\n(No semantic edges found)")
        else:
            print(f"\n{'Source':<20} {'Relation':<15} {'Target':<20} {'Conf.'}")
            print("-"*65)
            
            for row in rows:
                src, tgt, rel_type, conf = row
                src_short = (src or '-')[:17]
                tgt_short = (tgt or '-')[:17]
                rel_short = (rel_type or '-')[:12]
                
                print(f"{src_short:<20} {rel_short:<15} {tgt_short:<20} {conf:.2f}")
        
        print(f"\nTotal: {total} edges")
        
        # 타입별 통계
        cursor.execute("""
            SELECT relationship_type, COUNT(*) 
            FROM semantic_edges 
            GROUP BY relationship_type
        """)
        stats = cursor.fetchall()
        print("\nEdges by Type:")
        for rel_type, cnt in stats:
            print(f"   {rel_type}: {cnt}")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_medical_term_mappings(limit: int = 20):
    """medical_term_mappings 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("🏥 TABLE: medical_term_mappings (ontology_enhancement)")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM medical_term_mappings")
        total = cursor.fetchone()[0]
        
        # SNOMED 또는 LOINC가 있는 것만 표시
        cursor.execute("""
            SELECT parameter_key, snomed_code, snomed_name, loinc_code, loinc_name, confidence
            FROM medical_term_mappings
            WHERE snomed_code IS NOT NULL OR loinc_code IS NOT NULL
            ORDER BY confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        if not rows:
            print("\n(No medical term mappings found)")
        else:
            print(f"\n{'Parameter':<15} {'SNOMED Code':<15} {'SNOMED Name':<25} {'LOINC':<12} {'Conf.'}")
            print("-"*80)
            
            for row in rows:
                param, snomed_code, snomed_name, loinc_code, loinc_name, conf = row
                param_short = (param or '-')[:12]
                snomed_code_short = (snomed_code or '-')[:12]
                snomed_name_short = (snomed_name or '-')[:22]
                loinc_short = (loinc_code or '-')[:10]
                
                print(f"{param_short:<15} {snomed_code_short:<15} {snomed_name_short:<25} {loinc_short:<12} {conf:.2f}")
        
        print(f"\nTotal: {total} mappings")
        
        # 통계
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(snomed_code) as snomed_count,
                COUNT(loinc_code) as loinc_count
            FROM medical_term_mappings
        """)
        stats = cursor.fetchone()
        if stats[0] > 0:
            print(f"\nMapping Coverage:")
            print(f"   Total parameters: {stats[0]}")
            print(f"   With SNOMED: {stats[1]} ({stats[1]/stats[0]*100:.1f}%)")
            print(f"   With LOINC: {stats[2]} ({stats[2]/stats[0]*100:.1f}%)")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_cross_table_semantics(limit: int = 10):
    """cross_table_semantics 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("🔄 TABLE: cross_table_semantics (ontology_enhancement)")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM cross_table_semantics")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT fc1.file_name, cts.source_column, fc2.file_name, 
                   cts.target_column, cts.relationship_type, cts.confidence
            FROM cross_table_semantics cts
            JOIN file_catalog fc1 ON cts.source_file_id = fc1.file_id
            JOIN file_catalog fc2 ON cts.target_file_id = fc2.file_id
            ORDER BY cts.confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        if not rows:
            print("\n(No cross-table semantics found)")
        else:
            print(f"\n{'Source Table':<22} {'Source Col':<15} {'Target Table':<22} {'Target Col':<15} {'Conf.'}")
            print("-"*85)
            
            for row in rows:
                src_file, src_col, tgt_file, tgt_col, rel_type, conf = row
                src_file_short = src_file[:19] + "..." if len(src_file) > 22 else src_file
                tgt_file_short = tgt_file[:19] + "..." if len(tgt_file) > 22 else tgt_file
                
                print(f"{src_file_short:<22} {src_col[:12]:<15} {tgt_file_short:<22} {tgt_col[:12]:<15} {conf:.2f}")
        
        print(f"\nTotal: {total} cross-table semantics")
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_neo4j_stats():
    """Neo4j 그래프 통계 출력"""
    try:
        from neo4j import GraphDatabase
        from src.config import Neo4jConfig
        
        driver = GraphDatabase.driver(
            Neo4jConfig.URI,
            auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
        )
        driver.verify_connectivity()
        
        print("\n" + "="*80)
        print("📊 Neo4j Knowledge Graph")
        print("="*80)
        
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            # 노드 카운트
            node_types = ['RowEntity', 'FileGroup', 'ConceptCategory', 'SubCategory', 'Parameter', 'MedicalTerm']
            print("\n🔵 Nodes:")
            for node_type in node_types:
                result = session.run(f"MATCH (n:{node_type}) RETURN count(n) as cnt")
                cnt = result.single()["cnt"]
                phase = " (ontology_enhancement)" if node_type in ['SubCategory', 'MedicalTerm'] else ""
                print(f"   {node_type:<18} {cnt:>5}{phase}")
            
            # 관계 카운트
            rel_types = ['LINKS_TO', 'HAS_CONCEPT', 'HAS_SUBCATEGORY', 'CONTAINS', 
                        'HAS_COLUMN', 'CONTAINS_FILE', 'HAS_COMMON_PARAM',
                        'DERIVED_FROM', 'RELATED_TO', 'MAPS_TO']
            print("\n🔗 Relationships:")
            for rel_type in rel_types:
                result = session.run(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) as cnt")
                cnt = result.single()["cnt"]
                phase = " (ontology_enhancement)" if rel_type in ['HAS_SUBCATEGORY', 'DERIVED_FROM', 'RELATED_TO', 'MAPS_TO'] else ""
                print(f"   {rel_type:<18} {cnt:>5}{phase}")
            
            # Sample data
            print("\n📋 Sample RowEntities:")
            result = session.run("""
                MATCH (e:RowEntity)
                RETURN e.file_name as file, e.name as entity, e.identifier_column as id_col
            """)
            for record in result:
                id_col = record['id_col'] or '(none)'
                print(f"   - {record['file']}: {record['entity']} (id: {id_col})")
            
            print("\n📋 Sample LINKS_TO:")
            result = session.run("""
                MATCH (s:RowEntity)-[r:LINKS_TO]->(t:RowEntity)
                RETURN s.file_name as src, t.file_name as tgt, r.source_column as col, r.cardinality as card
                LIMIT 5
            """)
            for record in result:
                print(f"   - {record['src']} → {record['tgt']} ({record['col']}, {record['card']})")
            
            # FileGroup 정보
            print("\n📋 Sample FileGroups:")
            result = session.run("""
                MATCH (fg:FileGroup)
                OPTIONAL MATCH (fg)-[:CONTAINS_FILE]->(r:RowEntity)
                OPTIONAL MATCH (fg)-[:HAS_COMMON_PARAM]->(p:Parameter)
                WITH fg, count(DISTINCT r) as file_cnt, count(DISTINCT p) as param_cnt
                RETURN fg.name as name, fg.file_count as declared_cnt, file_cnt, param_cnt
            """)
            for record in result:
                print(f"   - {record['name']}: {record['file_cnt']} files, {record['param_cnt']} common params")
            
            # Identifier 파라미터
            print("\n📋 Identifier Parameters:")
            result = session.run("""
                MATCH (p:Parameter)
                WHERE p.is_identifier = true
                RETURN p.key as key, p.concept as concept
                LIMIT 5
            """)
            id_params = list(result)
            if id_params:
                for record in id_params:
                    print(f"   - {record['key']} ({record['concept']})")
            else:
                print("   (No identifier parameters found)")
        
        driver.close()
        
    except Exception as e:
        print(f"\n⚠️ Neo4j connection failed: {e}")


def print_summary_stats():
    """전체 요약 통계"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📈 Summary Statistics")
    print("="*80)
    
    stats = {}
    
    tables = [
        ('directory_catalog', 'Directories (directory_catalog)'),
        ('file_catalog', 'Files'),
        ('file_group', 'File Groups ✨'),
        ('column_metadata', 'Columns (physical + role)'),
        ('parameter', 'Parameters (semantic)'),
        ('data_dictionary', 'Dictionary Entries'),
        ('table_entities', 'Table Entities'),
        ('table_relationships', 'FK Relationships'),
        ('ontology_subcategories', 'Subcategories'),
        ('semantic_edges', 'Semantic Edges'),
        ('medical_term_mappings', 'Medical Mappings'),
        ('cross_table_semantics', 'Cross-table Semantics'),
    ]
    
    print(f"\n{'Table':<35} {'Count':>10}")
    print("-"*50)
    
    for table_name, display_name in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            stats[table_name] = count
            print(f"{display_name:<35} {count:>10}")
        except Exception as e:
            conn.rollback()  # 에러 후 트랜잭션 정리
            print(f"{display_name:<35} {'ERROR':>10}")
    
    # file_group 관련 통계
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM file_group 
            WHERE status = 'confirmed'
        """)
        confirmed_groups = cursor.fetchone()[0]
        print(f"\n{'Confirmed Groups':<35} {confirmed_groups:>10}")
        
        cursor.execute("""
            SELECT COUNT(*) FROM file_catalog 
            WHERE group_id IS NOT NULL
        """)
        grouped_files = cursor.fetchone()[0]
        print(f"{'Files in Groups':<35} {grouped_files:>10}")
        
        cursor.execute("""
            SELECT COUNT(*) FROM parameter 
            WHERE group_id IS NOT NULL
        """)
        group_params = cursor.fetchone()[0]
        print(f"{'Group-level Parameters':<35} {group_params:>10}")
    except Exception as e:
        conn.rollback()
    
    # directory_pattern 패턴 분석 통계
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM directory_catalog 
            WHERE filename_pattern IS NOT NULL
        """)
        patterns_count = cursor.fetchone()[0]
        print(f"\n{'Directories with Patterns':<35} {patterns_count:>10}")
        
        cursor.execute("""
            SELECT COUNT(*) FROM file_catalog 
            WHERE filename_values IS NOT NULL AND filename_values != '{}'::jsonb
        """)
        files_with_values = cursor.fetchone()[0]
        print(f"{'Files with filename_values':<35} {files_with_values:>10}")
    except Exception as e:
        conn.rollback()
    
    try:
        conn.commit()
    except:
        pass
    
    return stats


# =============================================================================
# Main
# =============================================================================

def main():
    """메인 함수"""
    print("="*80)
    print("🧪 Pipeline Test + Results Viewer (relationship_inference까지)")
    print("="*80)
    print(f"   Dataset: Open VitalDB")
    print(f"   Mode: Testing up to relationship_inference (ontology_enhancement excluded)")
    print(f"   Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. DB 리셋
    reset_database()
    
    # 2. 파이프라인 실행
    final_state = run_full_pipeline()
    
    if not final_state:
        print("\n❌ Pipeline failed. Cannot show results.")
        return
    
    # 3. DB 테이블 출력 (각 최대 20개)
    print("\n" + "="*80)
    print("📋 DATABASE TABLES AFTER PIPELINE (max 20 rows each)")
    print("="*80)
    
    print_summary_stats()
    print_directory_catalog(limit=20)  # directory_catalog / directory_pattern
    print_file_catalog(limit=20)
    print_file_group(limit=20)  # ✨ NEW
    print_column_metadata(limit=20)   # 물리 정보 + column_role
    print_parameter(limit=20)          # semantic 정보
    print_data_dictionary(limit=20)
    print_table_entities(limit=20)
    print_table_relationships(limit=20)
    
    # ontology_enhancement 결과 테이블 (제외되었으므로 비어있음)
    # 스킵하거나 참고용으로 표시만 함
    print("\n" + "="*80)
    print("ℹ️  ontology_enhancement 테이블들 (제외되어 비어있음)")
    print("="*80)
    print_ontology_subcategories(limit=5)
    print_semantic_edges(limit=5)
    print_medical_term_mappings(limit=5)
    print_cross_table_semantics(limit=5)
    
    print_neo4j_stats()
    
    print("\n" + "="*80)
    print("✅ All Results Displayed!")
    print("="*80)


if __name__ == "__main__":
    main()
