#!/usr/bin/env python3
"""
Debug Test Script for Indexing Pipeline
========================================

각 노드 실행 시 다음을 확인할 수 있습니다:
1. 각 노드 실행 전후 DB 상태
2. LLM 호출의 input(prompt)과 output(response)
3. Neo4j 그래프 생성 내역
4. 상태(state) 변화

사용법:
    # 전체 파이프라인 디버그
    python test_debug_pipeline.py
    
    # 특정 노드까지만 실행
    python test_debug_pipeline.py --until file_classification
    
    # 특정 노드만 디버그
    python test_debug_pipeline.py --only data_semantic
"""

import sys
import os
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import traceback

# 프로젝트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# =============================================================================
# Global Debug Storage
# =============================================================================

class DebugStorage:
    """디버그 정보 저장소"""
    def __init__(self):
        self.llm_calls: List[Dict] = []
        self.db_snapshots: Dict[str, Dict] = {}
        self.node_results: Dict[str, Any] = {}
        self.errors: List[Dict] = []
    
    def print_summary(self):
        """최종 요약 출력"""
        print("\n" + "="*80)
        print("📊 FINAL DEBUG SUMMARY")
        print("="*80)
        
        # LLM 호출 요약
        print(f"\n🤖 LLM Calls: {len(self.llm_calls)}")
        if self.llm_calls:
            total_prompt_chars = sum(c.get('prompt_length', 0) for c in self.llm_calls)
            print(f"   Total prompt chars: {total_prompt_chars:,}")
            for i, call in enumerate(self.llm_calls, 1):
                success = "✅" if call.get('success') else "❌"
                print(f"   #{i}: {success} {call.get('prompt_length', 0):,} chars → {call.get('method')}")
        
        # 노드 결과 요약
        print(f"\n📋 Node Results:")
        for node_name, result in self.node_results.items():
            duration = result.get('duration_seconds', 0)
            keys = len(result.get('updated_keys', []))
            print(f"   {node_name}: {duration:.2f}s, {keys} keys updated")
        
        # 에러 요약
        if self.errors:
            print(f"\n❌ Errors ({len(self.errors)}):")
            for err in self.errors:
                print(f"   - {err.get('node')}: {err.get('error')[:80]}...")


# Global instance
DEBUG_STORAGE = DebugStorage()


# =============================================================================
# LLM Call Logger (Monkey Patching)
# =============================================================================

def patch_llm_client():
    """LLM 클라이언트를 패치하여 모든 호출을 로깅"""
    from shared import llm as llm_client
    
    original_ask_json = None
    original_ask_text = None
    
    # OpenAIClient 패치
    if hasattr(llm_client, 'OpenAIClient'):
        original_ask_json = llm_client.OpenAIClient.ask_json
        original_ask_text = llm_client.OpenAIClient.ask_text
        
        def logged_ask_json(self, prompt: str, max_tokens: int = None):
            call_info = {
                "timestamp": datetime.now().isoformat(),
                "method": "ask_json",
                "model": self.model,
                "max_tokens": max_tokens,
                "prompt": prompt,
                "prompt_length": len(prompt),
            }
            
            try:
                response = original_ask_json(self, prompt, max_tokens)
                call_info["response"] = response
                call_info["success"] = True
            except Exception as e:
                call_info["error"] = str(e)
                call_info["success"] = False
                raise
            finally:
                DEBUG_STORAGE.llm_calls.append(call_info)
                
                # LLM 호출 내용 출력
                print(f"\n{'='*80}")
                print(f"🤖 LLM CALL #{len(DEBUG_STORAGE.llm_calls)}")
                print(f"{'='*80}")
                print(f"📤 PROMPT ({len(prompt):,} chars):")
                print("-"*80)
                print(prompt)
                print("-"*80)
                
                if call_info.get("success"):
                    print(f"\n📥 RESPONSE:")
                    print("-"*80)
                    response_str = json.dumps(call_info["response"], indent=2, ensure_ascii=False)
                    print(response_str)
                    print("-"*80)
                else:
                    print(f"\n❌ ERROR: {call_info.get('error')}")
                print(f"{'='*80}\n")
            
            return response
        
        def logged_ask_text(self, prompt: str, max_tokens: int = None):
            call_info = {
                "timestamp": datetime.now().isoformat(),
                "method": "ask_text",
                "model": self.model,
                "max_tokens": max_tokens,
                "prompt": prompt,
                "prompt_length": len(prompt),
            }
            
            try:
                response = original_ask_text(self, prompt, max_tokens)
                call_info["response"] = response
                call_info["success"] = True
            except Exception as e:
                call_info["error"] = str(e)
                call_info["success"] = False
                raise
            finally:
                DEBUG_STORAGE.llm_calls.append(call_info)
                
                # LLM 호출 내용 출력
                print(f"\n{'='*80}")
                print(f"🤖 LLM CALL #{len(DEBUG_STORAGE.llm_calls)} (text)")
                print(f"{'='*80}")
                print(f"📤 PROMPT ({len(prompt):,} chars):")
                print("-"*80)
                print(prompt)
                print("-"*80)
                
                if call_info.get("success"):
                    print(f"\n📥 RESPONSE:")
                    print("-"*80)
                    print(call_info["response"])
                    print("-"*80)
                else:
                    print(f"\n❌ ERROR: {call_info.get('error')}")
                print(f"{'='*80}\n")
            
            return response
        
        llm_client.OpenAIClient.ask_json = logged_ask_json
        llm_client.OpenAIClient.ask_text = logged_ask_text
        print("✅ LLM client patched for logging")


# =============================================================================
# DB Snapshot
# =============================================================================

def get_db_snapshot() -> Dict[str, Any]:
    """현재 DB 상태의 스냅샷을 가져옴"""
    from src.database import get_db_manager
    
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "tables": {}
    }
    
    tables_info = [
        ("directory_catalog", ["dir_id", "dir_name", "dir_type", "file_count", "filename_pattern"]),
        ("file_catalog", ["file_id", "file_name", "processor_type", "is_metadata", "filename_values"]),
        ("column_metadata", ["col_id", "file_id", "original_name", "column_role", "data_type"]),
        ("parameter", ["param_id", "file_id", "param_key", "source_type", "semantic_name", "unit"]),
        ("data_dictionary", ["entry_id", "parameter_key", "parameter_desc", "parameter_unit"]),
        ("table_entities", ["entity_id", "file_id", "row_represents", "entity_identifier", "confidence"]),
        ("table_relationships", ["rel_id", "source_file_id", "target_file_id", "source_column", "target_column", "cardinality"]),
        ("ontology_subcategories", ["id", "parent_category", "subcategory_name"]),
        ("semantic_edges", ["id", "source_parameter", "target_parameter", "relationship_type"]),
        ("medical_term_mappings", ["id", "parameter_key", "snomed_code", "loinc_code"]),
        ("cross_table_semantics", ["id", "source_file_id", "target_file_id", "source_column", "target_column"]),
    ]
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    for table_name, columns in tables_info:
        try:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                )
            """, (table_name,))
            exists = cursor.fetchone()[0]
            
            if not exists:
                snapshot["tables"][table_name] = {"exists": False, "count": 0, "sample": []}
                continue
            
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            
            cols_str = ", ".join(columns)
            cursor.execute(f"SELECT {cols_str} FROM {table_name} LIMIT 5")
            rows = cursor.fetchall()
            
            sample = []
            for row in rows:
                sample.append(dict(zip(columns, row)))
            
            snapshot["tables"][table_name] = {
                "exists": True,
                "count": count,
                "sample": sample
            }
            
        except Exception as e:
            conn.rollback()
            snapshot["tables"][table_name] = {
                "exists": "unknown",
                "error": str(e)
            }
    
    try:
        conn.commit()
    except:
        conn.rollback()
    
    return snapshot


def get_neo4j_snapshot() -> Dict[str, Any]:
    """Neo4j 상태의 스냅샷을 가져옴"""
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "nodes": {},
        "relationships": {},
        "connected": False
    }
    
    try:
        from neo4j import GraphDatabase
        from src.config import Neo4jConfig
        
        driver = GraphDatabase.driver(
            Neo4jConfig.URI,
            auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
        )
        driver.verify_connectivity()
        snapshot["connected"] = True
        
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            node_types = ['RowEntity', 'ConceptCategory', 'SubCategory', 'Parameter', 'MedicalTerm']
            for node_type in node_types:
                result = session.run(f"MATCH (n:{node_type}) RETURN count(n) as cnt")
                snapshot["nodes"][node_type] = result.single()["cnt"]
            
            rel_types = ['LINKS_TO', 'HAS_CONCEPT', 'HAS_SUBCATEGORY', 'CONTAINS', 
                        'HAS_COLUMN', 'DERIVED_FROM', 'RELATED_TO', 'MAPS_TO', 'FILENAME_VALUE']
            for rel_type in rel_types:
                result = session.run(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) as cnt")
                snapshot["relationships"][rel_type] = result.single()["cnt"]
        
        driver.close()
        
    except Exception as e:
        snapshot["error"] = str(e)
    
    return snapshot


def print_db_snapshot(snapshot: Dict, title: str = "DB Snapshot"):
    """DB 스냅샷 출력"""
    print(f"\n📊 {title}")
    print("-"*60)
    for table_name, info in snapshot.get("tables", {}).items():
        if info.get("exists"):
            count = info.get("count", 0)
            if count > 0:
                print(f"   {table_name}: {count} rows")
                # 샘플 출력
                for sample in info.get("sample", [])[:2]:
                    sample_str = ", ".join(f"{k}={str(v)[:20]}" for k, v in list(sample.items())[:3])
                    print(f"      └ {sample_str}")


def print_neo4j_snapshot(snapshot: Dict, title: str = "Neo4j Snapshot"):
    """Neo4j 스냅샷 출력"""
    if not snapshot.get("connected"):
        print(f"\n📊 {title}: (not connected)")
        return
    
    print(f"\n📊 {title}")
    print("-"*60)
    
    print("   Nodes:")
    for node_type, count in snapshot.get("nodes", {}).items():
        if count > 0:
            print(f"      {node_type}: {count}")
    
    print("   Relationships:")
    for rel_type, count in snapshot.get("relationships", {}).items():
        if count > 0:
            print(f"      {rel_type}: {count}")


# =============================================================================
# Debug Node Runner
# =============================================================================

def run_node_with_debug(node_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """노드를 디버그 모드로 실행"""
    from src.agents.registry import get_registry
    
    registry = get_registry()
    node = registry.get_node(node_name)
    
    if not node:
        print(f"❌ Node not found: {node_name}")
        return state
    
    print(f"\n{'#'*80}")
    print(f"# NODE: {node_name} (order: {node.order})")
    print(f"# Description: {node.description}")
    print(f"# Requires LLM: {'🤖 Yes' if node.requires_llm else '📏 No (Rule-based)'}")
    print(f"{'#'*80}")
    
    # 실행 전 DB 스냅샷
    print("\n📸 DB State BEFORE execution:")
    before_snapshot = get_db_snapshot()
    before_neo4j = get_neo4j_snapshot()
    print_db_snapshot(before_snapshot, "PostgreSQL BEFORE")
    print_neo4j_snapshot(before_neo4j, "Neo4j BEFORE")
    
    # 노드 실행
    try:
        start_time = datetime.now()
        node_output = node(state)
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"\n✅ Node [{node_name}] completed in {duration:.2f}s")
        
        # 노드 출력을 기존 state에 merge (노드는 partial state만 반환)
        result_state = {**state, **node_output}
        
        # 노드 결과 저장
        node_result_keys = [key for key in node_output.keys() if key not in state or state[key] != node_output[key]]
        DEBUG_STORAGE.node_results[node_name] = {
            "duration_seconds": duration,
            "updated_keys": node_result_keys,
        }
        
        # 주요 결과 출력
        print(f"\n📋 State keys updated by [{node_name}]:")
        for key in node_result_keys[:15]:
            value = node_output.get(key)
            if isinstance(value, list):
                print(f"   - {key}: list with {len(value)} items")
            elif isinstance(value, dict):
                print(f"   - {key}: dict with {len(value)} keys")
            else:
                print(f"   - {key}: {str(value)[:100]}")
        
    except Exception as e:
        print(f"\n❌ Node [{node_name}] failed: {e}")
        traceback.print_exc()
        DEBUG_STORAGE.errors.append({
            "node": node_name,
            "error": str(e),
            "traceback": traceback.format_exc()
        })
        result_state = state
    
    # 실행 후 DB 스냅샷
    print("\n📸 DB State AFTER execution:")
    after_snapshot = get_db_snapshot()
    after_neo4j = get_neo4j_snapshot()
    
    # DB 변경사항 출력
    print(f"\n📊 DATABASE CHANGES by [{node_name}]:")
    print("-"*60)
    
    has_postgres_changes = False
    for table_name in after_snapshot.get("tables", {}):
        before_count = before_snapshot.get("tables", {}).get(table_name, {}).get("count", 0)
        after_count = after_snapshot.get("tables", {}).get(table_name, {}).get("count", 0)
        
        if after_count != before_count:
            has_postgres_changes = True
            diff = after_count - before_count
            diff_str = f"+{diff}" if diff > 0 else str(diff)
            print(f"   PostgreSQL | {table_name}: {before_count} → {after_count} ({diff_str})")
            
            # 새로 추가된 샘플 출력
            if diff > 0:
                samples = after_snapshot.get("tables", {}).get(table_name, {}).get("sample", [])
                for sample in samples[:2]:
                    sample_str = ", ".join(f"{k}={str(v)[:25]}" for k, v in list(sample.items())[:4])
                    print(f"              └ {sample_str}")
    
    if not has_postgres_changes:
        print("   PostgreSQL | (No changes)")
    
    # Neo4j 변경사항
    has_neo4j_changes = False
    if after_neo4j.get("connected"):
        for node_type, count in after_neo4j.get("nodes", {}).items():
            before_count = before_neo4j.get("nodes", {}).get(node_type, 0)
            if count != before_count:
                has_neo4j_changes = True
                diff = count - before_count
                diff_str = f"+{diff}" if diff > 0 else str(diff)
                print(f"   Neo4j      | {node_type}: {before_count} → {count} ({diff_str})")
        
        for rel_type, count in after_neo4j.get("relationships", {}).items():
            before_count = before_neo4j.get("relationships", {}).get(rel_type, 0)
            if count != before_count:
                has_neo4j_changes = True
                diff = count - before_count
                diff_str = f"+{diff}" if diff > 0 else str(diff)
                print(f"   Neo4j      | {rel_type}: {before_count} → {count} ({diff_str})")
    
    if not has_neo4j_changes:
        print("   Neo4j      | (No changes)")
    
    # 스냅샷 저장
    DEBUG_STORAGE.db_snapshots[node_name] = {
        "before": before_snapshot,
        "after": after_snapshot,
        "neo4j_before": before_neo4j,
        "neo4j_after": after_neo4j,
    }
    
    return result_state


# =============================================================================
# Database Reset
# =============================================================================

def reset_database():
    """테스트 전 DB 초기화"""
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
    
    for manager_cls, name in [
        (OntologySchemaManager, "Ontology"),
        (DictionarySchemaManager, "Dictionary"),
        (ParameterSchemaManager, "Parameter"),
        (CatalogSchemaManager, "Catalog"),
        (DirectorySchemaManager, "Directory"),
    ]:
        try:
            manager = manager_cls()
            manager.drop_tables(confirm=True)
            print(f"✅ {name} tables dropped")
        except Exception as e:
            print(f"⚠️  Error dropping {name}: {e}")
    
    for manager_cls, name in [
        (DirectorySchemaManager, "Directory"),
        (CatalogSchemaManager, "Catalog"),
        (DictionarySchemaManager, "Dictionary"),
        (ParameterSchemaManager, "Parameter"),
        (OntologySchemaManager, "Ontology"),
    ]:
        try:
            manager = manager_cls()
            manager.create_tables()
            print(f"✅ {name} tables created")
        except Exception as e:
            print(f"⚠️  Error creating {name}: {e}")


def reset_neo4j():
    """Neo4j 초기화"""
    print("\n🗑️  Resetting Neo4j...")
    
    try:
        from neo4j import GraphDatabase
        from src.config import Neo4jConfig
        
        driver = GraphDatabase.driver(
            Neo4jConfig.URI,
            auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
        )
        driver.verify_connectivity()
        
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            session.run("MATCH (n) DETACH DELETE n")
            print("✅ Neo4j cleared")
        
        driver.close()
    except Exception as e:
        print(f"⚠️  Neo4j reset failed: {e}")


# =============================================================================
# Main Execution
# =============================================================================

def find_data_files() -> List[str]:
    """데이터 파일 찾기"""
    DATA_DIR = Path(__file__).parent / "data" / "raw" / "Open_VitalDB_1.0.0"
    
    print(f"\n📂 Scanning: {DATA_DIR}")
    files = []
    
    if not DATA_DIR.exists():
        print(f"⚠️  Data directory not found: {DATA_DIR}")
        return files
    
    for f in DATA_DIR.rglob("*.csv"):
        files.append(str(f))
        print(f"   Found: {f.name}")
    
    vital_files = list(DATA_DIR.rglob("*.vital"))[:3]
    for f in vital_files:
        files.append(str(f))
        print(f"   Found: {f.name} (signal)")
    
    print(f"\n📁 Total files: {len(files)}")
    return files


def get_initial_state(input_files: List[str]) -> Dict[str, Any]:
    """초기 상태 생성"""
    DATA_DIR = Path(__file__).parent / "data" / "raw" / "Open_VitalDB_1.0.0"
    
    return {
        "input_directory": str(DATA_DIR),
        "current_dataset_id": "open_vitaldb_v1.0.0_debug",
        "current_table_name": None,
        "data_catalog": {},
        "directory_catalog_result": None,
        "catalog_dir_ids": [],
        "file_catalog_result": None,
        "catalog_file_ids": [],
        "schema_aggregation_result": None,
        "unique_columns": [],
        "unique_files": [],
        "column_batches": [],
        "file_batches": [],
        "file_classification_result": None,
        "metadata_files": [],
        "data_files": [],
        "metadata_semantic_result": None,
        "data_dictionary_entries": [],
        "data_semantic_result": None,
        "data_semantic_entries": [],
        "directory_pattern_result": None,
        "directory_patterns": {},
        "entity_identification_result": None,
        "table_entity_results": [],
        "relationship_inference_result": None,
        "table_relationships": [],
        "ontology_enhancement_result": None,
        "ontology_subcategories": [],
        "semantic_edges": [],
        "medical_term_mappings": [],
        "cross_table_semantics": [],
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
        "conversation_history": {
            "session_id": f"debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "dataset_id": "open_vitaldb_v1.0.0",
            "started_at": datetime.now().isoformat(),
            "turns": [],
            "classification_decisions": [],
            "entity_decisions": [],
            "user_preferences": {},
        },
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


def run_debug_pipeline(until_node: str = None, only_node: str = None):
    """디버그 모드로 파이프라인 실행"""
    
    # 중요: 노드들을 레지스트리에 등록하기 위해 먼저 import
    import src.agents.nodes  # noqa: F401
    
    NODE_ORDER = [
        "directory_catalog",      # 100 - 📏 Rule-based
        "file_catalog",           # 200 - 📏 Rule-based
        "schema_aggregation",     # 300 - 📏 Rule-based
        "file_classification",    # 400 - 🤖 LLM
        "column_classification",  # 420 - 🤖 LLM (NEW: column role + parameter creation)
        "metadata_semantic",      # 500 - 🤖 LLM
        "parameter_semantic",     # 600 - 🤖 LLM (renamed from data_semantic)
        "directory_pattern",      # 700 - 🤖 LLM
        "entity_identification",  # 800 - 🤖 LLM
        "relationship_inference", # 900 - 🤖 LLM + Neo4j
        "ontology_enhancement",   # 1000 - 🤖 LLM + Neo4j
    ]
    
    if only_node:
        if only_node not in NODE_ORDER:
            print(f"❌ Unknown node: {only_node}")
            print(f"Available nodes: {NODE_ORDER}")
            return
        nodes_to_run = [only_node]
        print(f"🎯 Running only: {only_node}")
    elif until_node:
        if until_node not in NODE_ORDER:
            print(f"❌ Unknown node: {until_node}")
            print(f"Available nodes: {NODE_ORDER}")
            return
        idx = NODE_ORDER.index(until_node)
        nodes_to_run = NODE_ORDER[:idx + 1]
        print(f"🎯 Running until: {until_node}")
    else:
        nodes_to_run = NODE_ORDER
        print("🎯 Running full pipeline")
    
    print(f"\n📋 Nodes to run: {nodes_to_run}")
    
    # LLM 패치
    patch_llm_client()
    
    # DB 초기화 (only_node가 아닌 경우에만)
    if not only_node:
        reset_database()
        reset_neo4j()
    
    # 데이터 파일 찾기
    input_files = find_data_files()
    if not input_files:
        print("❌ No data files found!")
        return
    
    # 초기 상태
    state = get_initial_state(input_files)
    
    # 각 노드 실행
    print("\n" + "="*80)
    print("🚀 STARTING DEBUG PIPELINE")
    print("="*80)
    
    start_time = datetime.now()
    
    for node_name in nodes_to_run:
        state = run_node_with_debug(node_name, state)
    
    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()
    
    # 최종 요약 출력
    print("\n" + "="*80)
    print("📊 DEBUG PIPELINE COMPLETED")
    print("="*80)
    print(f"Total duration: {total_duration:.2f}s ({total_duration/60:.2f}m)")
    
    DEBUG_STORAGE.print_summary()
    
    print("\n" + "="*80)
    print("✅ DONE")
    print("="*80)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Debug test script for Indexing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_debug_pipeline.py                            # 전체 파이프라인
  python test_debug_pipeline.py --until file_classification  # 특정 노드까지
  python test_debug_pipeline.py --only data_semantic          # 특정 노드만
        """
    )
    
    parser.add_argument("--until", type=str, help="Run pipeline until this node (inclusive)")
    parser.add_argument("--only", type=str, help="Run only this specific node")
    parser.add_argument("--no-reset", action="store_true", help="Don't reset database")
    
    args = parser.parse_args()
    
    print("="*80)
    print("🧪 DEBUG TEST SCRIPT FOR INDEXING PIPELINE")
    print("="*80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    run_debug_pipeline(until_node=args.until, only_node=args.only)


if __name__ == "__main__":
    main()
