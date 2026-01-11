"""Code Generation 전용 모델"""

from typing import Dict, List, Any, Optional, Literal, TYPE_CHECKING
from pydantic import BaseModel, Field

from .context import ExecutionContext

if TYPE_CHECKING:
    import pandas as pd


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


# =============================================================================
# Map-Reduce 패턴 모델 (대용량 데이터 처리용)
# =============================================================================

class MapReduceRequest(BaseModel):
    """범용 Map-Reduce 코드 생성 요청
    
    대용량 데이터셋을 배치 처리할 때 사용하는 Map-Reduce 패턴 요청.
    다양한 데이터셋 (의료, IoT, 금융 등)에서 범용적으로 사용 가능.
    
    Example:
        request = MapReduceRequest(
            task_description="각 센서별 평균 온도 계산 후 전체 평균",
            expected_output="{sensor_id: mean_temp} 형태의 dict",
            entity_id_column="sensor_id",
            total_entities=5000,
            entity_data_columns=["timestamp", "temperature", "humidity"],
            metadata_columns=["sensor_id", "location", "install_date"],
        )
    """
    
    # === 분석 요청 ===
    task_description: str
    """분석 태스크 설명
    
    예: "각 환자별 평균 심박수 계산"
    """
    
    expected_output: str
    """기대하는 최종 출력 형태
    
    예: "{patient_id: mean_hr} 형태의 dictionary"
    """
    
    hints: Optional[str] = None
    """구현 힌트 (선택)
    
    예: "10분 단위로 segmentation 후 평균"
    """
    
    constraints: Optional[List[str]] = None
    """추가 제약사항 (선택)
    
    예: ["NaN 값 제외", "음수 값 무시"]
    """
    
    # === 데이터셋 정보 (범용) ===
    dataset_type: Optional[str] = None
    """데이터셋 유형 (선택)
    
    예: "medical", "iot", "financial", "sensor"
    """
    
    dataset_description: Optional[str] = None
    """데이터셋 자연어 설명 (선택)
    
    예: "VitalDB 수술 중 생체신호 데이터"
    """
    
    # === 엔티티 정보 (범용) ===
    entity_id_column: str = "id"
    """엔티티 식별자 컬럼명
    
    예: "caseid", "sensor_id", "account_id"
    """
    
    total_entities: int = 0
    """처리할 총 엔티티 수"""
    
    # === 스키마 정보 (동적) ===
    entity_data_columns: List[str] = Field(default_factory=list)
    """엔티티 데이터의 컬럼 목록
    
    예: ["Time", "HR", "SpO2", "BP"]
    """
    
    entity_data_dtypes: Dict[str, str] = Field(default_factory=dict)
    """엔티티 데이터 컬럼별 데이터 타입
    
    예: {"Time": "float64", "HR": "float32"}
    """
    
    entity_data_sample: Optional[str] = None
    """엔티티 데이터 샘플 (문자열, 프롬프트용)
    
    DataFrame.head().to_string() 결과
    """
    
    metadata_columns: List[str] = Field(default_factory=list)
    """메타데이터 컬럼 목록
    
    예: ["caseid", "age", "sex", "optype"]
    """
    
    metadata_dtypes: Dict[str, str] = Field(default_factory=dict)
    """메타데이터 컬럼별 데이터 타입"""
    
    metadata_sample: Optional[str] = None
    """메타데이터 샘플 (문자열, 프롬프트용)"""
    
    # === 허용 임포트 ===
    allowed_imports: List[str] = Field(default_factory=lambda: [
        "pandas as pd", 
        "numpy as np", 
        "scipy.stats as stats", 
        "math", 
        "datetime", 
        "statistics", 
        "collections"
    ])
    """코드에서 사용 가능한 import 목록"""
    
    class Config:
        """Pydantic 설정"""
        arbitrary_types_allowed = True


class MapReduceGenerationResult(BaseModel):
    """Map-Reduce 코드 생성 결과
    
    map_func와 reduce_func 두 함수의 생성 결과.
    
    Example (성공):
        result = MapReduceGenerationResult(
            full_code="def map_func(...):\\n    ...\\ndef reduce_func(...):\\n    ...",
            map_code="def map_func(...):\\n    ...",
            reduce_code="def reduce_func(...):\\n    ...",
            is_valid=True,
        )
    """
    
    full_code: str
    """LLM이 생성한 전체 코드"""
    
    map_code: str
    """추출된 map_func 코드
    
    빈 문자열이면 추출 실패.
    """
    
    reduce_code: str
    """추출된 reduce_func 코드
    
    빈 문자열이면 추출 실패.
    """
    
    is_valid: bool
    """검증 통과 여부
    
    False면 실행하면 안 됨.
    """
    
    validation_errors: List[str] = Field(default_factory=list)
    """검증 에러 목록"""
    
    validation_warnings: List[str] = Field(default_factory=list)
    """검증 경고 목록"""


class MapReduceExecutionResult(BaseModel):
    """Map-Reduce 실행 결과
    
    전체 Map-Reduce 파이프라인 실행 결과.
    
    Example (성공):
        result = MapReduceExecutionResult(
            success=True,
            result={"patient_1": 72.5, "patient_2": 68.3},
            total_entities=1000,
            successful_maps=998,
            failed_maps=2,
        )
    """
    
    success: bool
    """전체 실행 성공 여부"""
    
    result: Optional[Any] = None
    """reduce_func의 최종 결과"""
    
    total_entities: int = 0
    """처리 대상 엔티티 수"""
    
    successful_maps: int = 0
    """성공한 map_func 호출 수"""
    
    failed_maps: int = 0
    """실패한 map_func 호출 수"""
    
    map_errors: List[Dict[str, str]] = Field(default_factory=list)
    """map_func 에러 목록 (entity_id, error)"""
    
    reduce_error: Optional[str] = None
    """reduce_func 에러 메시지"""
    
    execution_time_ms: Optional[float] = None
    """총 실행 시간 (밀리초)"""
    
    map_time_ms: Optional[float] = None
    """Map Phase 실행 시간 (밀리초)"""
    
    reduce_time_ms: Optional[float] = None
    """Reduce Phase 실행 시간 (밀리초)"""

