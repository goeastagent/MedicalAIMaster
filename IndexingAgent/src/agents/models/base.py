# src/agents/models/base.py
"""
Pydantic 베이스 클래스 및 공통 유틸리티

모든 Pydantic 모델의 공통 기능:
- LLMAnalysisBase: LLM 분석 결과의 공통 필드 (confidence, reasoning)
- PhaseResultBase: Phase 결과의 공통 필드 (llm_calls, started_at, completed_at)
- Neo4jPhaseResultBase: Neo4j 사용 Phase 결과 (+ neo4j_synced)
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


# =============================================================================
# 헬퍼 함수
# =============================================================================

def parse_llm_response(response: Dict[str, Any], model_class: type) -> BaseModel:
    """
    LLM의 dict 응답을 Pydantic 모델로 변환
    
    Args:
        response: LLM 응답 (dict)
        model_class: 변환할 Pydantic 모델 클래스
    
    Returns:
        검증된 Pydantic 모델 인스턴스
    
    Raises:
        ValidationError: 응답이 모델 스키마와 맞지 않을 때
    """
    try:
        return model_class(**response)
    except Exception as e:
        print(f"⚠️ [LLM Response Parsing] Validation failed: {e}")
        print(f"   Response: {response}")
        # 기본값으로 모델 생성
        return model_class()


# =============================================================================
# 베이스 클래스: LLM 분석 결과 공통 필드
# =============================================================================

class LLMAnalysisBase(BaseModel):
    """
    LLM 분석 결과의 공통 필드
    
    대부분의 LLM 응답 모델이 상속받아 사용합니다.
    - confidence: 분석 확신도 (0.0 ~ 1.0)
    - reasoning: 판단 근거
    """
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class PhaseResultBase(BaseModel):
    """
    Phase 결과의 공통 필드
    
    각 Phase의 최종 결과 모델이 상속받아 사용합니다.
    """
    llm_calls: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class Neo4jPhaseResultBase(PhaseResultBase):
    """
    Neo4j 사용 Node 결과의 공통 필드
    
    relationship_inference, ontology_enhancement 등 Neo4j를 사용하는 노드의 결과 모델이 상속받습니다.
    """
    neo4j_synced: bool = False

