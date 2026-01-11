# src/agents/state.py
"""
ExtractionAgent State Definition

LangGraph 워크플로우에서 사용하는 상태 객체입니다.
3-Node Pipeline:
    [100] QueryUnderstanding - 동적 컨텍스트 로딩 + 쿼리 분석
    [200] ParameterResolver  - 파라미터 매핑
    [300] PlanBuilder        - Execution Plan 생성
"""

import operator
from typing import Annotated, List, Dict, Any, Optional, TypedDict


class ExtractionState(TypedDict):
    """
    ExtractionAgent 워크플로우 상태
    
    3-Node Sequential Pipeline:
        [100] QueryUnderstanding: DB 메타데이터 기반 동적 컨텍스트 생성 + LLM 쿼리 분석
        [200] ParameterResolver: 요청 파라미터를 실제 param_key에 매핑
        [300] PlanBuilder: Execution Plan JSON 조립 및 검증
    """
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Input
    # ═══════════════════════════════════════════════════════════════════════════
    user_query: str  # 사용자 자연어 쿼리
    
    # ═══════════════════════════════════════════════════════════════════════════
    # [100] QueryUnderstanding Output
    # ═══════════════════════════════════════════════════════════════════════════
    query_understanding_result: Optional[Dict[str, Any]]  # 노드 실행 결과 요약
    
    schema_context: Optional[Dict[str, Any]]
    # {
    #     "cohort_sources": [
    #         {
    #             "file_id": "uuid-...",
    #             "file_name": "...",
    #             "row_represents": "...",
    #             "entity_identifier": "...",
    #             "filterable_columns": [...],
    #             "temporal_columns": [...]
    #         }
    #     ],
    #     "signal_groups": [
    #         {
    #             "group_id": "uuid-...",
    #             "group_name": "...",
    #             "file_count": 0,
    #             "file_pattern": "...",
    #             "entity_identifier_key": "..."
    #         }
    #     ],
    #     "parameters": {
    #         "<category>": {
    #             "param_keys": [...],
    #             "semantic_names": [...],
    #             "units": [...]
    #         }
    #     },
    #     "relationships": [
    #         {"from": "...", "to": "...", "via": "...", "cardinality": "..."}
    #     ],
    #     "context_text": "LLM 프롬프트용 텍스트"
    # }
    
    intent: Optional[str]  # always "data_retrieval"
    
    requested_parameters: Optional[List[Dict[str, Any]]]
    # [{
    #     "term": "심박수",           # 사용자 원문
    #     "normalized": "Heart Rate", # 정규화된 이름
    #     "candidates": ["HR", "Heart Rate"]  # 검색 키워드
    # }]
    
    cohort_filters: Optional[List[Dict[str, Any]]]
    # [{
    #     "column": "diagnosis",
    #     "operator": "LIKE",
    #     "value": "%Stomach Cancer%"
    # }]
    
    temporal_context: Optional[Dict[str, Any]]
    # {
    #     "type": "procedure_window",  # full_record | procedure_window | treatment_window | custom_window
    #     "start_column": "procedure_start",
    #     "end_column": "procedure_end",
    #     "margin_seconds": 300
    # }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # [200] ParameterResolver Output
    # ═══════════════════════════════════════════════════════════════════════════
    parameter_resolver_result: Optional[Dict[str, Any]]  # 노드 실행 결과 요약
    
    resolved_parameters: Optional[List[Dict[str, Any]]]
    # [{
    #     "term": "심박수",
    #     "param_keys": ["Solar8000/HR", "BIS/HR"],
    #     "semantic_name": "Heart Rate",
    #     "unit": "bpm",
    #     "concept_category": "Vital Signs",
    #     "resolution_mode": "all_sources",  # all_sources | specific | clarify
    #     "confidence": 0.95
    # }]
    
    ambiguities: Optional[List[Dict[str, Any]]]
    # [{
    #     "term": "...",
    #     "candidates": [...],
    #     "question": "사용자에게 질문할 내용"
    # }]
    
    has_ambiguity: Optional[bool]  # 사용자 확인이 필요한 모호성 존재 여부
    
    # ═══════════════════════════════════════════════════════════════════════════
    # [300] PlanBuilder Output
    # ═══════════════════════════════════════════════════════════════════════════
    plan_builder_result: Optional[Dict[str, Any]]  # 노드 실행 결과 요약
    
    execution_plan: Optional[Dict[str, Any]]  # 최종 Execution Plan JSON
    # {
    #     "version": "1.0",
    #     "generated_at": "...",
    #     "agent": "ExtractionAgent",
    #     "original_query": "...",
    #     "execution_plan": {
    #         "cohort_source": {...},
    #         "signal_source": {...}
    #     },
    #     "validation": {...}
    # }
    
    validation: Optional[Dict[str, Any]]
    # {
    #     "warnings": [],
    #     "confidence": 0.95,
    #     "validated_at": "..."
    # }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Human-in-the-Loop (Future)
    # ═══════════════════════════════════════════════════════════════════════════
    needs_human_review: Optional[bool]
    human_question: Optional[str]
    human_feedback: Optional[str]
    
    # ═══════════════════════════════════════════════════════════════════════════
    # System
    # ═══════════════════════════════════════════════════════════════════════════
    logs: Annotated[List[str], operator.add]  # 로그 누적
    error_message: Optional[str]

