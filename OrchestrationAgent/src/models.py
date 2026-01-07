"""Orchestrator 입출력 모델"""

from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class OrchestrationRequest(BaseModel):
    """오케스트레이션 요청
    
    Example:
        request = OrchestrationRequest(
            query="위암 환자의 심박수 평균을 성별로 비교해줘",
            max_retries=2
        )
    """
    
    query: str
    """자연어 질의"""
    
    max_retries: int = Field(default=2, ge=0, le=5)
    """코드 생성 재시도 횟수"""
    
    timeout_seconds: int = Field(default=30, ge=5, le=120)
    """실행 타임아웃 (초)"""
    
    auto_resolve_ambiguity: bool = True
    """모호성 자동 해결 여부"""


class OrchestrationResult(BaseModel):
    """오케스트레이션 결과
    
    Example:
        if result.status == "success":
            print(result.result)  # 분석 결과
            print(result.generated_code)  # 생성된 코드
        else:
            print(result.error_message)
    """
    
    status: Literal["success", "error", "partial"]
    """실행 상태"""
    
    # === 성공 시 ===
    result: Optional[Any] = None
    """분석 결과 (숫자, 딕셔너리, DataFrame 등)"""
    
    generated_code: Optional[str] = None
    """생성된 Python 코드"""
    
    # === 실패 시 ===
    error_message: Optional[str] = None
    """에러 메시지"""
    
    error_stage: Optional[Literal["extraction", "data_load", "analysis"]] = None
    """실패한 단계"""
    
    # === 메타데이터 ===
    execution_time_ms: Optional[float] = None
    """총 실행 시간 (밀리초)"""
    
    data_summary: Optional[Dict[str, Any]] = None
    """데이터 요약 (케이스 수, 컬럼 등)"""
    
    extraction_plan: Optional[Dict[str, Any]] = None
    """ExtractionAgent가 생성한 실행 계획"""
    
    retry_count: int = 0
    """재시도 횟수"""
    
    # === 디버그 정보 ===
    extraction_confidence: Optional[float] = None
    """Extraction 신뢰도"""
    
    ambiguities: Optional[List[Dict[str, Any]]] = None
    """발견된 모호성 목록"""


class DataSummary(BaseModel):
    """데이터 요약 정보"""
    
    case_count: int = 0
    """총 케이스 수"""
    
    param_keys: List[str] = Field(default_factory=list)
    """사용 가능한 파라미터 키 목록"""
    
    cohort_columns: List[str] = Field(default_factory=list)
    """Cohort 컬럼 목록"""
    
    signal_columns: List[str] = Field(default_factory=list)
    """Signal 컬럼 목록"""
    
    signal_shape: Optional[tuple] = None
    """Signal DataFrame shape (rows, cols)"""
    
    cohort_shape: Optional[tuple] = None
    """Cohort DataFrame shape (rows, cols)"""

