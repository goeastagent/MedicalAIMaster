# src/agents/nodes/data_semantic.py
"""
Phase 6: Data Semantic Analysis Node

데이터 파일(is_metadata=false)의 컬럼을 의미론적으로 분석하고
data_dictionary와 연결합니다.

주요 기능:
- LLM을 사용해 각 컬럼의 semantic_name, unit, description 추론
- data_dictionary의 parameter_key와 매칭 시도
- column_metadata에 결과 저장 (dict_entry_id, dict_match_status)
- 파일당 컬럼 수가 많으면 배치로 분할하여 LLM 호출
"""

import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from ..state import AgentState
from ..models.llm_responses import (
    ColumnSemanticResult,
    DataSemanticResponse,
    DataSemanticResult,
)
from src.database import (
    FileRepository,
    ColumnRepository,
    DictionaryRepository,
)
from src.utils.llm_client import get_llm_client
from src.config import Phase6Config, LLMConfig


# Repository 싱글톤
_file_repo = None
_col_repo = None
_dict_repo = None

def _get_repositories():
    """Repository 인스턴스들 반환"""
    global _file_repo, _col_repo, _dict_repo
    if _file_repo is None:
        _file_repo = FileRepository()
        _col_repo = ColumnRepository()
        _dict_repo = DictionaryRepository()
    return _file_repo, _col_repo, _dict_repo


# =============================================================================
# LLM Prompt Template
# =============================================================================

COLUMN_SEMANTIC_PROMPT = """You are a Medical Data Expert analyzing clinical data columns.

[Task]
Analyze each column and provide semantic information.
Use the Parameter Dictionary and column statistics to make accurate judgments.

{dict_section}

[File: {file_name}]
Type: {file_type}
Rows: {row_count}

[Columns to Analyze with Statistics]
{columns_info}

[CRITICAL RULES for dict_entry_key]
1. MUST be EXACTLY one of the keys from "EXACT Parameter Keys" above (if provided)
2. Copy the key exactly as shown (including "/" and special characters)
3. If no matching key exists → set to null
4. If uncertain (confidence < 0.7) → set to null
5. Use column statistics (min/max/values) to help identify the correct match

[Output Format]
Return ONLY valid JSON (no markdown, no explanation):
{{
  "columns": [
    {{
      "original_name": "age",
      "semantic_name": "Age",
      "unit": "years",
      "description": "Patient age at time of surgery",
      "concept_category": "Demographics",
      "dict_entry_key": "age",
      "match_confidence": 0.99,
      "reasoning": "Exact name match, values 20-90 consistent with age"
    }},
    {{
      "original_name": "unknown_col",
      "semantic_name": "Unknown Parameter",
      "unit": null,
      "description": "Unable to determine meaning",
      "concept_category": "Other",
      "dict_entry_key": null,
      "match_confidence": 0.0,
      "reasoning": "No matching parameter found in dictionary"
    }}
  ]
}}
"""

DICT_SECTION_TEMPLATE = """[EXACT Parameter Keys - Use these values ONLY]
{dict_keys_list}

[Parameter Definitions]
{dict_context}
"""

DICT_SECTION_EMPTY = """[Note]
No parameter dictionary is available for this dataset.
Infer semantic meaning from column names and statistics using your medical knowledge.
Set dict_entry_key to null for all columns.
"""


# =============================================================================
# Helper Functions (Repository 사용)
# =============================================================================

def _load_dictionary_with_context() -> Tuple[List[Dict], str, str, Dict[str, str]]:
    """
    data_dictionary 로드 + LLM context 생성 (Repository 사용)
    
    Returns:
        (dictionary_entries, dict_keys_list, dict_context, key_to_id_map)
    """
    _, _, dict_repo = _get_repositories()
    
    dictionary = dict_repo.get_all_entries()
    dict_keys_list, dict_context, key_to_id_map = dict_repo.build_llm_context()
    
    return dictionary, dict_keys_list, dict_context, key_to_id_map


# Legacy 함수 유지 (하위 호환성)
def _load_data_dictionary(db) -> List[Dict[str, Any]]:
    """
    data_dictionary 테이블에서 모든 엔트리 로드 (Legacy - Repository 사용)
    """
    _, _, dict_repo = _get_repositories()
    return dict_repo.get_all_entries()


def _build_dict_context(dictionary: List[Dict]) -> Tuple[str, str, Dict[str, str]]:
    """
    data_dictionary를 LLM context 문자열로 변환 (Legacy 호환)
    
    Returns:
        (dict_keys_list, dict_context, key_to_id_map)
    """
    if not dictionary:
        return "", "", {}
    
    # Key 목록 (정확한 매칭용)
    keys = [f'"{e["parameter_key"]}"' for e in dictionary]
    dict_keys_list = ", ".join(keys)
    
    # 상세 정의 (LLM이 의미 파악용)
    lines = []
    key_to_id_map = {}
    
    for entry in dictionary:
        key = entry['parameter_key']
        desc = entry['parameter_desc'] or ''
        unit = entry['parameter_unit'] or '-'
        extra = entry.get('extra_info', {})
        
        key_to_id_map[key] = entry['dict_id']
        
        line = f'- "{key}": {desc}'
        if unit and unit != '-':
            line += f' ({unit})'
        if extra:
            extra_items = list(extra.items())[:2]  # 최대 2개
            if extra_items:
                extra_str = ", ".join(f"{k}={v}" for k, v in extra_items)
                line += f' [{extra_str}]'
        lines.append(line)
    
    dict_context = "\n".join(lines)
    
    return dict_keys_list, dict_context, key_to_id_map


def _get_columns_with_stats(db, file_id: str) -> List[Dict]:
    """
    특정 파일의 컬럼 정보와 통계를 조회 (Repository 사용)
    
    Returns:
        List of column info dicts
    """
    _, col_repo, _ = _get_repositories()
    
    try:
        return col_repo.get_columns_with_stats(file_id)
    except Exception as e:
        print(f"   ⚠️ Error loading columns: {e}")
        return []


def _build_columns_info(columns: List[Dict], config: Phase6Config) -> str:
    """
    컬럼 정보 + 통계를 LLM context 문자열로 변환
    
    Args:
        columns: 컬럼 정보 리스트
        config: Phase6Config 설정 (표시 개수 제한)
    
    Returns:
        포맷된 컬럼 정보 문자열
    """
    lines = []
    
    for col in columns:
        name = col['original_name']
        dtype = col['data_type']
        col_type = col['column_type']
        info = col.get('column_info', {}) or {}
        dist = col.get('value_distribution', {}) or {}
        
        # 기본 정보
        line = f"- {name} ({dtype}, {col_type})"
        details = []
        
        # Continuous: min, max, mean
        if col_type == 'continuous':
            min_val = info.get('min')
            max_val = info.get('max')
            mean_val = info.get('mean')
            if min_val is not None and max_val is not None:
                range_str = f"range: [{min_val:.2f}, {max_val:.2f}]"
                if mean_val is not None:
                    range_str += f", mean: {mean_val:.2f}"
                details.append(range_str)
        
        # Categorical: unique values
        if col_type == 'categorical':
            unique_vals = dist.get('unique_values', [])
            n_unique = len(unique_vals)
            if n_unique > 0:
                max_show = config.MAX_UNIQUE_VALUES_DISPLAY
                if n_unique <= max_show:
                    details.append(f"values ({n_unique}): {unique_vals}")
                else:
                    details.append(f"values ({n_unique} unique): {unique_vals[:max_show]}...")
        
        # Datetime: date range
        if info.get('is_datetime'):
            min_dt = info.get('min_date')
            max_dt = info.get('max_date')
            if min_dt:
                details.append(f"date_range: [{min_dt}, {max_dt}]")
        
        # Samples
        samples = dist.get('samples', [])[:config.MAX_SAMPLES_DISPLAY]
        if samples:
            details.append(f"samples: {samples}")
        
        # 조합
        if details:
            line += "\n    " + "\n    ".join(details)
        
        lines.append(line)
    
    return "\n".join(lines)


# NOTE: _resolve_dict_entry_id 함수는 DictionaryRepository.resolve_dict_entry_id()로 이동됨


def _call_llm_for_semantic(
    llm_client,
    file_info: Dict,
    columns: List[Dict],
    dict_keys_list: str,
    dict_context: str,
    config: Phase6Config
) -> Optional[DataSemanticResponse]:
    """
    LLM을 호출하여 컬럼 시맨틱 분석 수행
    
    Args:
        llm_client: LLM 클라이언트
        file_info: 파일 정보 (file_name, file_type, row_count)
        columns: 분석할 컬럼 목록
        dict_keys_list: dictionary key 목록 문자열
        dict_context: dictionary 상세 정보 문자열
        config: Phase6Config 설정
    
    Returns:
        DataSemanticResponse or None
    """
    # Dictionary section 구성
    if dict_keys_list:
        dict_section = DICT_SECTION_TEMPLATE.format(
            dict_keys_list=dict_keys_list,
            dict_context=dict_context
        )
    else:
        dict_section = DICT_SECTION_EMPTY
    
    # Columns info 구성
    columns_info = _build_columns_info(columns, config)
    
    # Prompt 구성
    prompt = COLUMN_SEMANTIC_PROMPT.format(
        dict_section=dict_section,
        file_name=file_info.get('file_name', 'unknown'),
        file_type=file_info.get('file_type', 'tabular'),
        row_count=file_info.get('row_count', 'unknown'),
        columns_info=columns_info
    )
    
    try:
        response = llm_client.ask_json(
            prompt=prompt,
            max_tokens=LLMConfig.MAX_TOKENS_COLUMN_ANALYSIS
        )
        
        if not response:
            return None
        
        # Pydantic 모델로 변환
        columns_data = response.get('columns', [])
        column_results = []
        for col_data in columns_data:
            try:
                col_result = ColumnSemanticResult(**col_data)
                column_results.append(col_result)
            except Exception as e:
                print(f"   ⚠️ Error parsing column result: {e}")
                continue
        
        return DataSemanticResponse(
            columns=column_results,
            file_summary=response.get('file_summary')
        )
        
    except json.JSONDecodeError as e:
        print(f"   ❌ JSON parsing error: {e}")
        return None
    except Exception as e:
        print(f"   ❌ LLM call error: {e}")
        return None


def _update_column_metadata_batch(
    db,  # unused, 하위 호환성
    file_id: str,
    results: List[ColumnSemanticResult],
    key_to_id_map: Dict[str, str]
) -> Dict[str, int]:
    """
    column_metadata 테이블을 배치 업데이트 (Repository 사용)
    
    Args:
        db: DB 매니저 (unused, 하위 호환성)
        file_id: 파일 ID
        results: LLM 분석 결과 리스트
        key_to_id_map: {parameter_key: dict_id} 매핑
    
    Returns:
        통계 dict: {matched: n, not_found: n, null_from_llm: n}
    """
    _, col_repo, dict_repo = _get_repositories()
    
    # LLM 결과를 업데이트용 dict 리스트로 변환
    updates = []
    for result in results:
        # dict_entry_id 해석
        dict_id, status = dict_repo.resolve_dict_entry_id(
            result.dict_entry_key,
            key_to_id_map
        )
        
        updates.append({
            'original_name': result.original_name,
            'semantic_name': result.semantic_name,
            'unit': result.unit,
            'description': result.description,
            'concept_category': result.concept_category,
            'dict_entry_id': dict_id,
            'dict_match_status': status,
            'match_confidence': result.match_confidence
        })
    
    # Repository를 통해 일괄 업데이트
    return col_repo.batch_update_semantic_info(file_id, updates)


def _get_data_files_info(db, data_files: List[str]) -> List[Dict]:
    """
    데이터 파일들의 정보 조회 (Repository 사용)
    
    Args:
        db: DB 매니저 (unused, 하위 호환성)
        data_files: 파일 경로 목록
    
    Returns:
        파일 정보 리스트 (file_id, file_path, file_name, row_count 등)
    """
    if not data_files:
        return []
    
    file_repo, _, _ = _get_repositories()
    
    try:
        files_data = file_repo.get_files_by_paths(data_files)
        
        files = []
        for f in files_data:
            raw_stats = f.get('raw_stats', {})
            files.append({
                'file_id': f['file_id'],
                'file_path': f['file_path'],
                'file_name': f['file_name'],
                'file_type': f.get('processor_type') or 'tabular',
                'row_count': raw_stats.get('row_count', 'unknown')
            })
        
        return files
        
    except Exception as e:
        print(f"   ⚠️ Error loading file info: {e}")
        return []


# =============================================================================
# Main Node Function
# =============================================================================

def phase6_data_semantic_node(state: AgentState) -> AgentState:
    """
    Phase 6: Data Semantic Analysis Node
    
    데이터 파일의 컬럼을 의미론적으로 분석하고 data_dictionary와 연결
    
    Input State:
        - data_files: 분석할 데이터 파일 경로 목록
        - (DB) data_dictionary: Phase 5에서 생성된 parameter definitions
        - (DB) column_metadata: Phase 2에서 생성된 컬럼 정보 + 통계
    
    Output State:
        - phase6_result: DataSemanticResult
        - data_semantic_entries: 분석된 컬럼 정보 리스트
        - (DB) column_metadata 업데이트: semantic_name, unit, dict_entry_id 등
    """
    print("\n" + "="*60)
    print("🔬 Phase 6: Data Semantic Analysis")
    print("="*60)
    
    started_at = datetime.now().isoformat()
    config = Phase6Config
    
    # 데이터 파일 목록
    data_files = state.get('data_files', [])
    
    if not data_files:
        print("⚠️ No data files to analyze")
        return {
            **state,
            'phase6_result': DataSemanticResult(
                total_data_files=0,
                started_at=started_at,
                completed_at=datetime.now().isoformat()
            ).dict(),
            'data_semantic_entries': []
        }
    
    print(f"📁 Data files to analyze: {len(data_files)}")
    
    # LLM 클라이언트 초기화
    llm_client = get_llm_client()
    
    # 1. data_dictionary 로드 (Repository 사용)
    print("\n📖 Loading data dictionary...")
    dictionary, dict_keys_list, dict_context, key_to_id_map = _load_dictionary_with_context()
    print(f"   Found {len(dictionary)} parameter definitions")
    
    # 2. 파일 정보 조회 (Repository 사용)
    files_info = _get_data_files_info(None, data_files)  # db 파라미터는 더 이상 사용 안 함
    print(f"   Loaded info for {len(files_info)} files")
    
    # 결과 추적
    total_columns = 0
    total_matched = 0
    total_not_found = 0
    total_null_from_llm = 0
    columns_by_file = {}
    llm_calls = 0
    batches_processed = 0
    all_entries = []
    
    # 3. 파일별 처리
    for file_info in files_info:
        file_id = file_info['file_id']
        file_name = file_info['file_name']
        
        print(f"\n📄 Processing: {file_name}")
        
        # 컬럼 정보 로드 (Repository 사용)
        columns = _get_columns_with_stats(None, file_id)  # db 파라미터는 더 이상 사용 안 함
        n_cols = len(columns)
        print(f"   Columns: {n_cols}")
        
        if not columns:
            continue
        
        columns_by_file[file_name] = n_cols
        total_columns += n_cols
        
        # 배치 분할 (컬럼 수가 많으면)
        batch_size = config.COLUMN_BATCH_SIZE
        batches = [columns[i:i+batch_size] for i in range(0, n_cols, batch_size)]
        
        if len(batches) > 1:
            print(f"   Splitting into {len(batches)} batches (batch_size={batch_size})")
        
        file_results = []
        
        for batch_idx, batch_cols in enumerate(batches):
            if len(batches) > 1:
                print(f"   Batch {batch_idx + 1}/{len(batches)} ({len(batch_cols)} columns)")
            
            # LLM 호출
            response = _call_llm_for_semantic(
                llm_client,
                file_info,
                batch_cols,
                dict_keys_list,
                dict_context,
                config
            )
            llm_calls += 1
            batches_processed += 1
            
            if response and response.columns:
                # DB 업데이트
                stats = _update_column_metadata_batch(
                    None, file_id, response.columns, key_to_id_map  # db 파라미터는 더 이상 사용 안 함
                )
                
                total_matched += stats.get('matched', 0)
                total_not_found += stats.get('not_found', 0)
                total_null_from_llm += stats.get('null_from_llm', 0)
                
                file_results.extend([c.dict() for c in response.columns])
                
                print(f"   ✓ Analyzed {len(response.columns)} columns "
                      f"(matched: {stats.get('matched', 0)}, "
                      f"not_found: {stats.get('not_found', 0)}, "
                      f"null: {stats.get('null_from_llm', 0)})")
            else:
                print(f"   ⚠️ No results from LLM")
        
        # 결과 저장
        all_entries.extend(file_results)
    
    # 4. 최종 결과 구성
    completed_at = datetime.now().isoformat()
    
    result = DataSemanticResult(
        total_data_files=len(files_info),
        processed_files=len(files_info),
        total_columns_analyzed=total_columns,
        columns_matched=total_matched,
        columns_not_found=total_not_found,
        columns_null_from_llm=total_null_from_llm,
        columns_by_file=columns_by_file,
        batches_processed=batches_processed,
        llm_calls=llm_calls,
        started_at=started_at,
        completed_at=completed_at
    )
    
    print("\n" + "="*60)
    print("✅ Phase 6 Complete!")
    print(f"   Files processed: {result.processed_files}")
    print(f"   Columns analyzed: {result.total_columns_analyzed}")
    print(f"   Dictionary matches: {result.columns_matched}")
    print(f"   Not found in dict: {result.columns_not_found}")
    print(f"   Null from LLM: {result.columns_null_from_llm}")
    print(f"   LLM calls: {result.llm_calls}")
    print(f"   Batches: {result.batches_processed}")
    print("="*60)
    
    return {
        **state,
        'phase6_result': result.dict(),
        'data_semantic_entries': all_entries
    }


# =============================================================================
# Class-based Node (for NodeRegistry)
# =============================================================================

from ..base import BaseNode, LLMMixin, DatabaseMixin
from ..registry import register_node


@register_node
class DataSemanticNode(BaseNode, LLMMixin, DatabaseMixin):
    """
    Data Semantic Analysis Node (LLM-based)
    
    데이터 파일(is_metadata=false)의 컬럼을 의미론적으로 분석하고
    data_dictionary와 연결합니다.
    """
    
    name = "data_semantic"
    description = "데이터 파일 컬럼 의미 분석"
    order = 600
    requires_llm = True
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """기존 함수 위임"""
        return phase6_data_semantic_node(state)

