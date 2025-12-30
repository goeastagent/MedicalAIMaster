# src/agents/nodes/data_semantic.py
"""
Data Semantic Analysis Node

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
from ..base import BaseNode, LLMMixin, DatabaseMixin
from ..registry import register_node
from src.database import (
    FileRepository,
    ColumnRepository,
    DictionaryRepository,
)
from src.config import DataSemanticConfig, LLMConfig


# =============================================================================
# LLM Prompt Templates
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
# Class-based Node
# =============================================================================

@register_node
class DataSemanticNode(BaseNode, LLMMixin, DatabaseMixin):
    """
    Data Semantic Analysis Node (LLM-based)
    
    데이터 파일(is_metadata=false)의 컬럼을 의미론적으로 분석하고
    data_dictionary와 연결합니다.
    
    Input State:
        - data_files: 분석할 데이터 파일 경로 목록
        - (DB) data_dictionary: 이전 단계에서 생성된 parameter definitions
        - (DB) column_metadata: 이전 단계에서 생성된 컬럼 정보 + 통계
    
    Output State:
        - data_semantic_result: DataSemanticResult
        - data_semantic_entries: 분석된 컬럼 정보 리스트
        - (DB) column_metadata 업데이트: semantic_name, unit, dict_entry_id 등
    """
    
    name = "data_semantic"
    description = "데이터 파일 컬럼 의미 분석"
    order = 600
    requires_llm = True
    
    def __init__(self):
        super().__init__()
        self._file_repo: Optional[FileRepository] = None
        self._col_repo: Optional[ColumnRepository] = None
        self._dict_repo: Optional[DictionaryRepository] = None
    
    def _get_repositories(self) -> Tuple[FileRepository, ColumnRepository, DictionaryRepository]:
        """Repository 인스턴스들 반환 (lazy initialization)"""
        if self._file_repo is None:
            self._file_repo = FileRepository()
            self._col_repo = ColumnRepository()
            self._dict_repo = DictionaryRepository()
        return self._file_repo, self._col_repo, self._dict_repo
    
    def _load_dictionary_with_context(self) -> Tuple[List[Dict], str, str, Dict[str, str]]:
        """
        data_dictionary 로드 + LLM context 생성
        
        Returns:
            (dictionary_entries, dict_keys_list, dict_context, key_to_id_map)
        """
        _, _, dict_repo = self._get_repositories()
        
        dictionary = dict_repo.get_all_entries()
        dict_keys_list, dict_context, key_to_id_map = dict_repo.build_llm_context()
        
        return dictionary, dict_keys_list, dict_context, key_to_id_map
    
    def _get_columns_with_stats(self, file_id: str) -> List[Dict]:
        """
        특정 파일의 컬럼 정보와 통계를 조회
        
        Returns:
            List of column info dicts
        """
        _, col_repo, _ = self._get_repositories()
        
        try:
            return col_repo.get_columns_with_stats(file_id)
        except Exception as e:
            self.log(f"⚠️ Error loading columns: {e}", indent=1)
            return []
    
    def _build_columns_info(self, columns: List[Dict]) -> str:
        """
        컬럼 정보 + 통계를 LLM context 문자열로 변환
        
        Args:
            columns: 컬럼 정보 리스트
        
        Returns:
            포맷된 컬럼 정보 문자열
        """
        config = DataSemanticConfig
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
    
    def _call_llm_for_semantic(
        self,
        file_info: Dict,
        columns: List[Dict],
        dict_keys_list: str,
        dict_context: str
    ) -> Optional[DataSemanticResponse]:
        """
        LLM을 호출하여 컬럼 시맨틱 분석 수행
        
        Args:
            file_info: 파일 정보 (file_name, file_type, row_count)
            columns: 분석할 컬럼 목록
            dict_keys_list: dictionary key 목록 문자열
            dict_context: dictionary 상세 정보 문자열
        
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
        columns_info = self._build_columns_info(columns)
        
        # Prompt 구성
        prompt = COLUMN_SEMANTIC_PROMPT.format(
            dict_section=dict_section,
            file_name=file_info.get('file_name', 'unknown'),
            file_type=file_info.get('file_type', 'tabular'),
            row_count=file_info.get('row_count', 'unknown'),
            columns_info=columns_info
        )
        
        try:
            response = self.call_llm_json(
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
                    self.log(f"⚠️ Error parsing column result: {e}", indent=1)
                    continue
            
            return DataSemanticResponse(
                columns=column_results,
                file_summary=response.get('file_summary')
            )
            
        except json.JSONDecodeError as e:
            self.log(f"❌ JSON parsing error: {e}", indent=1)
            return None
        except Exception as e:
            self.log(f"❌ LLM call error: {e}", indent=1)
            return None
    
    def _update_column_metadata_batch(
        self,
        file_id: str,
        results: List[ColumnSemanticResult],
        key_to_id_map: Dict[str, str]
    ) -> Dict[str, int]:
        """
        column_metadata 테이블을 배치 업데이트
        
        Args:
            file_id: 파일 ID
            results: LLM 분석 결과 리스트
            key_to_id_map: {parameter_key: dict_id} 매핑
        
        Returns:
            통계 dict: {matched: n, not_found: n, null_from_llm: n}
        """
        _, col_repo, dict_repo = self._get_repositories()
        
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
    
    def _get_data_files_info(self, data_files: List[str]) -> List[Dict]:
        """
        데이터 파일들의 정보 조회
        
        Args:
            data_files: 파일 경로 목록
        
        Returns:
            파일 정보 리스트 (file_id, file_path, file_name, row_count 등)
        """
        if not data_files:
            return []
        
        file_repo, _, _ = self._get_repositories()
        
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
            self.log(f"⚠️ Error loading file info: {e}", indent=1)
            return []
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Data Semantic Analysis 실행
        
        데이터 파일의 컬럼을 의미론적으로 분석하고 data_dictionary와 연결
        """
        started_at = datetime.now().isoformat()
        config = DataSemanticConfig
        
        # 데이터 파일 목록
        data_files = state.get('data_files', [])
        
        if not data_files:
            self.log("⚠️ No data files to analyze")
            return {
                **state,
                'data_semantic_result': DataSemanticResult(
                    total_data_files=0,
                    started_at=started_at,
                    completed_at=datetime.now().isoformat()
                ).dict(),
                'data_semantic_entries': []
            }
        
        self.log(f"📁 Data files to analyze: {len(data_files)}")
        
        # 1. data_dictionary 로드
        self.log("📖 Loading data dictionary...")
        dictionary, dict_keys_list, dict_context, key_to_id_map = self._load_dictionary_with_context()
        self.log(f"Found {len(dictionary)} parameter definitions", indent=1)
        
        # 2. 파일 정보 조회
        files_info = self._get_data_files_info(data_files)
        self.log(f"Loaded info for {len(files_info)} files", indent=1)
        
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
            
            self.log(f"📄 Processing: {file_name}")
            
            # 컬럼 정보 로드
            columns = self._get_columns_with_stats(file_id)
            n_cols = len(columns)
            self.log(f"Columns: {n_cols}", indent=1)
            
            if not columns:
                continue
            
            columns_by_file[file_name] = n_cols
            total_columns += n_cols
            
            # 배치 분할 (컬럼 수가 많으면)
            batch_size = config.COLUMN_BATCH_SIZE
            batches = [columns[i:i+batch_size] for i in range(0, n_cols, batch_size)]
            
            if len(batches) > 1:
                self.log(f"Splitting into {len(batches)} batches (batch_size={batch_size})", indent=1)
            
            file_results = []
            
            for batch_idx, batch_cols in enumerate(batches):
                if len(batches) > 1:
                    self.log(f"Batch {batch_idx + 1}/{len(batches)} ({len(batch_cols)} columns)", indent=1)
                
                # LLM 호출
                response = self._call_llm_for_semantic(
                    file_info,
                    batch_cols,
                    dict_keys_list,
                    dict_context
                )
                llm_calls += 1
                batches_processed += 1
                
                if response and response.columns:
                    # DB 업데이트
                    stats = self._update_column_metadata_batch(
                        file_id, response.columns, key_to_id_map
                    )
                    
                    total_matched += stats.get('matched', 0)
                    total_not_found += stats.get('not_found', 0)
                    total_null_from_llm += stats.get('null_from_llm', 0)
                    
                    file_results.extend([c.dict() for c in response.columns])
                    
                    self.log(
                        f"✓ Analyzed {len(response.columns)} columns "
                        f"(matched: {stats.get('matched', 0)}, "
                        f"not_found: {stats.get('not_found', 0)}, "
                        f"null: {stats.get('null_from_llm', 0)})",
                        indent=1
                    )
                else:
                    self.log("⚠️ No results from LLM", indent=1)
            
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
        
        self.log(f"Files processed: {result.processed_files}", indent=1)
        self.log(f"Columns analyzed: {result.total_columns_analyzed}", indent=1)
        self.log(f"Dictionary matches: {result.columns_matched}", indent=1)
        self.log(f"Not found in dict: {result.columns_not_found}", indent=1)
        self.log(f"Null from LLM: {result.columns_null_from_llm}", indent=1)
        self.log(f"LLM calls: {result.llm_calls}", indent=1)
        self.log(f"Batches: {result.batches_processed}", indent=1)
        
        return {
            **state,
            'data_semantic_result': result.dict(),
            'data_semantic_entries': all_entries
        }
    
    @classmethod
    def run_standalone(cls, data_files: List[str]) -> Dict[str, Any]:
        """
        단독 실행용 메서드
        
        Args:
            data_files: 분석할 데이터 파일 경로 리스트
        
        Returns:
            실행 결과 state
        """
        node = cls()
        initial_state = {
            'data_files': data_files
        }
        return node(initial_state)
