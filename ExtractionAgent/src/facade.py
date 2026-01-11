# ExtractionAgent/src/facade.py
"""
ExtractionFacade - ExtractionAgent 단순화 인터페이스

OrchestrationAgent에서 ExtractionAgent를 쉽게 사용할 수 있도록
LangGraph workflow를 단순한 함수 호출로 래핑합니다.

Usage:
    from ExtractionAgent.src.facade import ExtractionFacade
    
    # 기본 사용
    facade = ExtractionFacade()
    plan = facade.extract("위암 환자의 수술 중 심박수 데이터")
    
    # 전체 상태 포함 (디버깅용)
    result = facade.extract_with_state("위암 환자의 수술 중 심박수 데이터")
    print(result.execution_plan)
    print(result.resolved_parameters)
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ExtractionResult:
    """ExtractionAgent 실행 결과"""
    
    # 성공 여부
    success: bool
    
    # 최종 Execution Plan (성공 시)
    execution_plan: Optional[Dict[str, Any]] = None
    
    # 중간 결과들
    schema_context: Optional[Dict[str, Any]] = None
    resolved_parameters: Optional[List[Dict[str, Any]]] = None
    cohort_filters: Optional[List[Dict[str, Any]]] = None
    temporal_context: Optional[Dict[str, Any]] = None
    
    # 모호성 정보 (Human-in-the-Loop용)
    has_ambiguity: bool = False
    ambiguities: Optional[List[Dict[str, Any]]] = None
    
    # 검증 정보
    validation: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    
    # 메타데이터
    original_query: str = ""
    execution_time_seconds: float = 0.0
    logs: List[str] = field(default_factory=list)
    
    # 에러 (실패 시)
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "success": self.success,
            "execution_plan": self.execution_plan,
            "schema_context": self.schema_context,
            "resolved_parameters": self.resolved_parameters,
            "cohort_filters": self.cohort_filters,
            "temporal_context": self.temporal_context,
            "has_ambiguity": self.has_ambiguity,
            "ambiguities": self.ambiguities,
            "validation": self.validation,
            "confidence": self.confidence,
            "original_query": self.original_query,
            "execution_time_seconds": self.execution_time_seconds,
            "logs": self.logs,
            "error_message": self.error_message,
        }


class ExtractionFacade:
    """
    ExtractionAgent 단순화 인터페이스
    
    LangGraph workflow를 래핑하여 단순한 함수 호출로 사용할 수 있게 합니다.
    
    Attributes:
        verbose: True면 빌드 정보 출력 (기본 False)
    
    Examples:
        # 기본 사용
        facade = ExtractionFacade()
        plan = facade.extract("위암 환자의 수술 중 심박수 데이터")
        
        # DataContext와 연동
        from shared.data.context import DataContext
        ctx = DataContext()
        ctx.load_from_plan(plan)
        df = ctx.get_merged_data()
    """
    
    def __init__(self, verbose: bool = False):
        """
        Args:
            verbose: True면 workflow 빌드 시 정보 출력
        """
        self.verbose = verbose
        self._workflow = None
    
    def _get_workflow(self):
        """Lazy workflow initialization"""
        if self._workflow is None:
            from shared.langgraph import get_registry, build_sequential_graph
            from ExtractionAgent.src.agents.state import ExtractionState
            
            # Registry 초기화 (다른 Agent와 충돌 방지)
            registry = get_registry()
            registry.clear()
            
            # Workflow 빌드 (verbose=False로 출력 억제)
            import sys
            from io import StringIO
            
            if not self.verbose:
                # stdout 임시 캡처
                old_stdout = sys.stdout
                sys.stdout = StringIO()
            
            try:
                self._workflow = build_sequential_graph(
                    state_class=ExtractionState,
                    node_module="ExtractionAgent.src.agents.nodes",
                    agent_name="ExtractionAgent",
                    verbose=self.verbose,
                )
            finally:
                if not self.verbose:
                    sys.stdout = old_stdout
        
        return self._workflow
    
    def extract(self, query: str) -> Dict[str, Any]:
        """
        자연어 쿼리를 Execution Plan으로 변환
        
        Args:
            query: 자연어 쿼리 (예: "위암 환자의 수술 중 심박수 데이터")
        
        Returns:
            Execution Plan JSON (DataContext.load_from_plan()에 직접 전달 가능)
            {
                "version": "1.0",
                "generated_at": "...",
                "agent": "ExtractionAgent",
                "original_query": "...",
                "execution_plan": {
                    "cohort_source": {...},
                    "signal_source": {...},
                    "join_specification": {...}
                }
            }
        
        Raises:
            RuntimeError: 추출 실패 시
        
        Example:
            facade = ExtractionFacade()
            plan = facade.extract("위암 환자의 수술 중 심박수")
            
            from shared.data.context import DataContext
            ctx = DataContext()
            ctx.load_from_plan(plan)
        """
        result = self.extract_with_state(query)
        
        if not result.success:
            raise RuntimeError(f"Extraction failed: {result.error_message}")
        
        if result.has_ambiguity:
            # 모호성이 있으면 경고와 함께 반환
            import warnings
            warnings.warn(
                f"Query has ambiguities that may need clarification: {result.ambiguities}"
            )
        
        return result.execution_plan
    
    def extract_with_state(self, query: str) -> ExtractionResult:
        """
        자연어 쿼리를 Execution Plan으로 변환 (전체 상태 포함)
        
        디버깅이나 상세 정보가 필요할 때 사용합니다.
        
        Args:
            query: 자연어 쿼리
        
        Returns:
            ExtractionResult 객체 (모든 중간 결과 포함)
        
        Example:
            result = facade.extract_with_state("위암 환자의 심박수")
            
            if result.success:
                print(f"Resolved parameters: {result.resolved_parameters}")
                print(f"Execution plan: {result.execution_plan}")
            else:
                print(f"Error: {result.error_message}")
        """
        start_time = datetime.now()
        
        try:
            workflow = self._get_workflow()
            
            # 초기 상태
            initial_state = {
                "user_query": query,
                "logs": [],
            }
            
            # Workflow 실행
            final_state = workflow.invoke(initial_state)
            
            # 실행 시간 계산
            execution_time = (datetime.now() - start_time).total_seconds()
            
            # 결과 추출
            execution_plan = final_state.get("execution_plan")
            has_ambiguity = final_state.get("has_ambiguity", False)
            error_message = final_state.get("error_message")
            validation = final_state.get("validation", {})
            confidence = validation.get("confidence", 0.0) if validation else 0.0
            
            # 성공 여부 판단
            success = execution_plan is not None and error_message is None
            
            return ExtractionResult(
                success=success,
                execution_plan=execution_plan,
                schema_context=final_state.get("schema_context"),
                resolved_parameters=final_state.get("resolved_parameters"),
                cohort_filters=final_state.get("cohort_filters"),
                temporal_context=final_state.get("temporal_context"),
                has_ambiguity=has_ambiguity,
                ambiguities=final_state.get("ambiguities"),
                validation=validation,
                confidence=confidence,
                original_query=query,
                execution_time_seconds=execution_time,
                logs=final_state.get("logs", []),
                error_message=error_message,
            )
            
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            
            return ExtractionResult(
                success=False,
                original_query=query,
                execution_time_seconds=execution_time,
                error_message=str(e),
            )
    
    def extract_batch(self, queries: List[str]) -> List[ExtractionResult]:
        """
        여러 쿼리를 배치로 처리
        
        Args:
            queries: 쿼리 리스트
        
        Returns:
            ExtractionResult 리스트 (순서 유지)
        
        Example:
            results = facade.extract_batch([
                "위암 환자의 심박수",
                "폐암 환자의 혈압",
            ])
        """
        return [self.extract_with_state(q) for q in queries]
    
    def validate_query(self, query: str) -> Dict[str, Any]:
        """
        쿼리 유효성 검사 (실제 실행 없이)
        
        쿼리가 처리 가능한지, 모호성이 있는지 등을 미리 확인합니다.
        
        Args:
            query: 검사할 쿼리
        
        Returns:
            {
                "valid": bool,
                "has_ambiguity": bool,
                "ambiguities": [...],
                "estimated_parameters": [...],
                "warnings": [...]
            }
        """
        result = self.extract_with_state(query)
        
        return {
            "valid": result.success or result.has_ambiguity,
            "has_ambiguity": result.has_ambiguity,
            "ambiguities": result.ambiguities or [],
            "estimated_parameters": [
                p.get("term") for p in (result.resolved_parameters or [])
            ],
            "warnings": [log for log in result.logs if "warning" in log.lower()],
            "error": result.error_message,
        }
    
    def get_schema_context(self) -> Optional[Dict[str, Any]]:
        """
        현재 DB의 스키마 컨텍스트 반환
        
        ExtractionAgent가 사용하는 DB 메타데이터를 확인할 때 유용합니다.
        
        Returns:
            스키마 컨텍스트 또는 None
        """
        # 더미 쿼리로 스키마 컨텍스트만 추출
        result = self.extract_with_state("테스트")
        return result.schema_context
    
    def reset(self) -> None:
        """
        내부 상태 초기화
        
        Workflow를 다시 빌드하고 싶을 때 호출합니다.
        """
        self._workflow = None


# Convenience function
def extract_plan(query: str, verbose: bool = False) -> Dict[str, Any]:
    """
    단일 쿼리에서 Execution Plan 추출 (편의 함수)
    
    Args:
        query: 자연어 쿼리
        verbose: 빌드 정보 출력 여부
    
    Returns:
        Execution Plan JSON
    
    Example:
        from ExtractionAgent.src.facade import extract_plan
        
        plan = extract_plan("위암 환자의 수술 중 심박수")
    """
    facade = ExtractionFacade(verbose=verbose)
    return facade.extract(query)
