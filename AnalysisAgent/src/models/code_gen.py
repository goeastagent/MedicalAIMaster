"""Code Generation 전용 모델"""

from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel, Field

from .context import ExecutionContext


class CodeRequest(BaseModel):
    """코드 생성 요청 (Agent → Generator)
    
    Agent가 코드 생성이 필요하다고 판단했을 때 Generator에게 전달.
    
    Example:
        request = CodeRequest(
            task_description="심박수가 100 이상인 구간의 비율 계산",
            expected_output="0.0 ~ 1.0 사이의 float (비율)",
            execution_context=context,
            hints="df['HR'] > 100 조건 사용",
            constraints=["루프 대신 벡터 연산 사용", "NaN 처리 필수"]
        )
    """
    
    task_description: str
    """무엇을 하는 코드인지 설명
    
    예: "심박수가 100 이상인 구간의 비율 계산"
    """
    
    expected_output: str
    """기대하는 출력 형태
    
    예: "0.0 ~ 1.0 사이의 float (비율)"
    생성된 코드는 반드시 `result` 변수에 이 형태로 결과를 저장해야 함.
    """
    
    execution_context: ExecutionContext
    """실행 컨텍스트 (사용 가능한 변수, import 등)"""
    
    hints: Optional[str] = None
    """구현 힌트 (선택)
    
    예: "df['HR'] > 100 조건 사용"
    """
    
    constraints: Optional[List[str]] = None
    """추가 제약사항 (선택)
    
    예: ["루프 대신 벡터 연산 사용", "NaN 처리 필수"]
    """


class ValidationResult(BaseModel):
    """검증 결과 (Validator → Generator/Agent)
    
    CodeValidator가 생성된 코드를 검증한 결과.
    
    Example:
        result = ValidationResult(
            is_valid=False,
            errors=["Forbidden pattern detected: 'os.system'"],
            warnings=["Using explicit loop instead of vectorized operation"]
        )
    """
    
    is_valid: bool
    """검증 통과 여부"""
    
    errors: List[str] = Field(default_factory=list)
    """치명적 에러 목록 (금지 패턴, 허용되지 않은 import 등)
    
    errors가 있으면 코드 실행 불가.
    """
    
    warnings: List[str] = Field(default_factory=list)
    """경고 목록 (비효율적 코드, 권장사항 위반 등)
    
    warnings는 실행은 가능하지만 개선이 필요한 사항.
    """


class GenerationResult(BaseModel):
    """생성 결과 (Generator → Agent)
    
    CodeGenerator가 코드를 생성하고 검증한 결과.
    
    Example:
        result = GenerationResult(
            code="result = (df['HR'] > 100).mean()",
            is_valid=True,
            validation_errors=[],
            validation_warnings=[]
        )
    """
    
    code: str
    """생성된 코드
    
    실행 시 `result` 변수에 결과가 저장되어야 함.
    """
    
    is_valid: bool
    """검증 통과 여부
    
    False인 경우 코드 실행하면 안 됨.
    """
    
    validation_errors: List[str] = Field(default_factory=list)
    """검증 에러 목록"""
    
    validation_warnings: List[str] = Field(default_factory=list)
    """검증 경고 목록"""


class ExecutionResult(BaseModel):
    """실행 결과 (Executor → Agent)
    
    SandboxExecutor가 코드를 실행한 결과.
    
    Example (성공):
        result = ExecutionResult(
            success=True,
            result=0.35,  # 35%
            execution_time_ms=12.5
        )
    
    Example (실패):
        result = ExecutionResult(
            success=False,
            error="NameError: name 'undefined_var' is not defined",
            error_type="runtime",
            execution_time_ms=5.2
        )
    """
    
    success: bool
    """실행 성공 여부"""
    
    result: Optional[Any] = None
    """`result` 변수의 값 (성공 시)
    
    생성된 코드가 `result = ...` 형태로 결과를 저장해야 함.
    """
    
    error: Optional[str] = None
    """에러 메시지 (실패 시)"""
    
    error_type: Optional[Literal["timeout", "runtime", "memory", "security"]] = None
    """에러 유형
    
    - timeout: 실행 시간 초과
    - runtime: 런타임 에러 (NameError, TypeError 등)
    - memory: 메모리 초과
    - security: 보안 위반 (샌드박스 탈출 시도)
    """
    
    execution_time_ms: Optional[float] = None
    """실행 시간 (밀리초)"""
    
    stdout: Optional[str] = None
    """print 출력 (선택적)
    
    디버깅 목적으로 캡처.
    """


class CodeResult(BaseModel):
    """최종 결과 (Agent가 조합해서 반환)
    
    Agent가 Generate → Validate → Execute 과정을 거쳐
    최종적으로 반환하는 결과.
    
    Example (성공):
        result = CodeResult(
            success=True,
            generated_code="result = (df['HR'] > 100).mean()",
            execution_result=0.35,
            execution_time_ms=12.5
        )
    
    Example (실패):
        result = CodeResult(
            success=False,
            generated_code="result = df['HR'].mean()",
            error_type="execution",
            error_message="KeyError: 'HR'",
            retry_count=2
        )
    """
    
    success: bool
    """전체 과정 성공 여부"""
    
    generated_code: str
    """생성된 코드 (성공/실패 무관하게 기록)"""
    
    execution_result: Optional[Any] = None
    """실행 결과 (성공 시)"""
    
    error_type: Optional[Literal["generation", "validation", "execution"]] = None
    """에러 발생 단계 (실패 시)
    
    - generation: LLM 코드 생성 실패
    - validation: 코드 검증 실패 (금지 패턴 등)
    - execution: 코드 실행 실패 (런타임 에러 등)
    """
    
    error_message: Optional[str] = None
    """에러 메시지 (실패 시)"""
    
    execution_time_ms: Optional[float] = None
    """총 실행 시간 (밀리초)"""
    
    retry_count: int = 0
    """재시도 횟수
    
    Agent가 실패 후 재시도한 횟수.
    """

