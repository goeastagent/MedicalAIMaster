# OrchestrationAgent - 경량 설계

## 📖 개요

OrchestrationAgent는 **ExtractionAgent**와 **AnalysisAgent(CodeGen)**를 연결하는 **얇은 조율 레이어**입니다.

### 핵심 철학

```
최소 구현 (MVP First)
├── 복잡한 그래프 없이 순차 실행
├── 3개 컴포넌트만 연결: Extraction → DataContext → CodeGen
└── 필요해지면 확장
```

---

## 🔄 전체 흐름

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         사용자 질의                                      │
│          "2023년 위암 환자의 심박수 평균을 성별로 비교해줘"                  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Orchestrator                                      │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐  │
│   │ Step 1: ExtractionAgent 호출                                      │  │
│   │ • 쿼리 → Execution Plan 생성                                      │  │
│   │ • 어떤 데이터가 필요한지, 어디서 가져올지 계획                       │  │
│   └────────────────────────────┬─────────────────────────────────────┘  │
│                                │                                         │
│                                ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────┐  │
│   │ Step 2: DataContext로 데이터 로드                                  │  │
│   │ • Execution Plan 해석                                             │  │
│   │ • Cohort + Signal 데이터 로드                                     │  │
│   │ • runtime_data 준비 (df, cohort, case_ids, param_keys)           │  │
│   └────────────────────────────┬─────────────────────────────────────┘  │
│                                │                                         │
│                                ▼                                         │
│   ┌──────────────────────────────────────────────────────────────────┐  │
│   │ Step 3: CodeGenerator로 분석 실행                                  │  │
│   │ • 분석 태스크 → Python 코드 생성                                   │  │
│   │ • Sandbox에서 안전하게 실행                                        │  │
│   │ • 실패 시 에러 컨텍스트와 함께 재시도                               │  │
│   └────────────────────────────┬─────────────────────────────────────┘  │
│                                │                                         │
└────────────────────────────────┼────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         분석 결과 반환                                    │
│          {"status": "success", "result": {...}, "code": "..."}           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 파일 구조

```
OrchestrationAgent/
├── src/
│   ├── __init__.py
│   ├── orchestrator.py          # 메인 클래스 (핵심)
│   ├── models.py                # 입출력 모델
│   └── config.py                # 설정
│
├── tests/
│   ├── __init__.py
│   ├── test_orchestrator.py     # 단위 테스트
│   └── test_e2e.py              # E2E 테스트
│
├── examples/
│   └── basic_usage.py
│
├── ARCHITECTURE.md              # 이 문서
├── requirements.txt
└── README.md
```

---

## 📋 구현 상세

### 1. 모델 정의 (`src/models.py`)

```python
"""Orchestrator 입출력 모델"""

from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class OrchestrationRequest(BaseModel):
    """오케스트레이션 요청"""
    
    query: str
    # "2023년 위암 환자의 심박수 평균을 성별로 비교해줘"
    
    # 선택적 옵션
    max_retries: int = Field(default=2, ge=0, le=5)
    timeout_seconds: int = Field(default=30, ge=5, le=120)
    auto_resolve_ambiguity: bool = True


class OrchestrationResult(BaseModel):
    """오케스트레이션 결과"""
    
    status: Literal["success", "error", "partial"]
    
    # 성공 시
    result: Optional[Any] = None
    generated_code: Optional[str] = None
    
    # 실패 시
    error_message: Optional[str] = None
    error_stage: Optional[Literal["extraction", "data_load", "analysis"]] = None
    
    # 메타데이터
    execution_time_ms: Optional[float] = None
    data_summary: Optional[Dict[str, Any]] = None
    
    # 디버그 정보 (선택적)
    extraction_plan: Optional[Dict[str, Any]] = None
    retry_count: int = 0


class AnalysisTask(BaseModel):
    """분석 태스크 (CodeGen에 전달)"""
    
    description: str
    # "심박수(HR)의 평균을 성별로 그룹화하여 계산"
    
    expected_output: str = "분석 결과를 result 변수에 저장"
    # "딕셔너리 형태: {sex: mean_hr}"
    
    hints: Optional[str] = None
    # "df.groupby() 사용, cohort에서 sex 컬럼 참조"
```

---

### 2. 메인 클래스 (`src/orchestrator.py`)

```python
"""경량 Orchestrator - ExtractionAgent + DataContext + CodeGen 연결"""

import time
from typing import Dict, Any, Optional
from .models import OrchestrationRequest, OrchestrationResult, AnalysisTask
from .config import OrchestratorConfig


class Orchestrator:
    """
    ExtractionAgent와 AnalysisAgent(CodeGen)를 연결하는 오케스트레이터
    
    사용법:
        orchestrator = Orchestrator()
        result = orchestrator.run("위암 환자의 심박수 평균을 구해줘")
        
        if result.status == "success":
            print(result.result)
            print(result.generated_code)
    """
    
    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.config = config or OrchestratorConfig()
        
        # Lazy initialization
        self._extraction_agent = None
        self._data_context = None
        self._code_generator = None
        self._sandbox = None
        self._llm_client = None
    
    # =========================================================================
    # Public API
    # =========================================================================
    
    def run(
        self, 
        query: str,
        max_retries: int = None,
        timeout_seconds: int = None
    ) -> OrchestrationResult:
        """
        질의 실행 - 전체 파이프라인
        
        Args:
            query: 자연어 질의
            max_retries: 코드 생성 재시도 횟수 (기본: config 값)
            timeout_seconds: 실행 타임아웃 (기본: config 값)
        
        Returns:
            OrchestrationResult
        """
        start_time = time.time()
        
        max_retries = max_retries if max_retries is not None else self.config.max_retries
        timeout = timeout_seconds if timeout_seconds is not None else self.config.timeout_seconds
        
        try:
            # Step 1: Extraction - 실행 계획 생성
            extraction_result = self._run_extraction(query)
            
            if not extraction_result.get("execution_plan"):
                return OrchestrationResult(
                    status="error",
                    error_message="Extraction failed: No execution plan generated",
                    error_stage="extraction",
                    extraction_plan=extraction_result
                )
            
            execution_plan = extraction_result["execution_plan"]
            
            # Step 2: Data Load - 데이터 로드
            runtime_data, data_summary = self._load_data(execution_plan)
            
            if not runtime_data:
                return OrchestrationResult(
                    status="error",
                    error_message="Data loading failed: No data available",
                    error_stage="data_load",
                    extraction_plan=execution_plan
                )
            
            # Step 3: Analysis - 코드 생성 및 실행
            analysis_result = self._run_analysis(
                query=query,
                runtime_data=runtime_data,
                data_summary=data_summary,
                max_retries=max_retries,
                timeout=timeout
            )
            
            execution_time = (time.time() - start_time) * 1000
            
            return OrchestrationResult(
                status="success" if analysis_result["success"] else "error",
                result=analysis_result.get("result"),
                generated_code=analysis_result.get("code"),
                error_message=analysis_result.get("error"),
                error_stage="analysis" if not analysis_result["success"] else None,
                execution_time_ms=execution_time,
                data_summary=data_summary,
                extraction_plan=execution_plan,
                retry_count=analysis_result.get("retry_count", 0)
            )
        
        except Exception as e:
            return OrchestrationResult(
                status="error",
                error_message=str(e),
                execution_time_ms=(time.time() - start_time) * 1000
            )
    
    def run_with_plan(
        self,
        query: str,
        execution_plan: Dict[str, Any],
        max_retries: int = None
    ) -> OrchestrationResult:
        """
        이미 있는 Execution Plan으로 분석 실행
        (ExtractionAgent 스킵)
        
        Args:
            query: 분석 질의
            execution_plan: 미리 생성된 실행 계획
            max_retries: 재시도 횟수
        """
        start_time = time.time()
        max_retries = max_retries if max_retries is not None else self.config.max_retries
        
        try:
            # Data Load
            runtime_data, data_summary = self._load_data(execution_plan)
            
            if not runtime_data:
                return OrchestrationResult(
                    status="error",
                    error_message="Data loading failed",
                    error_stage="data_load"
                )
            
            # Analysis
            analysis_result = self._run_analysis(
                query=query,
                runtime_data=runtime_data,
                data_summary=data_summary,
                max_retries=max_retries
            )
            
            return OrchestrationResult(
                status="success" if analysis_result["success"] else "error",
                result=analysis_result.get("result"),
                generated_code=analysis_result.get("code"),
                error_message=analysis_result.get("error"),
                execution_time_ms=(time.time() - start_time) * 1000,
                data_summary=data_summary,
                retry_count=analysis_result.get("retry_count", 0)
            )
        
        except Exception as e:
            return OrchestrationResult(
                status="error",
                error_message=str(e)
            )
    
    def run_analysis_only(
        self,
        query: str,
        runtime_data: Dict[str, Any],
        max_retries: int = None
    ) -> OrchestrationResult:
        """
        데이터가 이미 있을 때 분석만 실행
        (Extraction + DataLoad 스킵)
        
        Args:
            query: 분석 질의
            runtime_data: 이미 로드된 데이터 {"df": ..., "cohort": ...}
            max_retries: 재시도 횟수
        """
        start_time = time.time()
        max_retries = max_retries if max_retries is not None else self.config.max_retries
        
        # 데이터 요약 생성
        data_summary = self._create_data_summary(runtime_data)
        
        # Analysis
        analysis_result = self._run_analysis(
            query=query,
            runtime_data=runtime_data,
            data_summary=data_summary,
            max_retries=max_retries
        )
        
        return OrchestrationResult(
            status="success" if analysis_result["success"] else "error",
            result=analysis_result.get("result"),
            generated_code=analysis_result.get("code"),
            error_message=analysis_result.get("error"),
            execution_time_ms=(time.time() - start_time) * 1000,
            data_summary=data_summary,
            retry_count=analysis_result.get("retry_count", 0)
        )
    
    # =========================================================================
    # Step 1: Extraction
    # =========================================================================
    
    def _run_extraction(self, query: str) -> Dict[str, Any]:
        """ExtractionAgent 호출하여 Execution Plan 생성"""
        
        if self._extraction_agent is None:
            self._extraction_agent = self._create_extraction_agent()
        
        # ExtractionAgent 실행
        result = self._extraction_agent.invoke({"user_query": query})
        
        # 결과에서 plan 추출
        return {
            "execution_plan": result.get("validated_plan") or result.get("execution_plan"),
            "confidence": result.get("overall_confidence", 0.0),
            "ambiguities": result.get("ambiguities", []),
            "intent": result.get("intent")
        }
    
    def _create_extraction_agent(self):
        """ExtractionAgent 인스턴스 생성"""
        from ExtractionAgent.src.agents.graph import create_extraction_graph
        return create_extraction_graph()
    
    # =========================================================================
    # Step 2: Data Load
    # =========================================================================
    
    def _load_data(
        self, 
        execution_plan: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """DataContext로 데이터 로드"""
        
        from shared.data.context import DataContext
        
        ctx = DataContext()
        ctx.load_from_plan(execution_plan, preload_cohort=True)
        
        # runtime_data 구성
        runtime_data = {}
        
        # Cohort
        cohort = ctx.get_cohort()
        if not cohort.empty:
            runtime_data["cohort"] = cohort
        
        # Signals
        signals = ctx.get_signals()
        if not signals.empty:
            runtime_data["df"] = signals
        
        # 메타데이터
        runtime_data["case_ids"] = ctx.get_case_ids()
        runtime_data["param_keys"] = ctx.get_available_parameters()
        
        # 요약 생성
        data_summary = ctx.summary()
        
        # DataContext 저장 (재사용 가능)
        self._data_context = ctx
        
        return runtime_data, data_summary
    
    def _create_data_summary(self, runtime_data: Dict[str, Any]) -> Dict[str, Any]:
        """runtime_data에서 요약 생성"""
        summary = {}
        
        if "df" in runtime_data:
            df = runtime_data["df"]
            summary["signals"] = {
                "shape": df.shape,
                "columns": list(df.columns)
            }
        
        if "cohort" in runtime_data:
            cohort = runtime_data["cohort"]
            summary["cohort"] = {
                "shape": cohort.shape,
                "columns": list(cohort.columns)
            }
        
        summary["case_count"] = len(runtime_data.get("case_ids", []))
        summary["param_keys"] = runtime_data.get("param_keys", [])
        
        return summary
    
    # =========================================================================
    # Step 3: Analysis (CodeGen)
    # =========================================================================
    
    def _run_analysis(
        self,
        query: str,
        runtime_data: Dict[str, Any],
        data_summary: Dict[str, Any],
        max_retries: int = 2,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """CodeGenerator로 분석 코드 생성 및 실행"""
        
        # 컴포넌트 초기화
        if self._code_generator is None:
            self._init_code_gen_components()
        
        # ExecutionContext 생성
        exec_context = self._build_execution_context(runtime_data, data_summary)
        
        # CodeRequest 생성
        request = self._build_code_request(query, exec_context, data_summary)
        
        # 생성 + 실행 (with retry)
        last_error = None
        generated_code = None
        
        for attempt in range(max_retries + 1):
            # 첫 시도 또는 재시도
            if attempt == 0:
                gen_result = self._code_generator.generate(request)
            else:
                gen_result = self._code_generator.generate_with_fix(
                    request, 
                    generated_code, 
                    last_error
                )
            
            generated_code = gen_result.code
            
            # 검증 실패
            if not gen_result.is_valid:
                last_error = f"Validation failed: {gen_result.validation_errors}"
                continue
            
            # 실행
            exec_result = self._sandbox.execute(gen_result.code, runtime_data)
            
            if exec_result.success:
                return {
                    "success": True,
                    "result": exec_result.result,
                    "code": gen_result.code,
                    "retry_count": attempt
                }
            
            last_error = exec_result.error
        
        # 모든 재시도 실패
        return {
            "success": False,
            "error": last_error,
            "code": generated_code,
            "retry_count": max_retries + 1
        }
    
    def _init_code_gen_components(self):
        """CodeGenerator와 Sandbox 초기화"""
        from AnalysisAgent.src.code_gen import CodeGenerator, SandboxExecutor
        from shared.llm import get_llm_client
        
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        
        self._code_generator = CodeGenerator(llm_client=self._llm_client)
        self._sandbox = SandboxExecutor(timeout_seconds=self.config.timeout_seconds)
    
    def _build_execution_context(
        self, 
        runtime_data: Dict[str, Any],
        data_summary: Dict[str, Any]
    ):
        """CodeGen용 ExecutionContext 생성"""
        from AnalysisAgent.src.models import ExecutionContext
        
        # 사용 가능한 변수 설명
        available_variables = {}
        
        if "df" in runtime_data:
            df = runtime_data["df"]
            available_variables["df"] = (
                f"pandas DataFrame - Signal 데이터, "
                f"shape: {df.shape}, columns: {list(df.columns)[:10]}"
            )
        
        if "cohort" in runtime_data:
            cohort = runtime_data["cohort"]
            available_variables["cohort"] = (
                f"pandas DataFrame - Cohort 메타데이터, "
                f"shape: {cohort.shape}, columns: {list(cohort.columns)[:10]}"
            )
        
        available_variables["case_ids"] = f"List[str] - {len(runtime_data.get('case_ids', []))}개 케이스 ID"
        available_variables["param_keys"] = f"List[str] - 파라미터 키 목록: {runtime_data.get('param_keys', [])}"
        
        # 샘플 데이터 (LLM 참고용)
        sample_data = {}
        if "df" in runtime_data and not runtime_data["df"].empty:
            sample_data["df_head"] = runtime_data["df"].head(3).to_dict(orient="records")
        if "cohort" in runtime_data and not runtime_data["cohort"].empty:
            sample_data["cohort_head"] = runtime_data["cohort"].head(3).to_dict(orient="records")
        
        return ExecutionContext(
            available_variables=available_variables,
            sample_data=sample_data if sample_data else None
        )
    
    def _build_code_request(
        self, 
        query: str,
        exec_context,
        data_summary: Dict[str, Any]
    ):
        """CodeRequest 생성"""
        from AnalysisAgent.src.models import CodeRequest
        
        # 힌트 생성
        hints = self._generate_hints(query, data_summary)
        
        return CodeRequest(
            task_description=query,
            expected_output="분석 결과를 result 변수에 저장. 딕셔너리, 숫자, 또는 DataFrame 형태.",
            execution_context=exec_context,
            hints=hints,
            constraints=[
                "NaN 값은 dropna() 또는 fillna()로 처리",
                "result 변수에 최종 결과 저장 필수",
                "루프 대신 pandas/numpy 벡터 연산 사용"
            ]
        )
    
    def _generate_hints(self, query: str, data_summary: Dict[str, Any]) -> str:
        """질의 기반 구현 힌트 생성"""
        hints = []
        
        # 키워드 기반 힌트
        query_lower = query.lower()
        
        if "평균" in query_lower or "mean" in query_lower:
            hints.append("df['column'].mean() 또는 df.groupby('group')['column'].mean() 사용")
        
        if "비교" in query_lower or "그룹" in query_lower or "성별" in query_lower:
            hints.append("cohort DataFrame에서 그룹 정보 참조 (예: cohort['sex'])")
            hints.append("df와 cohort를 case_id로 조인 필요할 수 있음")
        
        if "상관" in query_lower or "correlation" in query_lower:
            hints.append("scipy.stats.pearsonr() 또는 df.corr() 사용")
        
        if "분포" in query_lower or "distribution" in query_lower:
            hints.append("df['column'].describe() 또는 value_counts() 사용")
        
        # 데이터 구조 힌트
        if data_summary.get("param_keys"):
            hints.append(f"사용 가능한 signal 파라미터: {data_summary['param_keys'][:5]}")
        
        return "\n".join(hints) if hints else None
    
    # =========================================================================
    # Utility
    # =========================================================================
    
    def get_data_context(self):
        """현재 DataContext 반환 (데이터 재사용용)"""
        return self._data_context
    
    def clear_cache(self):
        """캐시 정리"""
        from shared.data.context import DataContext
        DataContext.clear_cache()
        self._data_context = None
```

---

### 3. 설정 (`src/config.py`)

```python
"""Orchestrator 설정"""

from dataclasses import dataclass


@dataclass
class OrchestratorConfig:
    """오케스트레이터 설정"""
    
    # 코드 생성
    max_retries: int = 2
    timeout_seconds: int = 30
    
    # ExtractionAgent
    auto_resolve_ambiguity: bool = True
    
    # DataContext
    preload_cohort: bool = True
    cache_signals: bool = True
```

---

### 4. 패키지 초기화 (`src/__init__.py`)

```python
"""OrchestrationAgent - 경량 오케스트레이터"""

from .orchestrator import Orchestrator
from .models import OrchestrationRequest, OrchestrationResult, AnalysisTask
from .config import OrchestratorConfig

__all__ = [
    "Orchestrator",
    "OrchestrationRequest",
    "OrchestrationResult",
    "AnalysisTask",
    "OrchestratorConfig",
]
```

---

## 🎯 사용 예시

### 기본 사용

```python
from OrchestrationAgent.src import Orchestrator

# 오케스트레이터 생성
orchestrator = Orchestrator()

# 질의 실행
result = orchestrator.run(
    "2023년 위암 환자의 심박수 평균을 성별로 비교해줘"
)

# 결과 확인
if result.status == "success":
    print("분석 결과:", result.result)
    print("생성된 코드:")
    print(result.generated_code)
else:
    print("에러:", result.error_message)
    print("실패 단계:", result.error_stage)
```

### 단계별 실행 (디버깅용)

```python
orchestrator = Orchestrator()

# Step 1: Extraction만 실행
extraction_result = orchestrator._run_extraction(
    "위암 환자의 심박수 데이터"
)
print("Execution Plan:", extraction_result["execution_plan"])

# Step 2: 데이터 로드
runtime_data, summary = orchestrator._load_data(
    extraction_result["execution_plan"]
)
print("로드된 케이스 수:", len(runtime_data["case_ids"]))
print("Signal shape:", runtime_data["df"].shape)

# Step 3: 분석만 실행
result = orchestrator.run_analysis_only(
    query="심박수 평균을 구해줘",
    runtime_data=runtime_data
)
print("결과:", result.result)
```

### 데이터 재사용

```python
orchestrator = Orchestrator()

# 첫 번째 질의 (데이터 로드 포함)
result1 = orchestrator.run("위암 환자의 심박수 평균")

# 같은 데이터로 추가 분석 (데이터 로드 스킵)
ctx = orchestrator.get_data_context()
runtime_data = {
    "df": ctx.get_signals(),
    "cohort": ctx.get_cohort(),
    "case_ids": ctx.get_case_ids(),
    "param_keys": ctx.get_available_parameters()
}

result2 = orchestrator.run_analysis_only(
    query="SpO2의 분포를 보여줘",
    runtime_data=runtime_data
)
```

---

## ✅ 구현 체크리스트

```
=== Phase 1: 핵심 구현 (우선) ===
[ ] 1. 디렉토리 구조 생성
[ ] 2. src/models.py
[ ] 3. src/config.py
[ ] 4. src/orchestrator.py
[ ] 5. src/__init__.py

=== Phase 2: 테스트 ===
[ ] 6. tests/test_orchestrator.py (Mock 사용)
[ ] 7. tests/test_e2e.py (실제 LLM 사용)

=== Phase 3: 문서화 ===
[ ] 8. examples/basic_usage.py
[ ] 9. README.md
[ ] 10. requirements.txt
```

---

## 🔗 의존성

```python
# 필요한 import들

# ExtractionAgent
from ExtractionAgent.src.agents.graph import create_extraction_graph

# AnalysisAgent (CodeGen)
from AnalysisAgent.src.code_gen import CodeGenerator, SandboxExecutor
from AnalysisAgent.src.models import CodeRequest, ExecutionContext

# Shared
from shared.data.context import DataContext
from shared.llm import get_llm_client
```

---

## 📝 확장 포인트

나중에 필요하면 추가:

| 기능 | 설명 | 우선순위 |
|------|------|---------|
| **IntentRouter** | 질의 유형 분류 (extraction_only vs analysis) | 낮음 |
| **SessionManager** | 멀티턴 대화, follow-up 지원 | 중간 |
| **ToolRegistry** | 미리 정의된 분석 Tool 등록/사용 | 낮음 |
| **ResultCache** | 동일 질의 결과 캐싱 | 중간 |
| **StreamingResult** | 대용량 데이터 스트리밍 처리 | 낮음 |

---

## 요약

```
Orchestrator = 얇은 연결 레이어

run(query)
├── _run_extraction(query)      # ExtractionAgent → Plan
├── _load_data(plan)            # DataContext → runtime_data  
└── _run_analysis(query, data)  # CodeGenerator → result

총 ~300줄, 핵심 로직만 구현
```
