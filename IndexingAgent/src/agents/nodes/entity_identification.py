# src/agents/nodes/entity_identification.py
"""
Phase 2A: Entity Identification Node

데이터 파일(is_metadata=false)의 행이 무엇을 나타내는지(row_represents)와
고유 식별자 컬럼(entity_identifier)을 식별합니다.

주요 기능:
- LLM을 사용해 각 테이블의 row_represents 추론 (surgery, patient, lab_result 등)
- 컬럼 통계(unique count)를 활용해 entity_identifier 식별
- table_entities 테이블에 결과 저장
"""

import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from ..state import AgentState
from ..models.llm_responses import (
    TableEntityResult,
    EntityIdentificationResponse,
    Phase2AResult,
)
from src.database.connection import get_db_manager
from src.database.schema_ontology import OntologySchemaManager
from src.utils.llm_client import get_llm_client
from src.config import Phase8Config, LLMConfig


# =============================================================================
# LLM Prompt Template
# =============================================================================

ENTITY_IDENTIFICATION_PROMPT = """You are a Medical Data Expert analyzing clinical database tables.

[Task]
For each data table, identify:
1. **row_represents**: What does each ROW in this table represent? 
   - Examples: "surgery", "patient", "lab_result", "vital_sign_record", "medication_order"
   - Use a SINGULAR noun (not plural)
   
2. **entity_identifier**: Which column UNIQUELY identifies each row?
   - Look at unique counts - if unique count equals row count, that's a good candidate
   - If multiple columns together form a unique key, set to null
   - If no single column uniquely identifies rows, set to null

[Tables to Analyze]
{tables_context}

[CRITICAL RULES]
1. row_represents should be a SINGULAR, descriptive noun in lowercase
2. entity_identifier should be a column with unique values per row (unique_count ≈ row_count)
3. If a table has time-series data (same ID with multiple timestamps), the ID column is NOT a unique identifier
4. For signal/waveform data, consider if there's a case/subject identifier

[Output Format]
Return ONLY valid JSON (no markdown, no explanation):
{{
  "tables": [
    {{
      "file_name": "clinical_data.csv",
      "row_represents": "surgery",
      "entity_identifier": "caseid",
      "confidence": 0.95,
      "reasoning": "caseid has 6388 unique values matching row count, each row is one surgery record"
    }},
    {{
      "file_name": "lab_results.csv",
      "row_represents": "lab_result",
      "entity_identifier": null,
      "confidence": 0.85,
      "reasoning": "Multiple lab results per caseid over time, no single column uniquely identifies a row"
    }}
  ]
}}
"""


# =============================================================================
# Helper Functions: Data Loading
# =============================================================================

def _load_data_files_with_columns(data_files: List[str]) -> List[Dict[str, Any]]:
    """
    데이터 파일과 그 컬럼 정보를 DB에서 로드
    
    Returns:
        [
            {
                "file_id": "uuid",
                "file_name": "clinical_data.csv",
                "row_count": 6388,
                "columns": [
                    {
                        "original_name": "caseid",
                        "semantic_name": "Case ID",
                        "column_type": "categorical",
                        "concept_category": "Identifiers",
                        "unique_count": 6388,
                        ...
                    },
                    ...
                ]
            },
            ...
        ]
    """
    if not data_files:
        return []
    
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    files_info = []
    
    try:
        for file_path in data_files:
            # 파일 정보 조회 (row_count는 file_metadata JSONB에 있음)
            cursor.execute("""
                SELECT file_id, file_name, file_metadata
                FROM file_catalog
                WHERE file_path = %s
            """, (file_path,))
            
            file_row = cursor.fetchone()
            if not file_row:
                continue
            
            file_id, file_name, file_metadata = file_row
            
            # file_metadata에서 row_count 추출
            if file_metadata:
                if isinstance(file_metadata, str):
                    file_metadata = json.loads(file_metadata)
                row_count = file_metadata.get('row_count', 0)
            else:
                row_count = 0
            
            # 컬럼 정보 조회 (Phase 1B에서 분석된 semantic 정보 포함)
            cursor.execute("""
                SELECT 
                    original_name,
                    semantic_name,
                    column_type,
                    concept_category,
                    column_info,
                    value_distribution
                FROM column_metadata
                WHERE file_id = %s
                ORDER BY col_id
            """, (str(file_id),))
            
            columns = []
            for col_row in cursor.fetchall():
                (original_name, semantic_name, column_type,
                 concept_category, column_info, value_distribution) = col_row
                
                # unique_count 추출
                unique_count = None
                if value_distribution:
                    if isinstance(value_distribution, str):
                        value_distribution = json.loads(value_distribution)
                    unique_values = value_distribution.get('unique_values', [])
                    unique_count = len(unique_values) if unique_values else None
                
                # column_info에서 추가 정보 추출
                if column_info:
                    if isinstance(column_info, str):
                        column_info = json.loads(column_info)
                    # unique_count가 없으면 column_info에서 추출 시도
                    if unique_count is None:
                        unique_count = column_info.get('unique_count')
                
                columns.append({
                    "original_name": original_name,
                    "semantic_name": semantic_name,
                    "column_type": column_type,
                    "concept_category": concept_category,
                    "unique_count": unique_count,
                    "column_info": column_info if isinstance(column_info, dict) else {}
                })
            
            files_info.append({
                "file_id": str(file_id),
                "file_name": file_name,
                "row_count": row_count or 0,
                "file_path": file_path,
                "columns": columns
            })
    
    except Exception as e:
        print(f"❌ [Phase2A] Error loading data files: {e}")
        import traceback
        traceback.print_exc()
    
    return files_info


# =============================================================================
# Helper Functions: Context Building
# =============================================================================

def _build_tables_context(files_info: List[Dict[str, Any]]) -> str:
    """
    LLM 프롬프트용 테이블 컨텍스트 생성
    
    Args:
        files_info: _load_data_files_with_columns()의 결과
    
    Returns:
        포맷된 문자열
    """
    lines = []
    
    for file_info in files_info:
        file_name = file_info['file_name']
        row_count = file_info['row_count']
        columns = file_info['columns']
        
        lines.append(f"\n## {file_name}")
        lines.append(f"Rows: {row_count:,}")
        lines.append("Columns:")
        
        max_cols = Phase8Config.MAX_COLUMNS_PER_TABLE
        display_cols = columns[:max_cols] if max_cols > 0 else columns
        
        for col in display_cols:
            name = col['original_name']
            semantic = col.get('semantic_name') or name
            concept = col.get('concept_category') or '-'
            col_type = col.get('column_type') or '-'
            unique_count = col.get('unique_count')
            
            line = f"  - {name}"
            if semantic != name:
                line += f" ({semantic})"
            line += f" [{concept}, {col_type}]"
            
            # identifier 후보인 경우 unique count 강조
            if Phase8Config.SHOW_UNIQUE_COUNTS and unique_count is not None:
                line += f" unique: {unique_count:,}"
            
            lines.append(line)
        
        if max_cols > 0 and len(columns) > max_cols:
            lines.append(f"  ... and {len(columns) - max_cols} more columns")
    
    return "\n".join(lines)


# =============================================================================
# Helper Functions: LLM Interaction
# =============================================================================

def _call_llm_for_entity_identification(
    files_info: List[Dict[str, Any]]
) -> Tuple[List[TableEntityResult], int]:
    """
    LLM을 호출하여 Entity 식별
    
    Args:
        files_info: 테이블 정보 목록
    
    Returns:
        (결과 목록, LLM 호출 횟수)
    """
    if not files_info:
        return [], 0
    
    llm_client = get_llm_client()
    tables_context = _build_tables_context(files_info)
    
    prompt = ENTITY_IDENTIFICATION_PROMPT.format(tables_context=tables_context)
    
    print(f"   📤 Sending {len(files_info)} tables to LLM...")
    
    llm_calls = 0
    results = []
    
    for attempt in range(Phase8Config.MAX_RETRIES):
        try:
            response = llm_client.ask_json(
                prompt,
                max_tokens=LLMConfig.MAX_TOKENS
            )
            llm_calls += 1
            
            if response and 'tables' in response:
                for table_data in response['tables']:
                    result = TableEntityResult(
                        file_name=table_data.get('file_name', ''),
                        row_represents=table_data.get('row_represents', 'unknown'),
                        entity_identifier=table_data.get('entity_identifier'),
                        confidence=float(table_data.get('confidence', 0.0)),
                        reasoning=table_data.get('reasoning', '')
                    )
                    results.append(result)
                
                return results, llm_calls
            else:
                print(f"   ⚠️ Invalid LLM response format, attempt {attempt + 1}")
                
        except Exception as e:
            print(f"   ❌ LLM call failed (attempt {attempt + 1}): {e}")
            if attempt < Phase8Config.MAX_RETRIES - 1:
                import time
                time.sleep(Phase8Config.RETRY_DELAY_SECONDS)
    
    return results, llm_calls


# =============================================================================
# Helper Functions: Database Operations
# =============================================================================

def _save_table_entities(
    files_info: List[Dict[str, Any]],
    llm_results: List[TableEntityResult]
) -> int:
    """
    LLM 결과를 table_entities 테이블에 저장
    
    Args:
        files_info: 파일 정보 (file_id 포함)
        llm_results: LLM 분석 결과
    
    Returns:
        저장된 엔티티 수
    """
    # file_name → file_id 매핑 생성
    name_to_info = {f['file_name']: f for f in files_info}
    
    entities_to_save = []
    
    for result in llm_results:
        file_info = name_to_info.get(result.file_name)
        if not file_info:
            print(f"   ⚠️ File not found: {result.file_name}")
            continue
        
        entities_to_save.append({
            "file_id": file_info['file_id'],
            "row_represents": result.row_represents,
            "entity_identifier": result.entity_identifier,
            "confidence": result.confidence,
            "reasoning": result.reasoning
        })
    
    if entities_to_save:
        schema_manager = OntologySchemaManager()
        schema_manager.save_table_entities(entities_to_save)
    
    return len(entities_to_save)


# =============================================================================
# Main Node Function
# =============================================================================

def phase8_entity_identification_node(state: AgentState) -> Dict[str, Any]:
    """
    Phase 2A: Entity Identification Node
    
    데이터 파일의 행이 무엇을 나타내는지(row_represents)와
    고유 식별자 컬럼(entity_identifier)을 식별합니다.
    
    Input (from state):
        - data_files: is_metadata=false인 파일 경로 목록
        - phase1b_result: Phase 1B 완료 정보 (column_metadata 분석 완료)
    
    Output:
        - phase2a_result: Phase2AResult 형태
        - table_entity_results: TableEntityResult 목록
    """
    print("\n" + "="*60)
    print("📊 Phase 8: Entity Identification")
    print("="*60)
    
    started_at = datetime.now().isoformat()
    
    # 1. 데이터 파일 목록 가져오기
    data_files = state.get('data_files', [])
    
    if not data_files:
        print("ℹ️  No data files to analyze")
        return {
            "phase8_result": Phase2AResult(
                started_at=started_at,
                completed_at=datetime.now().isoformat()
            ).model_dump(),
            "table_entity_results": []
        }
    
    print(f"\n📁 Data files to analyze: {len(data_files)}")
    for f in data_files[:5]:
        print(f"   - {f}")
    if len(data_files) > 5:
        print(f"   ... and {len(data_files) - 5} more")
    
    # 2. Ontology 스키마 초기화
    schema_manager = OntologySchemaManager()
    schema_manager.create_tables()
    
    # 3. 데이터 파일과 컬럼 정보 로드
    print("\n📥 Loading data files with column info...")
    files_info = _load_data_files_with_columns(data_files)
    
    if not files_info:
        print("⚠️  No file info loaded from database")
        return {
            "phase8_result": Phase2AResult(
                total_tables=len(data_files),
                started_at=started_at,
                completed_at=datetime.now().isoformat()
            ).model_dump(),
            "table_entity_results": []
        }
    
    print(f"✅ Loaded {len(files_info)} files with column info")
    
    # 4. LLM 호출 (배치 처리)
    print("\n🤖 Calling LLM for entity identification...")
    
    all_results: List[TableEntityResult] = []
    total_llm_calls = 0
    
    # 배치 크기에 따라 분할
    batch_size = Phase8Config.TABLE_BATCH_SIZE
    for i in range(0, len(files_info), batch_size):
        batch = files_info[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(files_info) + batch_size - 1) // batch_size
        
        print(f"\n   📦 Batch {batch_num}/{total_batches} ({len(batch)} tables)")
        
        results, llm_calls = _call_llm_for_entity_identification(batch)
        all_results.extend(results)
        total_llm_calls += llm_calls
        
        print(f"   ✅ Got {len(results)} results")
    
    # 5. DB 저장
    print("\n💾 Saving to table_entities...")
    saved_count = _save_table_entities(files_info, all_results)
    print(f"✅ Saved {saved_count} table entities")
    
    # 6. 통계 계산
    entities_identified = sum(1 for r in all_results if r.row_represents != 'unknown')
    identifiers_found = sum(1 for r in all_results if r.entity_identifier is not None)
    high_conf = sum(1 for r in all_results if r.confidence >= Phase8Config.CONFIDENCE_THRESHOLD)
    low_conf = sum(1 for r in all_results if r.confidence < Phase8Config.CONFIDENCE_THRESHOLD)
    
    # 7. 결과 출력
    print("\n" + "-"*60)
    print("📊 Phase 8 Summary:")
    print(f"   Total tables: {len(files_info)}")
    print(f"   Analyzed: {len(all_results)}")
    print(f"   Entities identified: {entities_identified}")
    print(f"   With unique identifier: {identifiers_found}")
    print(f"   High confidence (≥{Phase8Config.CONFIDENCE_THRESHOLD}): {high_conf}")
    print(f"   Low confidence: {low_conf}")
    print(f"   LLM calls: {total_llm_calls}")
    
    # 상세 결과 출력
    print("\n📋 Entity Results:")
    for result in all_results:
        identifier_str = result.entity_identifier or "(none)"
        conf_emoji = "🟢" if result.confidence >= Phase8Config.CONFIDENCE_THRESHOLD else "🟡"
        print(f"   {conf_emoji} {result.file_name}")
        print(f"      row_represents: {result.row_represents}")
        print(f"      entity_identifier: {identifier_str}")
        print(f"      confidence: {result.confidence:.2f}")
    
    # 8. 결과 반환
    completed_at = datetime.now().isoformat()
    
    phase2a_result = Phase2AResult(
        total_tables=len(files_info),
        tables_analyzed=len(all_results),
        entities_identified=entities_identified,
        identifiers_found=identifiers_found,
        high_confidence=high_conf,
        low_confidence=low_conf,
        llm_calls=total_llm_calls,
        started_at=started_at,
        completed_at=completed_at
    )
    
    return {
        "phase8_result": phase2a_result.model_dump(),
        "table_entity_results": [r.model_dump() for r in all_results]
    }

