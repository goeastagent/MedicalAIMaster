# src/agents/helpers/llm_helpers.py
"""
LLM 관련 헬퍼 함수들 - 시맨틱 분석, 리뷰 판단 등
"""

import os
import json
from typing import Dict, Any, List, Optional

from src.agents.state import ColumnSchema
from src.utils.llm_client import get_llm_client
from src.utils.ontology_manager import get_ontology_manager
from src.utils.llm_cache import get_llm_cache
from src.config import HumanReviewConfig

# Lazy initialization to avoid circular imports
_llm_client = None
_ontology_manager = None
_llm_cache = None

def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        _llm_client = get_llm_client()
    return _llm_client

def _get_ontology_manager():
    global _ontology_manager
    if _ontology_manager is None:
        _ontology_manager = get_ontology_manager()
    return _ontology_manager

def _get_llm_cache():
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = get_llm_cache()
    return _llm_cache


def analyze_columns_with_llm(
    columns: List[str], 
    sample_data: Any, 
    anchor_context: Dict,
    user_feedback: str = None  # NEW: 사용자 피드백
) -> List[ColumnSchema]:
    """
    [Helper] Analyze column meaning, data type, PII status, units, etc. using LLM
    
    Args:
        user_feedback: 사용자가 제공한 컬럼/데이터 설명 (예: "caseid는 수술ID, subjectid는 환자ID")
    """
    # User feedback context
    user_context = ""
    if user_feedback:
        user_context = f"""
    [USER FEEDBACK - PRIORITIZE THIS INFORMATION]
    The user has provided the following context about this data:
    "{user_feedback}"
    
    Use this information to improve your analysis accuracy.
    """
    
    # Context summary for LLM
    prompt = f"""
    You are a Medical Data Ontologist specializing in clinical database design.
    Analyze the columns of a medical dataset and provide DETAILED metadata.
    {user_context}
    [Context]
    - Patient Identifier (Anchor): {anchor_context.get('column_name')}
    - Is Time Series: {anchor_context.get('is_time_series')}
    
    [Columns to Analyze]
    """
    
    # If sample_data is a list (from TabularProcessor)
    if isinstance(sample_data, list):
        for col_detail in sample_data:
            col_name = col_detail.get('column_name', 'unknown')
            col_type = col_detail.get('column_type', 'unknown')
            samples = col_detail.get('samples', [])
            
            if col_type == 'categorical':
                unique_vals = col_detail.get('unique_values', [])
                prompt += f"- Column: '{col_name}' | Type: CATEGORICAL | Unique Values: {unique_vals}\n"
            else:
                min_val = col_detail.get('min', 'N/A')
                max_val = col_detail.get('max', 'N/A')
                prompt += f"- Column: '{col_name}' | Type: CONTINUOUS | Range: [{min_val}, {max_val}] | Samples: {samples}\n"
    elif isinstance(sample_data, dict):
        for col in columns:
            details = sample_data.get(col, {})
            samples = details.get("sample_values", [])
            prompt += f"- Column: '{col}', Samples: {samples}\n"
    else:
        for col in columns:
            prompt += f"- Column: '{col}'\n"

    prompt += """
    [Task]
    For EACH column, provide a JSON object with DETAILED metadata:
    
    1. original_name: The exact column name as provided (REQUIRED)
    2. inferred_name: Human-readable name (e.g., 'sbp' → 'Systolic Blood Pressure')
    3. full_name: Full medical term without abbreviation
    4. description: Brief medical description
    5. description_kr: Korean description for Korean users (한글 설명)
    6. data_type: SQL compatible type (VARCHAR, INT, FLOAT, TIMESTAMP, BOOLEAN)
    7. semantic_type: High-level semantic category (e.g., "identifier", "timestamp", "measurement", "demographic", "clinical_score", "outcome")
    8. column_type: "categorical" or "continuous" based on the data nature
    9. unit: Measurement unit if applicable (e.g., "mmHg", "kg", null if N/A)
    10. typical_range: Normal/typical value range in medical context (null if N/A)
    11. is_pii: Boolean (true if it contains name, phone, address, social security number)
    12. confidence: 0.0 to 1.0
    13. value_mappings: (ONLY for CATEGORICAL columns) Dictionary mapping each unique value to its meaning
        - Example: sex column with values [0, 1] → {"0": "Male", "1": "Female"}
        - Example: asa column with values [1,2,3,4,5] → {"1": "Normal healthy patient", "2": "Mild systemic disease", ...}
        - For CONTINUOUS/NUMERIC columns: null
        - If meaning cannot be inferred: null

    Respond with a JSON object: {"columns": [list of column objects]}
    """
    
    response = _get_llm_client().ask_json(prompt)
    
    if isinstance(response, dict) and "columns" in response:
        result_list = response["columns"]
    elif isinstance(response, list):
        result_list = response
    else:
        result_list = []

    final_schema = []
    for idx, item in enumerate(result_list):
        original = item.get("original_name") or (columns[idx] if idx < len(columns) else "unknown")
        
        # value_mappings 처리: dict여야 하고, 비어있으면 null로 처리
        value_mappings = item.get("value_mappings")
        if value_mappings is not None and not isinstance(value_mappings, dict):
            value_mappings = None
        if isinstance(value_mappings, dict) and len(value_mappings) == 0:
            value_mappings = None
        
        final_schema.append({
            "original_name": original,
            "inferred_name": item.get("inferred_name", original),
            "full_name": item.get("full_name", item.get("inferred_name", original)),
            "description": item.get("description", ""),
            "description_kr": item.get("description_kr", ""),
            "data_type": item.get("data_type", "VARCHAR"),
            "semantic_type": item.get("semantic_type"),  # NEW: 의미적 타입
            "column_type": item.get("column_type"),      # NEW: categorical/continuous
            "unit": item.get("unit"),
            "typical_range": item.get("typical_range"),
            "standard_concept_id": None, 
            "is_pii": item.get("is_pii", False),
            "confidence": item.get("confidence", 0.5),
            "value_mappings": value_mappings
        })
        
    return final_schema


def analyze_intra_table_hierarchy(
    columns: List[str],
    sample_data: Any,
    table_name: str,
    user_feedback: str = None  # NEW: 사용자 피드백 전달
) -> Optional[Dict]:
    """
    [LLM] 테이블 내 ID 컬럼 간의 계층 관계 감지
    
    예: subjectid (환자) → caseid (수술) = 1:N 관계
    한 환자가 여러 번의 수술을 받을 수 있음
    
    Args:
        user_feedback: 사용자가 제공한 컬럼 관계 설명 (예: "subjectid는 환자ID, caseid는 수술ID")
    
    Returns:
        {
            "child_column": "caseid",
            "parent_column": "subjectid",
            "cardinality": "N:1",
            "reasoning": "..."
        }
        또는 None (계층 관계 없음)
    """
    # ID 컬럼 후보 필터링 (id, _id로 끝나는 컬럼들)
    id_columns = [col for col in columns if 
                  col.lower().endswith('id') or 
                  col.lower().endswith('_id') or
                  col.lower() in ['id', 'key', 'code']]
    
    if len(id_columns) < 2:
        print(f"   ℹ️ [Hierarchy] ID 컬럼이 2개 미만 ({id_columns}) - 스킵")
        return None
    
    # 샘플 데이터에서 ID 컬럼들의 값 분포 추출
    id_samples = {}
    if isinstance(sample_data, list):
        for col_detail in sample_data:
            col_name = col_detail.get('column_name', '')
            if col_name in id_columns:
                # TabularProcessor는 'n_unique' 필드를 제공함
                n_unique = col_detail.get('n_unique', 0)
                # unique_values 리스트의 길이로도 계산 가능
                if n_unique == 0:
                    unique_vals = col_detail.get('unique_values', [])
                    n_unique = len(unique_vals) if isinstance(unique_vals, list) else 0
                
                id_samples[col_name] = {
                    "unique_count": n_unique,
                    "sample_values": col_detail.get('samples', [])[:10],
                    "column_type": col_detail.get('column_type', 'unknown')
                }
    
    # 사용자 피드백이 있으면 우선 사용
    user_context = ""
    if user_feedback:
        user_context = f"""
[USER FEEDBACK - IMPORTANT, PRIORITIZE THIS]
The user has provided the following explanation about the column relationships:
"{user_feedback}"

"""

    prompt = f"""You are a Medical Data Expert analyzing table structure.

[TASK]
Analyze the ID columns in this table to find parent-child relationships.
A parent-child relationship exists when:
1. One ID column has FEWER unique values than another
2. The column with MORE unique values is likely grouped under the other
{user_context}
[TABLE]
Table Name: {table_name}

[ID COLUMNS - unique_count shows number of distinct values]
{json.dumps(id_samples, indent=2)}

[EXAMPLE]
If subjectid has unique_count=1000 and caseid has unique_count=6000,
then: caseid is CHILD of subjectid (N:1 relationship)
- Meaning: One patient (subjectid) can have multiple surgery cases (caseid)
- Ratio ~6:1 suggests each patient has ~6 cases on average

[RESPONSE FORMAT - JSON ONLY]
If hierarchy found:
{{
    "hierarchy_found": true,
    "child_column": "caseid",
    "parent_column": "subjectid",
    "cardinality": "N:1",
    "hierarchy_type": "patient_to_case",
    "reasoning": "subjectid has 1000 unique values, caseid has 6000, ratio ~6:1 suggests multiple cases per patient"
}}

If NO hierarchy:
{{
    "hierarchy_found": false,
    "reasoning": "All ID columns appear to be independent identifiers or have 1:1 relationship"
}}

IMPORTANT:
- Common medical hierarchies: patient → case/visit → measurement
"""
    
    try:
        result = _get_llm_client().ask_json(prompt)
        
        if not result.get("hierarchy_found", False):
            print(f"   ℹ️ [Hierarchy] 계층 관계 없음: {result.get('reasoning', '')}")
            return None
        
        hierarchy = {
            "child_column": result.get("child_column"),
            "parent_column": result.get("parent_column"),
            "cardinality": result.get("cardinality", "N:1"),
            "hierarchy_type": result.get("hierarchy_type", "unknown"),
            "reasoning": result.get("reasoning", "")
        }
        
        print(f"   ✅ [Hierarchy] 발견: {hierarchy['child_column']} → {hierarchy['parent_column']} ({hierarchy['cardinality']})")
        print(f"      근거: {hierarchy['reasoning'][:100]}...")
        
        return hierarchy
        
    except Exception as e:
        print(f"   ⚠️ [Hierarchy] 분석 오류: {e}")
        return None


def analyze_tracks_with_llm(tracks: List[str], column_details: Dict) -> Dict[str, Dict]:
    """
    [LLM Decides] Signal 트랙의 의미를 LLM이 분석
    """
    if not tracks:
        return {}
    
    tracks_summary = ""
    for track_name in tracks[:20]:
        details = column_details.get(track_name, {})
        unit = details.get("unit", "N/A")
        sr = details.get("sample_rate", 0)
        col_type = details.get("column_type", "unknown")
        
        tracks_summary += f"- Track: '{track_name}' | Unit: {unit} | Sample Rate: {sr}Hz | Type: {col_type}\n"
    
    if len(tracks) > 20:
        tracks_summary += f"  ... and {len(tracks) - 20} more tracks\n"
    
    prompt = f"""You are a Medical Signal Processing Expert.
Analyze the following signal tracks and provide detailed metadata for each.

[SIGNAL TRACKS - Pre-processed by Rules]
{tracks_summary}

[TASK]
For each track, determine:
1. **inferred_name**: Human-readable name (e.g., 'SNUADC/ECG_II' → 'Lead II ECG')
2. **description**: Brief medical description
3. **clinical_category**: One of: cardiac_waveform, cardiac_vital, respiratory, neurological, temperature, anesthesia, other

[RESPONSE FORMAT - JSON]
{{
    "tracks": {{
        "track_name": {{
            "inferred_name": "Human readable name",
            "description": "Brief description",
            "clinical_category": "category"
        }}
    }}
}}
"""
    
    try:
        result = _get_llm_client().ask_json(prompt)
        tracks_analysis = result.get("tracks", {})
        
        for track_name in tracks:
            if track_name not in tracks_analysis:
                tracks_analysis[track_name] = {
                    "inferred_name": track_name,
                    "description": "",
                    "clinical_category": "other"
                }
        
        print(f"   🧠 [LLM] Analyzed {len(tracks_analysis)} tracks")
        return tracks_analysis
        
    except Exception as e:
        print(f"   ⚠️ [LLM] Track analysis failed: {e}")
        return {track_name: {
            "inferred_name": track_name,
            "description": "",
            "clinical_category": "other"
        } for track_name in tracks}


def compare_with_global_context(
    local_metadata: Dict, 
    local_anchor_info: Dict, 
    project_context: Dict,
    ontology_context: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    [Helper] Compare current file data with project Global Anchor info (using LLM)
    
    Enhanced with FK inference:
    - MATCH: 완전 일치
    - INDIRECT_LINK: 온톨로지 기반 간접 연결
    - FK_LINK: FK 관계를 통한 연결 (NEW!)
    - CONFLICT/MISSING: 연결 불가
    """
    master_name = project_context["master_anchor_name"]
    local_cols = local_metadata.get("columns", [])
    local_candidate = local_anchor_info.get("target_column")
    
    file_path = local_metadata.get("file_path", "")
    current_table = os.path.basename(file_path).replace(".csv", "").replace(".CSV", "")
    
    # 1. 이름이 완전히 같은 경우 (Fast Path)
    if master_name in local_cols:
        return {"status": "MATCH", "target_column": master_name, "message": "Exact name match"}

    # 2. 온톨로지 기반 간접 연결 확인
    indirect_link = check_indirect_link_via_ontology(
        current_table=current_table,
        local_cols=local_cols,
        master_anchor=master_name
    )
    
    if indirect_link:
        return {
            "status": "INDIRECT_LINK",
            "target_column": indirect_link["via_column"],
            "via_table": indirect_link["via_table"],
            "master_anchor": master_name,
            "message": indirect_link["message"]
        }

    # 3. FK 관계 자동 추론 (NEW!)
    # Master anchor가 없어도 다른 컬럼을 통해 연결 가능한지 확인
    fk_link = infer_fk_relationship(
        current_table=current_table,
        local_cols=local_cols,
        master_anchor=master_name,
        ontology_context=ontology_context
    )
    
    if fk_link:
        return {
            "status": "FK_LINK",
            "target_column": fk_link["local_column"],
            "via_table": fk_link["via_table"],
            "via_column": fk_link["via_column"],
            "master_anchor": master_name,
            "fk_path": fk_link["fk_path"],
            "relation_type": fk_link.get("relation_type", "N:1"),
            "confidence": fk_link["confidence"],
            "message": fk_link["reasoning"]
        }

    # 4. 로컬 후보가 없는 경우
    if not local_candidate:
        return {
            "status": "MISSING",
            "target_column": None,
            "message": f"No anchor candidate found. Master anchor '{master_name}' not found in columns: {local_cols}"
        }

    # 5. LLM을 통한 의미론적 비교 (마지막 시도)
    prompt = f"""
    You are a Medical Data Integration Agent.
    Check if the new file contains the Project's Master Anchor (Patient ID).

    [Project Context / Global Master]
    - Master Anchor Name: '{master_name}'
    - Known Aliases: {project_context.get('known_aliases')}
    
    [New File Info]
    - Candidate Column found by AI: '{local_candidate}'
    - All Columns in file: {local_cols}
    
    [Task]
    Determine if any column represents the same 'Patient ID' entity as the Global Master.

    Respond with JSON:
    {{
        "status": "MATCH" or "MISSING" or "CONFLICT",
        "target_column": "name_of_column" or null,
        "message": "Reasoning"
    }}
    """
    
    try:
        result = _get_llm_client().ask_json(prompt)
        
        if not isinstance(result, dict):
            return {"status": "CONFLICT", "target_column": None, "message": "LLM returned invalid format"}
        
        status = result.get("status", "CONFLICT").upper()
        if status not in ["MATCH", "MISSING", "CONFLICT"]:
            status = "CONFLICT"
        
        return {
            "status": status,
            "target_column": result.get("target_column"),
            "message": result.get("message", "No explanation provided")
        }
        
    except Exception as e:
        return {"status": "CONFLICT", "target_column": None, "message": f"Error: {str(e)}"}


def check_indirect_link_via_ontology(
    current_table: str, 
    local_cols: list, 
    master_anchor: str
) -> Optional[Dict]:
    """
    Check ontology relationships for indirect connections
    """
    try:
        ontology = _get_ontology_manager().load()
        if not ontology:
            return None
        
        relationships = ontology.get("relationships", [])
        file_tags = ontology.get("file_tags", {})
        
        print(f"\n🔗 [Indirect Link Check] {current_table}")
        print(f"   - Ontology relationships: {len(relationships)}")
        
        for rel in relationships:
            source_table = rel.get("source_table", "")
            target_table = rel.get("target_table", "")
            source_column = rel.get("source_column", "")
            target_column = rel.get("target_column", "")
            
            if current_table.lower() in source_table.lower() or source_table.lower() in current_table.lower():
                if source_column in local_cols:
                    target_has_master = _check_table_has_column(file_tags, target_table, master_anchor)
                    
                    if target_has_master:
                        message = (
                            f"✅ Indirect link found! "
                            f"'{current_table}.{source_column}' → '{target_table}.{target_column}' "
                            f"connects to '{master_anchor}'"
                        )
                        print(f"   {message}")
                        
                        return {
                            "via_column": source_column,
                            "via_table": target_table,
                            "via_relation": f"{source_table}.{source_column} → {target_table}.{target_column}",
                            "message": message
                        }
        
        print(f"   - No indirect link found")
        return None
        
    except Exception as e:
        print(f"   ⚠️ Indirect link check error: {e}")
        return None


def _check_table_has_column(file_tags: Dict, table_name: str, column_name: str) -> bool:
    """Check if a specific table has a specific column in file_tags"""
    for file_path, tag_info in file_tags.items():
        file_table = os.path.basename(file_path).replace(".csv", "").replace(".CSV", "")
        
        if table_name.lower() in file_table.lower() or file_table.lower() in table_name.lower():
            columns = tag_info.get("columns", [])
            if column_name in columns:
                return True
    
    return False


def infer_fk_relationship(
    current_table: str,
    local_cols: List[str],
    master_anchor: str,
    ontology_context: Optional[Dict] = None
) -> Optional[Dict]:
    """
    [LLM] FK 관계 추론 - Master Anchor와 직접 매칭되지 않을 때 FK 경로 탐색
    
    예: lab_data.csv에 subjectid가 없지만 caseid가 있을 때
        → clinical_data.csv에 caseid와 subjectid가 모두 있으므로
        → lab_data.caseid → clinical_data.caseid → clinical_data.subjectid 경로 추론
    
    Returns:
        Dict with:
        - status: "FK_LINK" or None
        - local_column: 현재 테이블의 FK 컬럼
        - via_table: 연결되는 테이블
        - via_column: 연결 테이블의 대응 컬럼
        - fk_path: FK 연결 경로 리스트
        - confidence: 추론 확신도
        - reasoning: 추론 근거
    """
    print(f"\n🔗 [FK Inference] {current_table} → {master_anchor} 연결 시도")
    
    if not ontology_context:
        ontology_context = _get_ontology_manager().load() or {}
    
    file_tags = ontology_context.get("file_tags", {})
    column_metadata = ontology_context.get("column_metadata", {})
    existing_relationships = ontology_context.get("relationships", [])
    
    # Step 1: 기존 테이블 중 master_anchor를 가진 테이블 찾기
    # 두 가지 소스 모두 검색: file_tags (메타데이터 파일) + column_metadata (인덱싱된 테이블)
    tables_with_master = []
    
    # 1-A: file_tags에서 검색
    for fp, tag_info in file_tags.items():
        if tag_info.get("type") != "transactional_data":
            continue
        
        table_name = os.path.basename(fp).replace(".csv", "").replace(".CSV", "")
        columns = tag_info.get("columns", [])
        
        if master_anchor in columns:
            tables_with_master.append({
                "table_name": table_name,
                "columns": columns,
                "file_path": fp,
                "source": "file_tags"
            })
    
    # 1-B: column_metadata에서 검색 (인덱싱된 테이블)
    for table_name, col_info in column_metadata.items():
        # 이미 file_tags에서 찾은 테이블은 제외
        if any(t["table_name"] == table_name for t in tables_with_master):
            continue
        
        columns = list(col_info.keys())
        
        if master_anchor in columns:
            tables_with_master.append({
                "table_name": table_name,
                "columns": columns,
                "file_path": None,
                "source": "column_metadata"
            })
    
    if not tables_with_master:
        print(f"   ⚠️ Master anchor '{master_anchor}'를 가진 테이블이 없음")
        return None
    
    print(f"   ✅ Master anchor '{master_anchor}'를 가진 테이블 발견:")
    for t in tables_with_master:
        print(f"      - {t['table_name']} (source: {t['source']})")
    
    print(f"   - Master anchor '{master_anchor}'를 가진 테이블: {[t['table_name'] for t in tables_with_master]}")
    
    # Step 2: 현재 테이블과 공통 컬럼이 있는 테이블 찾기
    potential_links = []
    for table_info in tables_with_master:
        common_cols = set(local_cols) & set(table_info["columns"])
        # master_anchor 자체는 제외 (이미 MATCH 체크에서 실패했으므로)
        common_cols.discard(master_anchor)
        
        if common_cols:
            potential_links.append({
                "via_table": table_info["table_name"],
                "common_columns": list(common_cols),
                "via_table_columns": table_info["columns"]
            })
    
    if not potential_links:
        print(f"   ⚠️ 공통 컬럼을 가진 테이블이 없음")
        return None
    
    print(f"   - 잠재적 FK 연결: {[(l['via_table'], l['common_columns']) for l in potential_links]}")
    
    # Step 3: LLM에게 FK 관계 확인 요청
    prompt = f"""You are a Database Schema Expert analyzing medical data relationships.

[TASK]
Determine if a Foreign Key (FK) relationship exists between two tables.

[CURRENT TABLE]
- Table Name: {current_table}
- Columns: {local_cols}
- MISSING: Does NOT have '{master_anchor}' column

[MASTER ANCHOR]
- Master Anchor Column: '{master_anchor}' (Project's main patient identifier)

[POTENTIAL LINK TABLES]
{json.dumps(potential_links, indent=2)}

[QUESTION]
Can '{current_table}' be linked to '{master_anchor}' through a common column in another table?

For example:
- If current_table has 'caseid' and via_table has both 'caseid' and 'subjectid'
- Then: current_table.caseid → via_table.caseid (FK) → via_table.subjectid (Master)

[RESPONSE FORMAT - JSON ONLY]
{{
    "can_link": true or false,
    "local_column": "column name in current table (FK column)",
    "via_table": "table name that has both columns",
    "via_column": "column name in via_table (same as local_column)",
    "relation_type": "N:1" or "1:N" or "1:1",
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation of the FK relationship",
    "fk_path": ["current_table.local_column", "via_table.via_column", "via_table.master_anchor"]
}}

If no valid FK relationship can be established, return:
{{
    "can_link": false,
    "reasoning": "Explanation why FK cannot be established"
}}
"""
    
    try:
        result = _get_llm_client().ask_json(prompt)
        
        if not result.get("can_link", False):
            print(f"   ❌ FK 관계 없음: {result.get('reasoning', 'No reason provided')}")
            return None
        
        confidence = result.get("confidence", 0.5)
        local_column = result.get("local_column")
        via_table = result.get("via_table")
        via_column = result.get("via_column")
        fk_path = result.get("fk_path", [])
        reasoning = result.get("reasoning", "")
        
        print(f"   ✅ FK 관계 발견!")
        print(f"      - 경로: {' → '.join(fk_path)}")
        print(f"      - 확신도: {confidence:.0%}")
        print(f"      - 근거: {reasoning}")
        
        return {
            "status": "FK_LINK",
            "local_column": local_column,
            "via_table": via_table,
            "via_column": via_column,
            "master_anchor": master_anchor,
            "fk_path": fk_path,
            "relation_type": result.get("relation_type", "N:1"),
            "confidence": confidence,
            "reasoning": reasoning
        }
        
    except Exception as e:
        print(f"   ⚠️ FK 추론 LLM 오류: {e}")
        return None


def should_request_human_review(
    file_path: str,
    issue_type: str,
    context: Dict[str, Any],
    rule_based_confidence: float = 1.0
) -> Dict[str, Any]:
    """
    [Helper] Human Review가 필요한지 판단 (Rule + LLM Hybrid)
    """
    filename = os.path.basename(file_path)
    
    # === 1단계: Rule-based 판단 ===
    threshold = _get_threshold_for_issue(issue_type)
    
    rule_decision = {
        "needs_review": rule_based_confidence < threshold,
        "reason": f"Confidence {rule_based_confidence:.1%} < Threshold {threshold:.1%}",
        "confidence": rule_based_confidence
    }
    
    if not HumanReviewConfig.USE_LLM_FOR_REVIEW_DECISION:
        print(f"   [Rule-only] {issue_type}: needs_review={rule_decision['needs_review']}")
        return rule_decision
    
    # === 2단계: LLM 기반 판단 ===
    if rule_based_confidence < HumanReviewConfig.LLM_SKIP_CONFIDENCE_THRESHOLD:
        print(f"   [Rule] Low confidence ({rule_based_confidence:.1%}), skipping LLM check")
        return rule_decision
    
    llm_decision = ask_llm_for_review_decision(
        filename=filename,
        issue_type=issue_type,
        context=context,
        rule_confidence=rule_based_confidence
    )
    
    # === 3단계: Rule과 LLM 결과 종합 ===
    final_needs_review = rule_decision["needs_review"] or llm_decision.get("needs_review", False)
    
    combined_reason = []
    if rule_decision["needs_review"]:
        combined_reason.append(f"Rule: {rule_decision['reason']}")
    if llm_decision.get("needs_review"):
        combined_reason.append(f"LLM: {llm_decision.get('reason', 'LLM recommended review')}")
    
    result = {
        "needs_review": final_needs_review,
        "reason": " | ".join(combined_reason) if combined_reason else "No issues detected",
        "confidence": rule_based_confidence,
        "llm_opinion": llm_decision.get("reason", "N/A")
    }
    
    print(f"   [Hybrid] {issue_type}: needs_review={final_needs_review}")
    
    return result


def _get_threshold_for_issue(issue_type: str) -> float:
    """이슈 유형별 Threshold 반환"""
    thresholds = {
        "metadata_classification": HumanReviewConfig.METADATA_CONFIDENCE_THRESHOLD,
        "anchor_detection": HumanReviewConfig.ANCHOR_CONFIDENCE_THRESHOLD,
        "anchor_conflict": HumanReviewConfig.ANCHOR_CONFIDENCE_THRESHOLD,
        "general": HumanReviewConfig.FILENAME_ANALYSIS_CONFIDENCE_THRESHOLD
    }
    return thresholds.get(issue_type, HumanReviewConfig.DEFAULT_CONFIDENCE_THRESHOLD)


def ask_llm_for_review_decision(
    filename: str,
    issue_type: str,
    context: Dict[str, Any],
    rule_confidence: float
) -> Dict[str, Any]:
    """LLM에게 Human Review 필요 여부 판단 요청"""
    
    prompt = f"""
    You are an AI assistant helping with medical data processing.
    Based on the following situation, decide if human intervention is needed.

    [Situation]
    - File: {filename}
    - Issue Type: {issue_type}
    - Rule-based Confidence: {rule_confidence:.1%}
    - Context: {json.dumps(context, ensure_ascii=False, default=str)[:500]}...

    [Decision Criteria]
    Return "needs_review": true if:
    1. The context shows ambiguous or conflicting information
    2. Critical decisions might affect data integrity
    3. Domain expertise is clearly needed
    4. Multiple valid interpretations exist

    Respond with JSON only:
    {{
        "needs_review": true or false,
        "reason": "Brief explanation"
    }}
    """
    
    try:
        result = _get_llm_client().ask_json(prompt)
        return {
            "needs_review": result.get("needs_review", False),
            "reason": result.get("reason", "LLM did not provide reason")
        }
    except Exception as e:
        print(f"   ⚠️ [LLM Review Decision] Error: {e}")
        return {"needs_review": False, "reason": f"LLM error: {str(e)}"}


def ask_llm_is_metadata(context: dict) -> dict:
    """
    [LLM] Determine if file is metadata
    """
    cached = _get_llm_cache().get("metadata_detection", context)
    if cached:
        return cached
    
    prompt = f"""
You are a Data Classification Expert.

I have pre-processed file information using rules. Based on these facts, determine if this is METADATA or TRANSACTIONAL DATA.

[PRE-PROCESSED FILE INFORMATION]
Filename: {context['filename']}
Parsed Name Parts: {context['name_parts']}
Base Name: {context['base_name']}
Extension: {context['extension']}
Number of Columns: {context['num_columns']}
Columns: {context['columns']}

[PRE-PROCESSED SAMPLE DATA]
{json.dumps(context['sample_data'], indent=2)}

[DEFINITION]
- METADATA file: Describes OTHER data (column definitions, parameter lists, codebooks)
- TRANSACTIONAL DATA: Actual records/measurements

[OUTPUT FORMAT - JSON ONLY]
{{
    "is_metadata": true or false,
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation",
    "indicators": {{
        "filename_hint": "strong/weak/none",
        "structure_hint": "dictionary-like/tabular/unclear",
        "content_type": "descriptive/transactional/mixed"
    }}
}}
"""
    
    try:
        result = _get_llm_client().ask_json(prompt)
        _get_llm_cache().set("metadata_detection", context, result)
        
        confidence = result.get("confidence", 0.0)
        if confidence < HumanReviewConfig.METADATA_DETECTION_CONFIDENCE_THRESHOLD:
            print(f"⚠️  [Metadata Detection] Low confidence ({confidence:.2%})")
        
        return result
        
    except Exception as e:
        print(f"❌ [Metadata Detection] LLM Error: {e}")
        return {
            "is_metadata": False,
            "confidence": 0.0,
            "reasoning": f"LLM error: {str(e)}",
            "indicators": {},
            "needs_human_review": True
        }

