# src/agents/helpers/llm_helpers.py
"""
LLM 관련 헬퍼 함수들 - 시맨틱 분석, 리뷰 판단 등
"""

import os
import json
from typing import Dict, Any, List, Optional, Union

from src.agents.state import ColumnSchema
from src.agents.models import (
    ColumnSchemaResult,
    ColumnAnalysisResponse,
    EntityAnalysisResult,
    LinkableColumnInfo,
    EntityRelationType,
    safe_parse_entity,
)
from src.utils.llm_client import get_llm_client
from src.utils.ontology_manager import get_ontology_manager
from src.utils.llm_cache import get_llm_cache
from src.config import HumanReviewConfig, LLMConfig

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




# =============================================================================
# Entity Understanding
# =============================================================================

def analyze_entity_with_llm(
    metadata: Dict[str, Any],
    project_context: Dict[str, Any] = None,
    user_feedback: str = None,
    ontology_context: Dict[str, Any] = None,
    conversation_history: List[Dict] = None
) -> EntityAnalysisResult:
    """
    [LLM Decides] 테이블/Signal 파일의 Entity 구조를 이해합니다.
    
    Tabular와 Signal 파일 모두 처리 (공통 컨텍스트 + 타입별 프롬프트)
    
    Args:
        metadata: Processor에서 추출한 메타데이터 (tabular 또는 signal)
        project_context: 프로젝트 전역 컨텍스트
        user_feedback: 사용자 피드백 (재실행 시)
        ontology_context: 온톨로지 컨텍스트 (용어 정의 등)
        conversation_history: 이전 대화 기록
    
    Returns:
        EntityAnalysisResult: Entity 이해 결과
    """
    import re
    
    # 기본 메타데이터 추출
    columns = metadata.get("columns", [])
    column_details = metadata.get("column_details", [])
    file_path = metadata.get("file_path", "")
    filename = os.path.basename(file_path)
    processor_type = metadata.get("processor_type", "tabular")
    
    if project_context is None:
        project_context = {}
    if ontology_context is None:
        ontology_context = {}
    if conversation_history is None:
        conversation_history = []
    
    # 프로젝트 컨텍스트
    known_entities = project_context.get("known_entities", {})
    master_identifier = project_context.get("master_entity_identifier")  # TODO: master_entity_identifier로 변경 필요
    definitions = ontology_context.get("definitions", {})
    processed_files = project_context.get("processed_signal_files", [])
    
    print(f"   🔍 [LLM] Entity 분석 중... (file: {filename}, type: {processor_type})")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 공통 컨텍스트 생성 (Tabular/Signal 동일)
    # ═══════════════════════════════════════════════════════════════════════════
    shared_context_parts = []
    
    # 1) Known entities (다른 테이블에서 발견된)
    if known_entities:
        entity_lines = [f"- {col}: {info.get('entity', 'unknown')}" 
                       for col, info in known_entities.items()]
        shared_context_parts.append(
            f"[KNOWN ENTITIES FROM OTHER TABLES]\n" + "\n".join(entity_lines)
        )
    
    # 2) 이전 대화 기록
    if conversation_history:
        turns = conversation_history.get("turns", []) if isinstance(conversation_history, dict) else conversation_history
        recent_turns = turns[-5:] if turns else []
        conv_lines = []
        for turn in recent_turns:
            role = turn.get("role", "unknown")
            content = turn.get("content", "")[:150]
            file_ref = turn.get("file", "")
            conv_lines.append(f"[{role}] {file_ref}: {content}")
        shared_context_parts.append(
            f"[PREVIOUS CONVERSATION]\n" + "\n".join(conv_lines)
        )
    
    # 3) 이전에 처리된 파일들 (Signal용이지만 Tabular에도 유용)
    if processed_files:
        proc_lines = [f"- {p['filename']}: {p['id_column']}={p.get('id_value', '?')}" 
                      for p in processed_files[-5:]]
        shared_context_parts.append(
            f"[PREVIOUSLY PROCESSED FILES]\n" + "\n".join(proc_lines)
        )
    
    # 4) 사용자 피드백 (최우선)
    if user_feedback:
        shared_context_parts.append(
            f"[USER FEEDBACK - HIGHEST PRIORITY]\n"
            f"사용자 피드백: \"{user_feedback}\"\n"
            f"이 피드백을 분석의 최우선으로 반영하세요."
        )
    
    shared_context = "\n\n".join(shared_context_parts)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 타입별 프롬프트 생성
    # ═══════════════════════════════════════════════════════════════════════════
    if processor_type == "signal":
        prompt = _build_signal_entity_prompt(metadata, shared_context, master_identifier)
    else:
        prompt = _build_tabular_entity_prompt(metadata, shared_context, master_identifier, definitions)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # LLM 호출 및 결과 파싱 (공통)
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        response = _get_llm_client().ask_json(prompt)
        
        if isinstance(response, str):
            response = safe_parse_entity(response.strip()) or {}
        
        if "error" in response:
            print(f"   ⚠️ LLM error: {response.get('error')}")
            return _create_default_entity_result(columns, filename, processor_type)
        
        # LinkableColumnInfo 객체로 변환
        linkable_cols = []
        for col_info in response.get("linkable_columns", []):
            try:
                relation_type = col_info.get("relation_type", "reference")
                if isinstance(relation_type, str) and relation_type in ["self", "parent", "child", "sibling", "reference"]:
                    rel_enum = EntityRelationType(relation_type)
                else:
                    rel_enum = EntityRelationType.REFERENCE
                    
                linkable_cols.append(LinkableColumnInfo(
                    column_name=col_info.get("column_name", ""),
                    represents_entity=col_info.get("represents_entity", "unknown"),
                    represents_entity_kr=col_info.get("represents_entity_kr", ""),
                    relation_type=rel_enum,
                    cardinality=col_info.get("cardinality", "N:1"),
                    is_primary_identifier=col_info.get("is_primary_identifier", False)
                ))
            except Exception as e:
                print(f"   ⚠️ LinkableColumn parse error: {e}")
        
        # entity_identifier 결정
        entity_identifier = response.get("entity_identifier") or response.get("id_column")
        if not entity_identifier:
            entity_identifier = columns[0] if columns else "id"
        
        # confidence 계산
        confidence = float(response.get("confidence", 0.7))
        
        # 이전 처리 기록이 있으면 confidence 상향 (패턴 학습됨)
        if processed_files and processor_type == "signal":
            confidence = max(confidence, 0.9)
        
        needs_review = confidence < HumanReviewConfig.DEFAULT_CONFIDENCE_THRESHOLD
        
        # Signal 파일인 경우 id_value 추출 (파일명에서 LLM이 추론한 값)
        id_value = response.get("id_value") if processor_type == "signal" else None
        
        result = EntityAnalysisResult(
            row_represents=response.get("row_represents", "unknown"),
            row_represents_kr=response.get("row_represents_kr", "알 수 없음"),
            entity_identifier=entity_identifier,
            linkable_columns=linkable_cols,
            hierarchy_explanation=response.get("hierarchy_explanation", ""),
            confidence=confidence,
            reasoning=response.get("reasoning", ""),
            status="CONFIRMED" if not needs_review else "NEEDS_REVIEW",
            needs_human_confirmation=needs_review,
            user_feedback_applied=user_feedback,
            id_value=id_value
        )
        
        print(f"   ✅ [LLM] Entity 분석 완료: {result.row_represents} (identifier: {result.entity_identifier}, {confidence:.0%})")
        return result
        
    except Exception as e:
        print(f"   ❌ [LLM] Entity 분석 실패: {e}")
        return _create_default_entity_result(columns, filename, processor_type)


def _build_tabular_entity_prompt(
    metadata: Dict[str, Any],
    shared_context: str,
    master_identifier: str,
    definitions: Dict[str, Any]
) -> str:
    """Tabular 파일용 Entity 분석 프롬프트 생성"""
    columns = metadata.get("columns", [])
    column_details = metadata.get("column_details", [])
    filename = os.path.basename(metadata.get("file_path", ""))
    
    # 컬럼 정보 요약
    column_summary = _build_column_summary_for_entity(columns, column_details)
    
    # 온톨로지 힌트
    ontology_hints = ""
    if definitions:
        relevant_defs = {k: v for k, v in list(definitions.items())[:10]}
        if relevant_defs:
            def_lines = []
            for k, v in relevant_defs.items():
                if isinstance(v, dict):
                    def_text = v.get('enriched_definition', v.get('definition', ''))
                else:
                    def_text = str(v) if v else ''
                def_lines.append(f"- {k}: {def_text[:100]}")
            ontology_hints = f"\n[ONTOLOGY HINTS]\n" + "\n".join(def_lines)
    
    return f"""You are analyzing a **TABULAR DATA FILE** (CSV/Excel with rows and columns).

[TASK]
Analyze this table and answer:
1. **row_represents**: What does each row represent? (e.g., "surgery", "patient", "lab_result")
2. **entity_identifier**: Which column uniquely identifies that entity?
3. **linkable_columns**: Which columns can be used to JOIN with other tables?
4. **hierarchy**: Entity relationships (e.g., patient → surgery is 1:N)

[FILE INFORMATION]
- Data Type: TABULAR (structured rows and columns)
- Filename: {filename}
- Total columns: {len(columns)}
- Master Identifier: {master_identifier or 'Not yet determined'}

[COLUMNS DETAIL]
{column_summary}
{ontology_hints}

{shared_context}

[OUTPUT FORMAT - JSON ONLY]
{{
    "row_represents": "surgery|patient|lab_result|measurement|other",
    "row_represents_kr": "수술 기록|환자 정보|검사 결과|측정값|기타",
    "entity_identifier": "the column name that uniquely identifies each row",
    "linkable_columns": [
        {{
            "column_name": "caseid",
            "represents_entity": "surgery",
            "represents_entity_kr": "수술",
            "relation_type": "self|parent|child|reference",
            "cardinality": "1:1|1:N|N:1",
            "is_primary_identifier": true|false
        }}
    ],
    "hierarchy_explanation": "Natural language explanation of entity relationships",
    "confidence": 0.0-1.0,
    "reasoning": "Detailed reasoning"
}}

RULES:
1. User feedback has HIGHEST priority
2. relation_type: "self"=identifies this row, "parent"=links to higher entity, "reference"=lookup
3. entity_identifier should have relation_type="self"
"""


def _build_signal_entity_prompt(
    metadata: Dict[str, Any],
    shared_context: str,
    master_identifier: str
) -> str:
    """Signal 파일용 Entity 분석 프롬프트 생성"""
    import re
    
    filename_info = metadata.get("filename_info", {})
    file_path = metadata.get("file_path", "")
    filename = os.path.basename(file_path)
    name_without_ext = filename_info.get("name_without_ext", os.path.splitext(filename)[0])
    
    # 파일명에서 숫자 추출
    numbers = re.findall(r'\d+', name_without_ext)
    potential_id = int(numbers[-1]) if numbers else None
    
    # 트랙 정보
    columns = metadata.get("columns", [])  # 트랙명 리스트
    column_details = metadata.get("column_details", {})  # 트랙별 상세 정보
    duration = metadata.get("duration", 0)
    
    # 트랙 상세 정보 포맷팅
    track_summary = _format_signal_tracks(columns, column_details)
    
    return f"""You are analyzing a **SIGNAL DATA FILE** (time-series physiological measurements).

[TASK]
For this signal file:
1. What ID links this file to other data? (usually extracted from filename)
2. What entity does this file represent measurements for?

[FILE INFORMATION]
- Data Type: SIGNAL (time-series waveforms/measurements)
- Filename: {filename}
- Filename without extension: {name_without_ext}
- Numbers found in filename: {numbers}
- Potential ID from filename: {potential_id}
- Master Identifier: {master_identifier or 'Not yet determined'}

[SIGNAL TRACKS]
- Total tracks: {len(columns)}
- Duration: {duration:.1f} seconds
{track_summary}

{shared_context}

[OUTPUT FORMAT - JSON ONLY]
{{
    "row_represents": "time_series_measurement",
    "row_represents_kr": "시계열 측정값",
    "entity_identifier": "the column/ID that links this file (e.g., caseid)",
    "id_value": {potential_id},
    "linkable_columns": [
        {{
            "column_name": "caseid",
            "represents_entity": "case/surgery",
            "represents_entity_kr": "케이스/수술",
            "relation_type": "parent",
            "cardinality": "N:1",
            "is_primary_identifier": false
        }}
    ],
    "hierarchy_explanation": "This signal file contains measurements for case/surgery ID {potential_id}",
    "confidence": 0.0-1.0,
    "reasoning": "How you determined the ID from filename"
}}

IMPORTANT RULES:
1. User feedback has HIGHEST priority
2. If previous signal file decisions exist in conversation, follow the SAME PATTERN
   (e.g., if "0001.vital → caseid=1" was confirmed, then "0002.vital → caseid=2")
3. Extract ID value from filename (e.g., "0001.vital" → caseid: 1, "0002.vital" → caseid: 2)
4. confidence should be HIGH (0.9+) if pattern is clear from previous decisions
"""


def _format_signal_tracks(columns: List[str], column_details: Dict[str, Any]) -> str:
    """Signal 트랙 정보를 포맷팅"""
    if not columns:
        return "- No tracks available"
    
    lines = []
    for track_name in columns[:20]:  # 최대 20개만
        detail = column_details.get(track_name, {})
        if isinstance(detail, dict):
            unit = detail.get("unit", "")
            sr = detail.get("sample_rate", 0)
            col_type = detail.get("column_type", "unknown")
            lines.append(f"  - {track_name}: {col_type}, {sr}Hz, unit={unit}")
        else:
            lines.append(f"  - {track_name}")
    
    if len(columns) > 20:
        lines.append(f"  ... and {len(columns) - 20} more tracks")
    
    return "\n".join(lines)


def _build_column_summary_for_entity(
    columns: List[str],
    column_details: List[Dict]
) -> str:
    """Entity 분석용 컬럼 요약 생성"""
    lines = []
    
    if isinstance(column_details, list) and column_details:
        for col_info in column_details[:25]:
            col_name = col_info.get('column_name', '')
            col_type = col_info.get('column_type', 'unknown')
            dtype = col_info.get('dtype', 'unknown')
            n_unique = col_info.get('n_unique', '?')
            n_total = col_info.get('n_total', '?')
            
            # Cardinality hint
            cardinality_hint = ""
            if n_unique != '?' and n_total != '?':
                try:
                    ratio = int(n_unique) / int(n_total)
                    if ratio > 0.95:
                        cardinality_hint = " [LIKELY IDENTIFIER - high uniqueness]"
                    elif ratio < 0.01:
                        cardinality_hint = " [LIKELY CATEGORICAL - low uniqueness]"
                except:
                    pass
            
            if col_type == 'categorical':
                unique_vals = col_info.get('unique_values', [])[:5]
                lines.append(
                    f"- '{col_name}' | {dtype} | {n_unique} unique / {n_total} rows | "
                    f"samples: {unique_vals}{cardinality_hint}"
                )
            else:
                samples = col_info.get('samples', [])[:3]
                lines.append(
                    f"- '{col_name}' | {dtype} | {n_unique} unique | samples: {samples}{cardinality_hint}"
                )
    else:
        for col in columns[:25]:
            lines.append(f"- '{col}'")
    
    if len(columns) > 25:
        lines.append(f"... and {len(columns) - 25} more columns")
    
    return "\n".join(lines)


def _create_default_entity_result(columns: List[str], filename: str, processor_type: str = "tabular") -> EntityAnalysisResult:
    """기본 Entity 결과 생성 (LLM 실패 시)"""
    import re
    
    # Signal 파일의 경우: 파일명에서 ID 추출 시도
    if processor_type == "signal":
        name_without_ext = os.path.splitext(filename)[0]
        numbers = re.findall(r'\d+', name_without_ext)
        identifier = "caseid"  # Signal은 보통 caseid로 연결
        id_value = int(numbers[-1]) if numbers else None  # 파일명에서 ID 값 추출
        
        return EntityAnalysisResult(
            row_represents="time_series_measurement",
            row_represents_kr="시계열 측정값",
            entity_identifier=identifier,
            linkable_columns=[
                LinkableColumnInfo(
                    column_name=identifier,
                    represents_entity="case",
                    represents_entity_kr="케이스",
                    relation_type=EntityRelationType.PARENT,
                    cardinality="N:1",
                    is_primary_identifier=False
                )
            ],
            hierarchy_explanation=f"Signal file - default fallback for {filename}",
            confidence=0.3,
            reasoning=f"Default fallback for signal file {filename}",
            status="NEEDS_REVIEW",
            needs_human_confirmation=True,
            id_value=id_value
        )
    
    # Tabular 파일의 경우: 첫 번째 컬럼을 identifier로 가정
    identifier = columns[0] if columns else "id"
    
    # ID로 보이는 컬럼 찾기
    id_candidates = [c for c in columns if 'id' in c.lower()]
    if id_candidates:
        identifier = id_candidates[0]
    
    return EntityAnalysisResult(
        row_represents="unknown",
        row_represents_kr="알 수 없음",
        entity_identifier=identifier,
        linkable_columns=[
            LinkableColumnInfo(
                column_name=identifier,
                represents_entity="unknown",
                represents_entity_kr="알 수 없음",
                relation_type=EntityRelationType.SELF,
                cardinality="1:1",
                is_primary_identifier=True
            )
        ],
        hierarchy_explanation="Unable to determine entity structure",
        confidence=0.3,
        reasoning=f"Default fallback for {filename}",
        status="NEEDS_REVIEW",
        needs_human_confirmation=True
    )


def analyze_columns_with_llm(
    columns: List[str], 
    sample_data: Any, 
    entity_context: Dict,
    user_feedback: str = None,
    ontology_context: Dict[str, Any] = None
) -> List[ColumnSchemaResult]:
    """
    [Helper] Analyze column meaning, data type, PII status, units, etc. using LLM
    
    Args:
        columns: 분석할 컬럼명 목록
        sample_data: 샘플 데이터 (list 또는 dict)
        entity_context: Entity Identification 정보
        user_feedback: 사용자가 제공한 컬럼/데이터 설명
        ontology_context: 온톨로지 컨텍스트 (메타데이터에서 추출한 용어 정의)
    
    Returns:
        List[ColumnSchemaResult]: Pydantic 모델로 구조화된 컬럼 분석 결과
    """
    if ontology_context is None:
        ontology_context = {}
    
    definitions = ontology_context.get("definitions", {})
    
    # User feedback context
    user_context = ""
    if user_feedback:
        user_context = f"""
    [USER FEEDBACK - PRIORITIZE THIS INFORMATION]
    The user has provided the following context about this data:
    "{user_feedback}"
    
    Use this information to improve your analysis accuracy.
    """
    
    # Ontology definitions context (메타데이터에서 추출한 용어 정의)
    definitions_context = ""
    if definitions:
        relevant_defs = []
        for col in columns[:30]:  # 상위 30개 컬럼
            col_lower = col.lower()
            for def_key, def_value in definitions.items():
                if col_lower == def_key.lower() or col_lower in def_key.lower():
                    relevant_defs.append(f"    - {def_key}: {str(def_value)[:150]}")
                    break
        
        if relevant_defs:
            definitions_context = f"""
    [ONTOLOGY DEFINITIONS - IMPORTANT: Use these as ground truth]
    The following definitions were extracted from the dataset's official metadata files.
    Prioritize these over guessing:
{chr(10).join(relevant_defs)}
    """
    
    # Context summary for LLM
    prompt = f"""
    You are a Medical Data Ontologist specializing in clinical database design.
    Analyze the columns of a medical dataset and provide DETAILED metadata.
    {user_context}
    {definitions_context}
    [Context]
    - Entity Identifier Column: {entity_context.get('column_name')}
    - Is Time Series: {entity_context.get('is_time_series')}
    
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
    from src.config import LLMConfig
    
    # 컬럼 분석은 value_mappings 등으로 토큰이 많이 필요할 수 있음
    response = _get_llm_client().ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS_COLUMN_ANALYSIS)
    
    if isinstance(response, dict) and "columns" in response:
        result_list = response["columns"]
    elif isinstance(response, list):
        result_list = response
    else:
        result_list = []

    final_schema: List[ColumnSchemaResult] = []
    for idx, item in enumerate(result_list):
        original = item.get("original_name") or (columns[idx] if idx < len(columns) else "unknown")
        
        # value_mappings 처리: dict여야 하고, 비어있으면 null로 처리
        value_mappings = item.get("value_mappings")
        if value_mappings is not None and not isinstance(value_mappings, dict):
            value_mappings = None
        if isinstance(value_mappings, dict) and len(value_mappings) == 0:
            value_mappings = None
        
        # Pydantic 모델로 변환 (자동 검증)
        final_schema.append(ColumnSchemaResult(
            original_name=original,
            inferred_name=item.get("inferred_name", original),
            full_name=item.get("full_name", item.get("inferred_name", original)),
            description=item.get("description", ""),
            description_kr=item.get("description_kr", ""),
            data_type=item.get("data_type", "VARCHAR"),
            semantic_type=item.get("semantic_type"),
            column_type=item.get("column_type"),
            unit=item.get("unit"),
            typical_range=item.get("typical_range"),
            is_pii=item.get("is_pii", False),
            confidence=item.get("confidence", 0.5),
            value_mappings=value_mappings
        ))
        
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
    local_identification_info: Dict, 
    project_context: Dict,
    ontology_context: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    [Helper] Compare current file data with project Global Entity Identifier info (using LLM)
    
    Returns:
    - MATCH: 완전 일치
    - CONFLICT/MISSING: 연결 불가
    """
    master_name = project_context["master_entity_identifier"]
    local_cols = local_metadata.get("columns", [])
    local_candidate = local_identification_info.get("target_column")
    
    # 1. 이름이 완전히 같은 경우 (Fast Path)
    if master_name in local_cols:
        return {"status": "MATCH", "target_column": master_name, "message": "Exact name match"}

    # 2. 로컬 후보가 없는 경우
    if not local_candidate:
        return {
            "status": "MISSING",
            "target_column": None,
            "message": f"No identifier candidate found. Master identifier '{master_name}' not found in columns: {local_cols}"
        }

    # 3. LLM을 통한 의미론적 비교
    prompt = f"""
    You are a Medical Data Integration Agent.
    Check if the new file contains the Project's Master Entity Identifier (Patient ID).

    [Project Context / Global Master]
    - Master Entity Identifier: '{master_name}'
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
        "entity_detection": HumanReviewConfig.ANCHOR_CONFIDENCE_THRESHOLD,
        "entity_conflict": HumanReviewConfig.ANCHOR_CONFIDENCE_THRESHOLD,
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
        
        # Check for error response from ask_json
        if "error" in result:
            error_msg = result.get("error", "Unknown error")
            print(f"❌ [Metadata Detection] LLM returned error: {error_msg}")
            return {
                "is_metadata": False,
                "confidence": 0.0,
                "reasoning": f"LLM error: {error_msg}",
                "indicators": {},
                "needs_human_review": True
            }
        
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

