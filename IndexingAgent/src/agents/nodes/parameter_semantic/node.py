# src/agents/nodes/parameter_semantic/node.py
"""
Parameter Semantic Analysis Node

parameter 테이블의 각 parameter를 의미론적으로 분석하고
data_dictionary와 연결합니다.

주요 기능:
- LLM을 사용해 각 parameter의 semantic_name, unit, description 추론
- data_dictionary의 parameter_key와 매칭 시도
- parameter 테이블에 결과 저장 (dict_entry_id, dict_match_status)
- parameter 수가 많으면 배치로 분할하여 LLM 호출

Workflow:
1. column_classification에서 생성된 parameter 조회 (semantic 미분석)
2. LLM으로 각 parameter 분석
3. parameter 테이블 업데이트
"""

import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from ...state import AgentState
from ...models.llm_responses import (
    ParameterSemanticResult,
    ParameterSemanticResponse,
)
from ...base import BaseNode, LLMMixin, DatabaseMixin
from ...registry import register_node
from src.database import (
    FileRepository,
    DictionaryRepository,
)
from src.database.repositories import ParameterRepository
from src.config import DataSemanticConfig, LLMConfig
from .prompts import ParameterSemanticPrompt


@register_node
class ParameterSemanticNode(BaseNode, LLMMixin, DatabaseMixin):
    """
    Parameter Semantic Analysis Node (LLM-based)
    
    parameter 테이블의 각 parameter를 의미론적으로 분석하고
    data_dictionary와 연결합니다.
    
    Input State:
        - data_files: 분석할 데이터 파일 경로 목록
        - (DB) data_dictionary: 이전 단계에서 생성된 parameter definitions
        - (DB) parameter: column_classification에서 생성된 parameter 목록
    
    Output State:
        - parameter_semantic_result: 분석 결과 요약
        - parameter_semantic_entries: 분석된 parameter 정보 리스트
        - (DB) parameter 테이블 업데이트: semantic_name, unit, dict_entry_id 등
    """
    
    name = "parameter_semantic"
    description = "Parameter 의미 분석 및 dictionary 매칭"
    order = 600
    requires_llm = True
    
    # 프롬프트 클래스 연결
    prompt_class = ParameterSemanticPrompt
    
    def __init__(self):
        super().__init__()
        self._file_repo: Optional[FileRepository] = None
        self._param_repo: Optional[ParameterRepository] = None
        self._dict_repo: Optional[DictionaryRepository] = None
    
    def _get_repositories(self) -> Tuple[FileRepository, ParameterRepository, DictionaryRepository]:
        """Repository 인스턴스들 반환 (lazy initialization)"""
        if self._file_repo is None:
            self._file_repo = FileRepository()
            self._param_repo = ParameterRepository()
            self._dict_repo = DictionaryRepository()
        return self._file_repo, self._param_repo, self._dict_repo
    
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
    
    def _get_parameters_to_analyze(self, data_files: List[str]) -> List[Dict]:
        """
        semantic 분석이 필요한 parameter 조회 (파일 레벨 + 그룹 레벨)
        
        Args:
            data_files: 데이터 파일 경로 목록
        
        Returns:
            Parameter 정보 리스트 (파일 레벨 + 그룹 레벨 합산)
        """
        _, param_repo, _ = self._get_repositories()
        file_repo, _, _ = self._get_repositories()
        
        all_parameters = []
        
        try:
            # 1. 파일 레벨 파라미터 조회
            files_data = file_repo.get_files_by_paths(data_files)
            file_ids = [f['file_id'] for f in files_data]
            
            if file_ids:
                file_params = param_repo.get_parameters_without_semantic(file_ids)
                all_parameters.extend(file_params)
            
            # 2. 그룹 레벨 파라미터 조회 (file_id=NULL, group_id!=NULL)
            group_params = param_repo.get_group_parameters_without_semantic()
            if group_params:
                all_parameters.extend(group_params)
                self.log(f"   Including {len(group_params)} group-level parameters", indent=0)
            
            return all_parameters
            
        except Exception as e:
            self.log(f"⚠️ Error loading parameters: {e}", indent=1)
            return []
    
    def _build_parameters_info(self, parameters: List[Dict]) -> str:
        """
        Parameter 정보를 LLM context 문자열로 변환
        
        Args:
            parameters: parameter 정보 리스트
        
        Returns:
            포맷된 parameter 정보 문자열
        """
        config = DataSemanticConfig
        lines = []
        
        for param in parameters:
            param_key = param.get('param_key', '')
            source_type = param.get('source_type', '')
            value_stats = param.get('value_stats', {}) or {}
            
            # 기본 정보
            line = f"- {param_key} (source: {source_type})"
            details = []
            
            # 통계 정보 (있으면)
            if value_stats:
                if 'min' in value_stats and 'max' in value_stats:
                    details.append(f"range: [{value_stats['min']}, {value_stats['max']}]")
                if 'mean' in value_stats:
                    details.append(f"mean: {value_stats['mean']:.2f}")
                if 'unique_values' in value_stats:
                    unique_vals = value_stats['unique_values']
                    max_show = config.MAX_UNIQUE_VALUES_DISPLAY
                    if len(unique_vals) <= max_show:
                        details.append(f"values: {unique_vals}")
                    else:
                        details.append(f"values ({len(unique_vals)} unique): {unique_vals[:max_show]}...")
            
            # extracted_unit (있으면)
            if param.get('extracted_unit'):
                details.append(f"extracted_unit: {param['extracted_unit']}")
            
            # 조합
            if details:
                line += "\n    " + "\n    ".join(details)
            
            lines.append(line)
        
        return "\n".join(lines)
    
    def _call_llm_for_semantic(
        self,
        parameters: List[Dict],
        dict_keys_list: str,
        dict_context: str
    ) -> Optional[ParameterSemanticResponse]:
        """
        LLM을 호출하여 parameter 시맨틱 분석 수행
        
        Args:
            parameters: 분석할 parameter 목록
            dict_keys_list: dictionary key 목록 문자열
            dict_context: dictionary 상세 정보 문자열
        
        Returns:
            ParameterSemanticResponse or None
        """
        # Dictionary section 구성
        dict_section = self.prompt_class.build_dict_section(dict_keys_list, dict_context)
        
        # Parameters info 구성
        parameters_info = self._build_parameters_info(parameters)
        
        # 프롬프트 빌드
        prompt = self.prompt_class.build(
            dict_section=dict_section,
            parameters_info=parameters_info,
            param_count=len(parameters)
        )
        
        try:
            response = self.call_llm_json(
                prompt=prompt,
                max_tokens=LLMConfig.MAX_TOKENS_COLUMN_ANALYSIS
            )
            
            if not response:
                return None
            
            # 응답 파싱
            param_results = self.prompt_class.parse_response(response)
            
            if param_results is None:
                # fallback: 수동 파싱
                params_data = response.get('parameters', response.get('columns', []))
                param_results = []
                for p_data in params_data:
                    try:
                        p_result = ParameterSemanticResult(
                            param_key=p_data.get('param_key', p_data.get('original_name', '')),
                            semantic_name=p_data.get('semantic_name', ''),
                            unit=p_data.get('unit'),
                            description=p_data.get('description'),
                            concept_category=p_data.get('concept_category'),
                            dict_entry_key=p_data.get('dict_entry_key'),
                            match_confidence=p_data.get('match_confidence', 0.0),
                            reasoning=p_data.get('reasoning')
                        )
                        param_results.append(p_result)
                    except Exception as e:
                        self.log(f"⚠️ Error parsing parameter result: {e}", indent=1)
                        continue
            
            return ParameterSemanticResponse(
                parameters=param_results,
                summary=response.get('summary')
            )
            
        except json.JSONDecodeError as e:
            self.log(f"❌ JSON parsing error: {e}", indent=1)
            return None
        except Exception as e:
            self.log(f"❌ LLM call error: {e}", indent=1)
            return None
    
    def _update_parameter_semantic_batch(
        self,
        results: List[ParameterSemanticResult],
        param_key_to_ids: Dict[str, List[int]],
        key_to_dict_id: Dict[str, str]
    ) -> Dict[str, int]:
        """
        parameter 테이블을 배치 업데이트
        
        동일한 param_key가 여러 파일에 존재할 수 있으므로,
        해당하는 모든 param_id에 동일한 semantic 정보를 적용
        
        Args:
            results: LLM 분석 결과 리스트
            param_key_to_ids: {param_key: [param_id, ...]} 매핑
            key_to_dict_id: {dict_key: dict_entry_id} 매핑
        
        Returns:
            통계 dict: {matched: n, not_found: n, null_from_llm: n}
        """
        _, param_repo, dict_repo = self._get_repositories()
        
        stats = {'matched': 0, 'not_found': 0, 'null_from_llm': 0}
        
        for result in results:
            param_key = result.param_key
            param_ids = param_key_to_ids.get(param_key, [])
            
            if not param_ids:
                self.log(f"⚠️ param_id not found for: {param_key}", indent=2)
                continue
            
            # dict_entry_id 해석
            dict_id, status = dict_repo.resolve_dict_entry_id(
                result.dict_entry_key,
                key_to_dict_id
            )
            
            # 통계 업데이트 (param_key 단위로 카운트)
            if status == 'matched':
                stats['matched'] += 1
            elif status == 'not_found':
                stats['not_found'] += 1
            else:
                stats['null_from_llm'] += 1
            
            # 모든 관련 param_id에 대해 업데이트
            for param_id in param_ids:
                try:
                    param_repo.update_semantic_info(
                        param_id=param_id,
                        semantic_name=result.semantic_name,
                        unit=result.unit,
                        concept_category=result.concept_category,
                        description=result.description,
                        dict_entry_id=dict_id,
                        dict_match_status=status,
                        match_confidence=result.match_confidence,
                        llm_confidence=result.match_confidence,  # LLM이 제공하는 신뢰도
                        llm_reasoning=result.reasoning
                    )
                except Exception as e:
                    self.log(f"⚠️ Error updating parameter {param_key} (id={param_id}): {e}", indent=2)
        
        return stats
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parameter Semantic Analysis 실행
        
        parameter 테이블의 각 parameter를 의미론적으로 분석하고 data_dictionary와 연결
        """
        started_at = datetime.now().isoformat()
        config = DataSemanticConfig
        
        # 데이터 파일 목록
        data_files = state.get('data_files', [])
        
        if not data_files:
            self.log("⚠️ No data files to analyze")
            return {
                **state,
                'parameter_semantic_result': {
                    'total_parameters': 0,
                    'started_at': started_at,
                    'completed_at': datetime.now().isoformat()
                },
                'parameter_semantic_entries': []
            }
        
        self.log(f"📁 Data files: {len(data_files)}")
        
        # 1. data_dictionary 로드
        self.log("📖 Loading data dictionary...")
        dictionary, dict_keys_list, dict_context, key_to_dict_id = self._load_dictionary_with_context()
        self.log(f"Found {len(dictionary)} parameter definitions", indent=1)
        
        # 2. 분석할 parameter 조회
        self.log("🔍 Loading parameters to analyze...")
        parameters = self._get_parameters_to_analyze(data_files)
        self.log(f"Found {len(parameters)} parameters to analyze", indent=1)
        
        if not parameters:
            self.log("⚠️ No parameters found to analyze")
            return {
                **state,
                'parameter_semantic_result': {
                    'total_parameters': 0,
                    'started_at': started_at,
                    'completed_at': datetime.now().isoformat()
                },
                'parameter_semantic_entries': []
            }
        
        # param_key → [param_id, ...] 매핑 생성 (동일 param_key가 여러 파일에 있을 수 있음)
        from collections import defaultdict
        param_key_to_ids = defaultdict(list)
        for p in parameters:
            param_key_to_ids[p['param_key']].append(p['param_id'])
        
        # 결과 추적
        total_parameters = len(parameters)
        total_matched = 0
        total_not_found = 0
        total_null_from_llm = 0
        llm_calls = 0
        batches_processed = 0
        all_entries = []
        
        # 3. 배치 처리
        batch_size = config.COLUMN_BATCH_SIZE
        batches = [parameters[i:i+batch_size] for i in range(0, total_parameters, batch_size)]
        
        if len(batches) > 1:
            self.log(f"📦 Splitting into {len(batches)} batches (batch_size={batch_size})")
        
        for batch_idx, batch_params in enumerate(batches):
            if len(batches) > 1:
                self.log(f"🔄 Batch {batch_idx + 1}/{len(batches)} ({len(batch_params)} parameters)", indent=1)
            
            # LLM 호출
            response = self._call_llm_for_semantic(
                batch_params,
                dict_keys_list,
                dict_context
            )
            llm_calls += 1
            batches_processed += 1
            
            if response and response.parameters:
                # DB 업데이트
                stats = self._update_parameter_semantic_batch(
                    response.parameters,
                    param_key_to_ids,
                    key_to_dict_id
                )
                
                total_matched += stats.get('matched', 0)
                total_not_found += stats.get('not_found', 0)
                total_null_from_llm += stats.get('null_from_llm', 0)
                
                all_entries.extend([c.dict() for c in response.parameters])
                
                self.log(
                    f"✅ Analyzed {len(response.parameters)} parameters "
                    f"(matched: {stats.get('matched', 0)}, "
                    f"not_found: {stats.get('not_found', 0)}, "
                    f"null: {stats.get('null_from_llm', 0)})",
                    indent=1
                )
            else:
                self.log("⚠️ No results from LLM", indent=1)
        
        # 4. 최종 결과 구성
        completed_at = datetime.now().isoformat()
        
        result = {
            'total_parameters': total_parameters,
            'parameters_analyzed': len(all_entries),
            'parameters_matched': total_matched,
            'parameters_not_found': total_not_found,
            'parameters_null_from_llm': total_null_from_llm,
            'batches_processed': batches_processed,
            'llm_calls': llm_calls,
            'started_at': started_at,
            'completed_at': completed_at
        }
        
        self.log(f"📊 Parameters analyzed: {len(all_entries)}/{total_parameters}", indent=1)
        self.log(f"✅ Dictionary matches: {total_matched}", indent=1)
        self.log(f"❌ Not found in dict: {total_not_found}", indent=1)
        self.log(f"⚠️ Null from LLM: {total_null_from_llm}", indent=1)
        self.log(f"🔄 Batches: {batches_processed}", indent=1)
        self.log(f"🤖 LLM calls: {llm_calls}", indent=1)
        
        return {
            **state,
            'parameter_semantic_result': result,
            'parameter_semantic_entries': all_entries
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
