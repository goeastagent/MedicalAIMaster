# src/agents/nodes/query_understanding/node.py
"""
QueryUnderstandingNode - [100] 동적 컨텍스트 로딩 + 쿼리 분석

Responsibilities:
1. SchemaContextBuilder로 DB 메타데이터 로딩
2. 동적 컨텍스트를 포함한 LLM 프롬프트 생성
3. 사용자 쿼리 분석 (intent, parameters, filters, temporal)
"""

import sys
from pathlib import Path
from typing import Dict, Any

# shared 패키지 경로 추가
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.agents.base import BaseNode
from src.agents.registry import register_node
from src.agents.context import SchemaContextBuilder
from src.config import get_config

# shared LLM client
from shared.llm.client import get_llm_client

# 프롬프트 템플릿
from .prompts import build_system_prompt, build_user_prompt


@register_node
class QueryUnderstandingNode(BaseNode):
    """
    [100] 쿼리 이해 노드
    
    DB 메타데이터 기반 동적 컨텍스트 생성 + LLM 쿼리 분석
    
    Input:
        - user_query: str
    
    Output:
        - schema_context: Dict (cohort_sources, signal_groups, parameters, relationships)
        - intent: str ("data_retrieval")
        - requested_parameters: List[Dict] (term, normalized, candidates)
        - cohort_filters: List[Dict] (column, operator, value)
        - temporal_context: Dict (type, start_column, end_column, margin_seconds)
    """
    
    name = "query_understanding"
    description = "동적 컨텍스트 로딩 + 쿼리 분석"
    order = 100
    requires_llm = True
    requires_db = True
    
    def __init__(self):
        super().__init__()
        self._context_builder = None
        self._llm_client = None
        self._config = get_config()
    
    @property
    def context_builder(self) -> SchemaContextBuilder:
        """SchemaContextBuilder 인스턴스 (lazy loading)"""
        if self._context_builder is None:
            self._context_builder = SchemaContextBuilder()
        return self._context_builder
    
    @property
    def llm_client(self):
        """LLM 클라이언트 인스턴스 (lazy loading)"""
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute query understanding
        
        1. SchemaContextBuilder로 DB 메타데이터 로딩
        2. 동적 컨텍스트 기반 LLM 프롬프트 생성
        3. LLM 호출 및 응답 파싱
        """
        user_query = state.get("user_query", "")
        
        self.log(f"입력 쿼리: {user_query}", "📝")
        
        # 1. 스키마 컨텍스트 로딩
        self.log("스키마 컨텍스트 로딩 중...", "📊")
        schema_context = self._load_schema_context()
        
        cohort_count = len(schema_context.get("cohort_sources", []))
        group_count = len(schema_context.get("signal_groups", []))
        param_categories = len(schema_context.get("parameters", {}))
        rel_count = len(schema_context.get("relationships", []))
        
        self.log(f"컨텍스트 로딩 완료: cohort={cohort_count}, groups={group_count}, param_categories={param_categories}, rels={rel_count}", "✅", indent=1)
        
        # 2. LLM 호출로 쿼리 분석
        self.log("LLM 쿼리 분석 중...", "🤖")
        llm_result = self._analyze_query_with_llm(user_query, schema_context)
        
        # 3. 결과 추출
        intent = llm_result.get("intent", "data_retrieval")
        requested_parameters = llm_result.get("requested_parameters", [])
        cohort_filters = llm_result.get("cohort_filters", [])
        temporal_context = llm_result.get("temporal_context", {
            "type": "full_record",
            "margin_seconds": 0
        })
        reasoning = llm_result.get("reasoning", "")
        
        self.log(f"의도 분석: {intent}", "🎯", indent=1)
        self.log(f"요청 파라미터: {len(requested_parameters)}개", "📋", indent=1)
        for param in requested_parameters:
            self.log(f"  - {param.get('term')} → {param.get('normalized')}", "", indent=2)
        
        self.log(f"필터: {len(cohort_filters)}개", "🔍", indent=1)
        for f in cohort_filters:
            self.log(f"  - {f.get('column')} {f.get('operator')} {f.get('value')}", "", indent=2)
        
        self.log(f"시간 범위: {temporal_context.get('type')}", "⏰", indent=1)
        
        if reasoning:
            self.log(f"분석 근거: {reasoning[:100]}...", "💭", indent=1)
        
        return {
            "query_understanding_result": {
                "status": "success",
                "node": self.name,
                "user_query": user_query,
                "context_loaded": True,
                "llm_reasoning": reasoning
            },
            "schema_context": schema_context,
            "intent": intent,
            "requested_parameters": requested_parameters,
            "cohort_filters": cohort_filters,
            "temporal_context": temporal_context
        }
    
    def _load_schema_context(self) -> Dict[str, Any]:
        """
        SchemaContextBuilder로 스키마 컨텍스트 로딩
        
        Returns:
            {
                "cohort_sources": [...],
                "signal_groups": [...],
                "parameters": {...},
                "relationships": [...],
                "context_text": "..."
            }
        """
        max_params = self._config.query_understanding.max_parameters_in_context
        return self.context_builder.build_context(max_parameters=max_params)
    
    def _analyze_query_with_llm(
        self, 
        user_query: str, 
        schema_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        LLM을 사용하여 쿼리 분석
        
        Args:
            user_query: 사용자 자연어 쿼리
            schema_context: 스키마 컨텍스트 (context_text 포함)
        
        Returns:
            {
                "intent": "data_retrieval",
                "requested_parameters": [...],
                "cohort_filters": [...],
                "temporal_context": {...},
                "reasoning": "..."
            }
        """
        # 프롬프트 생성
        context_text = schema_context.get("context_text", "")
        
        # 사용 가능한 카테고리 목록 추출 (동적)
        category_guide = schema_context.get("category_guide", {})
        available_categories = list(category_guide.keys()) if category_guide else None
        
        system_prompt = build_system_prompt(context_text, available_categories)
        user_prompt = build_user_prompt(user_query)
        
        # LLM 호출
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        
        try:
            response = self.llm_client.ask_json(full_prompt)
            
            # 에러 체크
            if "error" in response:
                self.log(f"LLM 에러: {response.get('error')}", "⚠️")
                return self._get_default_response()
            
            return self._validate_and_normalize_response(response)
            
        except Exception as e:
            self.log(f"LLM 호출 실패: {e}", "❌")
            return self._get_default_response()
    
    def _validate_and_normalize_response(
        self, 
        response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        LLM 응답 검증 및 정규화
        
        - 필수 필드 확인
        - 기본값 설정
        - 타입 검증
        """
        result = {
            "intent": response.get("intent", "data_retrieval"),
            "requested_parameters": [],
            "cohort_filters": [],
            "temporal_context": {
                "type": "full_record",
                "margin_seconds": 0
            },
            "reasoning": response.get("reasoning", "")
        }
        
        # requested_parameters 정규화
        params = response.get("requested_parameters", [])
        if isinstance(params, list):
            for param in params:
                if isinstance(param, dict):
                    normalized_param = {
                        "term": param.get("term", ""),
                        "normalized": param.get("normalized", param.get("term", "")),
                        "candidates": param.get("candidates", []),
                        "expected_categories": param.get("expected_categories", [])  # Option B: 카테고리 힌트
                    }
                    # candidates가 없으면 term과 normalized를 사용
                    if not normalized_param["candidates"]:
                        candidates = [normalized_param["term"]]
                        if normalized_param["normalized"] != normalized_param["term"]:
                            candidates.append(normalized_param["normalized"])
                        normalized_param["candidates"] = candidates
                    
                    result["requested_parameters"].append(normalized_param)
        
        # cohort_filters 정규화
        filters = response.get("cohort_filters", [])
        if isinstance(filters, list):
            for f in filters:
                if isinstance(f, dict) and f.get("column"):
                    normalized_filter = {
                        "column": f.get("column"),
                        "operator": f.get("operator", "="),
                        "value": f.get("value", "")
                    }
                    result["cohort_filters"].append(normalized_filter)
        
        # temporal_context 정규화
        temporal = response.get("temporal_context", {})
        if isinstance(temporal, dict):
            result["temporal_context"] = {
                "type": temporal.get("type", "full_record"),
                "margin_seconds": temporal.get("margin_seconds", 0),
                "start_column": temporal.get("start_column"),
                "end_column": temporal.get("end_column")
            }
        
        return result
    
    def _get_default_response(self) -> Dict[str, Any]:
        """LLM 실패 시 기본 응답"""
        return {
            "intent": "data_retrieval",
            "requested_parameters": [],
            "cohort_filters": [],
            "temporal_context": {
                "type": "full_record",
                "margin_seconds": 0
            },
            "reasoning": "LLM 호출 실패로 기본값 사용"
        }
