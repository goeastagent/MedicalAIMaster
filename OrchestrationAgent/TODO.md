# OrchestrationAgent 구현 TODO

> 경량 Orchestrator - ExtractionAgent + DataContext + CodeGen 연결

---

## 📋 Phase 1: 기본 구조 (Day 1)

### 1.1 디렉토리 생성

```
[ ] OrchestrationAgent/
    ├── src/
    │   ├── __init__.py
    │   ├── orchestrator.py
    │   ├── models.py
    │   └── config.py
    ├── tests/
    │   └── __init__.py
    ├── examples/
    ├── ARCHITECTURE.md ✅
    ├── TODO.md ✅
    └── requirements.txt
```

### 1.2 모델 정의 (`src/models.py`)

```
[ ] OrchestrationRequest
    - query: str
    - max_retries: int = 2
    - timeout_seconds: int = 30

[ ] OrchestrationResult
    - status: Literal["success", "error", "partial"]
    - result: Optional[Any]
    - generated_code: Optional[str]
    - error_message: Optional[str]
    - error_stage: Optional[str]
    - execution_time_ms: Optional[float]
    - data_summary: Optional[Dict]
    - retry_count: int

[ ] AnalysisTask (선택적)
    - description: str
    - expected_output: str
    - hints: Optional[str]
```

### 1.3 설정 (`src/config.py`)

```
[ ] OrchestratorConfig
    - max_retries: int = 2
    - timeout_seconds: int = 30
    - auto_resolve_ambiguity: bool = True
    - preload_cohort: bool = True
```

---

## 📋 Phase 2: Orchestrator 핵심 구현 (Day 1-2)

### 2.1 기본 구조 (`src/orchestrator.py`)

```
[ ] class Orchestrator
    [ ] __init__(config)
    [ ] Lazy initialization 패턴
        - _extraction_agent
        - _data_context
        - _code_generator
        - _sandbox
        - _llm_client
```

### 2.2 Public API

```
[ ] run(query, max_retries, timeout) -> OrchestrationResult
    - 전체 파이프라인: Extraction → DataLoad → Analysis

[ ] run_with_plan(query, execution_plan, max_retries) -> OrchestrationResult
    - Plan 있을 때: DataLoad → Analysis

[ ] run_analysis_only(query, runtime_data, max_retries) -> OrchestrationResult
    - 데이터 있을 때: Analysis만
```

### 2.3 Step 1: Extraction

```
[ ] _run_extraction(query) -> Dict
    - ExtractionAgent 호출
    - execution_plan, confidence, ambiguities 추출

[ ] _create_extraction_agent()
    - from ExtractionAgent.src.agents.graph import create_extraction_graph
```

### 2.4 Step 2: Data Load

```
[ ] _load_data(execution_plan) -> (runtime_data, data_summary)
    - DataContext.load_from_plan()
    - cohort, signals 로드
    - runtime_data 구성: {df, cohort, case_ids, param_keys}

[ ] _create_data_summary(runtime_data) -> Dict
    - 데이터 요약 생성
```

### 2.5 Step 3: Analysis (CodeGen)

```
[ ] _run_analysis(query, runtime_data, data_summary, max_retries, timeout) -> Dict
    - CodeGenerator.generate() 호출
    - SandboxExecutor.execute() 실행
    - 실패 시 generate_with_fix()로 재시도

[ ] _init_code_gen_components()
    - CodeGenerator, SandboxExecutor 초기화

[ ] _build_execution_context(runtime_data, data_summary) -> ExecutionContext
    - available_variables 구성
    - sample_data 구성

[ ] _build_code_request(query, exec_context, data_summary) -> CodeRequest
    - task_description, expected_output, hints, constraints

[ ] _generate_hints(query, data_summary) -> str
    - 키워드 기반 힌트 생성 (평균, 비교, 상관, 분포 등)
```

### 2.6 Utility

```
[ ] get_data_context() -> DataContext
    - 현재 DataContext 반환

[ ] clear_cache()
    - DataContext 캐시 정리
```

---

## 📋 Phase 3: 패키지 완성 (Day 2)

### 3.1 패키지 초기화

```
[ ] src/__init__.py
    - Orchestrator export
    - 모델 export
    - 설정 export

[ ] requirements.txt
    - pydantic>=2.0
    - (ExtractionAgent, AnalysisAgent, shared는 로컬 import)
```

---

## 📋 Phase 4: 테스트 (Day 2-3)

### 4.1 단위 테스트 (`tests/test_orchestrator.py`)

```
[ ] TestOrchestratorInit
    - test_default_config
    - test_custom_config
    - test_lazy_initialization

[ ] TestRunAnalysisOnly (Mock 사용)
    - test_simple_query
    - test_with_hints
    - test_retry_on_error
    - test_timeout

[ ] TestBuildContext
    - test_execution_context_with_df
    - test_execution_context_with_cohort
    - test_hints_generation
```

### 4.2 통합 테스트 (`tests/test_integration.py`)

```
[ ] TestFullPipeline (실제 컴포넌트 사용, Mock LLM)
    - test_extraction_to_analysis
    - test_run_with_plan
    - test_error_handling

[ ] TestWithRealLLM (선택적, @pytest.mark.slow)
    - test_simple_aggregation
    - test_groupby_analysis
```

---

## 📋 Phase 5: 예제 및 문서 (Day 3)

### 5.1 예제

```
[ ] examples/basic_usage.py
    - 기본 사용법
    - 결과 처리
    - 에러 핸들링

[ ] examples/step_by_step.py
    - 단계별 실행
    - 디버깅 방법
```

### 5.2 문서

```
[ ] README.md
    - 설치
    - 빠른 시작
    - API 레퍼런스
    - 예제
```

---

## 📋 체크포인트

### Checkpoint 1: 기본 동작 (Phase 1-2 완료 후)

```
[ ] Orchestrator 인스턴스 생성 가능
[ ] run_analysis_only()가 Mock 데이터로 동작
[ ] 에러 발생 시 적절한 OrchestrationResult 반환
```

### Checkpoint 2: 전체 파이프라인 (Phase 3 완료 후)

```
[ ] run()이 전체 파이프라인 실행
[ ] ExtractionAgent 연동 동작
[ ] DataContext 연동 동작
[ ] CodeGenerator 연동 동작
```

### Checkpoint 3: 프로덕션 준비 (Phase 4-5 완료 후)

```
[ ] 단위 테스트 통과
[ ] 통합 테스트 통과
[ ] 예제 코드 동작
[ ] 문서화 완료
```

---

## 🔧 구현 순서 (권장)

```
Day 1 (오전)
├── 1. 디렉토리 구조 생성
├── 2. src/models.py 구현
└── 3. src/config.py 구현

Day 1 (오후)
├── 4. src/orchestrator.py 기본 구조
├── 5. _run_analysis() 구현 (CodeGen 연동)
└── 6. run_analysis_only() 동작 확인

Day 2 (오전)
├── 7. _load_data() 구현 (DataContext 연동)
├── 8. _run_extraction() 구현 (ExtractionAgent 연동)
└── 9. run() 전체 파이프라인 동작 확인

Day 2 (오후)
├── 10. 테스트 작성
└── 11. 버그 수정

Day 3
├── 12. 예제 작성
├── 13. README 작성
└── 14. 최종 점검
```

---

## 📌 의존성 확인

구현 전 확인 필요:

```
[ ] ExtractionAgent
    - create_extraction_graph() 함수 존재 확인
    - 반환 형식 확인 (execution_plan, validated_plan 등)

[ ] AnalysisAgent  
    - CodeGenerator 클래스 확인
    - SandboxExecutor 클래스 확인
    - CodeRequest, ExecutionContext 모델 확인

[ ] shared
    - DataContext 클래스 확인
    - load_from_plan() 메서드 확인
    - get_llm_client() 함수 확인
```

---

## 📊 예상 코드량

| 파일 | 예상 라인 |
|------|----------|
| `src/models.py` | ~50줄 |
| `src/config.py` | ~20줄 |
| `src/orchestrator.py` | ~250줄 |
| `src/__init__.py` | ~15줄 |
| `tests/test_orchestrator.py` | ~200줄 |
| **총계** | **~535줄** |

