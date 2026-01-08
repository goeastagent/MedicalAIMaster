# AnalysisAgent 재설계 TODO

> 최종 수정일: 2025-01-08
> 상태: 설계 완료, 구현 대기

---

## 📋 설계 개요

### 목표
- **범용적 분석 에이전트**: 하드코딩 없이 어떤 분석 쿼리든 대응
- **계획-실행 분리**: LLM 기반 계획 수립 → 단계별 실행
- **Tool 우선 사용**: 등록된 Tool 있으면 활용, 없으면 CodeGen
- **결과 관리**: 캐싱, 이력 관리, 이전 결과 참조

### 전체 아키텍처
```
Orchestrator
    │
    ├── ExtractionAgent → Execution Plan
    ├── DataContext → 데이터 로드
    └── AnalysisAgent
            ├── Phase 1: Context Building
            ├── Phase 2: Planning (LLM)
            ├── Phase 3: Execution (Tool/CodeGen)
            └── Phase 4: Result Assembly
```

---

## 🗂️ 디렉토리 구조

```
AnalysisAgent/
├── src/
│   ├── __init__.py
│   ├── agent.py                    # [NEW] 메인 클래스
│   │
│   ├── context/                    # [NEW] Phase 1
│   │   ├── __init__.py
│   │   ├── builder.py              # ContextBuilder
│   │   └── schema.py               # ColumnInfo, DataFrameSchema, AnalysisContext
│   │
│   ├── planner/                    # [NEW] Phase 2
│   │   ├── __init__.py
│   │   ├── planner.py              # AnalysisPlanner
│   │   ├── prompts.py              # PLANNING_PROMPT
│   │   └── models.py               # PlanStep, AnalysisPlan
│   │
│   ├── executor/                   # [NEW] Phase 3
│   │   ├── __init__.py
│   │   ├── executor.py             # StepExecutor
│   │   ├── router.py               # ExecutionRouter
│   │   └── code_gen/               # [EXISTING - 리팩토링]
│   │       ├── __init__.py
│   │       ├── generator.py
│   │       ├── sandbox.py
│   │       ├── validator.py
│   │       └── prompts.py
│   │
│   ├── tools/                      # [NEW] Tool 시스템
│   │   ├── __init__.py
│   │   ├── registry.py             # ToolRegistry
│   │   ├── base.py                 # BaseTool
│   │   └── builtin/                # 향후 내장 Tool
│   │       └── __init__.py
│   │
│   ├── results/                    # [NEW] Phase 4
│   │   ├── __init__.py
│   │   ├── store.py                # ResultStore
│   │   └── models.py               # AnalysisResult
│   │
│   └── models/                     # [REFACTOR] 공통 모델
│       ├── __init__.py
│       ├── io.py                   # StepInput, StepOutput
│       ├── context.py              # [EXISTING] ExecutionContext
│       └── code_gen.py             # [EXISTING] CodeRequest, GenerationResult
│
├── config.py                       # [UPDATE] 설정 추가
├── DESIGN_TODO.md                  # 이 파일
└── requirements.txt
```

---

## ✅ 구현 TODO

### Phase 0: 준비 작업
- [x] **P0-1**: 기존 코드 분석 및 재사용 가능 부분 식별 ✅
  - `code_gen/generator.py` - 코드 생성 로직
  - `code_gen/sandbox.py` - 코드 실행 로직
  - `code_gen/validator.py` - 코드 검증 로직
  - `models/context.py` - ExecutionContext
  - `models/code_gen.py` - CodeRequest, GenerationResult

- [x] **P0-2**: 디렉토리 구조 생성 ✅
  - `facade.py` 제거 (AnalysisAgent로 대체)
  - `CODEGEN_TODO.md` 제거 (DESIGN_TODO.md로 대체)
  - `example_facades.py` 업데이트

---

### Phase 1: Context Building (컨텍스트 구성) ✅ 완료

- [x] **P1-1**: `context/schema.py` - 스키마 모델 정의 ✅
  ```python
  class ColumnInfo(BaseModel):
      name: str
      dtype: str  # "numeric", "categorical", "datetime"
      nullable: bool
      sample_values: List[Any]
      statistics: Optional[Dict[str, float]]  # numeric만
      unique_values: Optional[List[Any]]  # categorical만
  
  class DataFrameSchema(BaseModel):
      name: str
      shape: tuple
      columns: List[ColumnInfo]
      sample_rows: List[Dict[str, Any]]
  
  class AnalysisContext(BaseModel):
      data_schemas: Dict[str, DataFrameSchema]
      join_keys: List[str]
      available_tools: List[Dict[str, Any]]
      constraints: List[str]
      previous_results: Optional[List[Dict]]
  ```

- [x] **P1-2**: `context/builder.py` - ContextBuilder 구현 ✅
  - DataContext → AnalysisContext 변환
  - DataFrame 스키마 추출
  - 컬럼 타입 추론
  - 통계 정보 수집

---

### Phase 2: Planning (계획 수립) ✅ 완료

- [x] **P2-1**: `planner/models.py` - 계획 모델 정의 ✅
  ```python
  class PlanStep(BaseModel):
      id: str
      action: str
      description: str
      tool_name: Optional[str]
      inputs: List[str]
      output_key: str
      expected_output_type: str
      code_hint: Optional[str]
  
  class AnalysisPlan(BaseModel):
      query: str
      analysis_type: str
      steps: List[PlanStep]
      expected_output: Dict[str, Any]
      execution_mode: Literal["tool_only", "code_only", "hybrid"]
      estimated_complexity: Literal["simple", "moderate", "complex"]
      confidence: float
  ```

- [x] **P2-2**: `planner/prompts.py` - 계획 생성 프롬프트 ✅
  - 데이터 스키마 포맷팅
  - Tool 목록 포맷팅
  - 제약사항 포맷팅
  - JSON 출력 형식 정의
  - Few-shot 예제

- [x] **P2-3**: `planner/planner.py` - AnalysisPlanner 구현 ✅
  - LLM 호출 → AnalysisPlan 생성
  - 응답 파싱 및 검증
  - 에러 핸들링
  - 규칙 기반 단순 계획 (`plan_simple`)

---

### Phase 3: Execution (실행) ✅ 완료

- [x] **P3-1**: `models/io.py` - I/O 모델 정의 ✅
  ```python
  class StepInput(BaseModel):
      data: Dict[str, Any]
      parameters: Dict[str, Any] = {}
      context: Optional[Dict[str, Any]] = None
  
  class StepOutput(BaseModel):
      result: Any
      result_type: str
      meta: Dict[str, Any] = {}
      status: Literal["success", "error", "warning"]
      message: Optional[str]
      step_id: Optional[str]
      execution_time_ms: Optional[float]
  
  class ExecutionState(BaseModel):  # 추가
      data: Dict[str, Any]
      step_outputs: List[StepOutput]
  ```

- [x] **P3-2**: `tools/base.py` - Tool 기본 클래스 ✅
  ```python
  class BaseTool:
      name: str
      description: str
      input_schema: Dict[str, Any]
      output_schema: Dict[str, Any]
      
      def execute(self, step_input: StepInput) -> StepOutput:
          raise NotImplementedError
  ```

- [x] **P3-3**: `tools/registry.py` - ToolRegistry 구현 ✅
  - Tool 등록/조회
  - Tool 스키마 목록 제공 (Planner용)
  - 글로벌 레지스트리 지원

- [x] **P3-4**: `executor/router.py` - ExecutionRouter 구현 ✅
  - Tool 존재 여부 확인
  - Tool vs CodeGen 결정 로직

- [x] **P3-5**: `executor/executor.py` - StepExecutor 구현 ✅
  - 계획 단계별 실행
  - 중간 결과 관리
  - 에러 핸들링 및 복구

- [x] **P3-6**: CodeGen 통합 ✅
  - CodeGenerator: StepInput/StepOutput 호환
  - code_hint 활용
  - Lazy initialization

---

### Phase 4: Result Assembly (결과 관리) ✅ 완료

- [x] **P4-1**: `results/models.py` - 결과 모델 정의 ✅
  ```python
  class AnalysisResult(BaseModel):
      id: str
      query_hash: str
      query: str
      input_context_summary: Dict[str, Any]
      plan: Dict[str, Any]
      step_results: List[Dict[str, Any]]
      final_result: Any
      output_schema: Dict[str, Any]
      generated_code: Optional[str]
      status: str
      execution_time_ms: float
      created_at: datetime
      parent_id: Optional[str]
  ```

- [x] **P4-2**: `results/store.py` - ResultStore 구현 ✅
  - In-memory 저장 (LRU eviction)
  - 캐시 조회 (query_hash 기반)
  - 이력 조회 (최근 N개)
  - TTL 기반 만료
  - 향후: SQLite/PostgreSQL 백엔드

---

### Phase 5: Integration (통합) ✅ 완료

- [x] **P5-1**: `agent.py` - AnalysisAgent 메인 클래스 ✅
  - 컴포넌트 조립 (ContextBuilder, Planner, Executor, ResultStore)
  - `analyze()` / `analyze_dataframes()` 메서드 구현
  - 캐시 활용 로직

- [x] **P5-2**: `__init__.py` - 모듈 export 정리 ✅
  - AnalysisAgent, AnalysisAgentConfig export

- [x] **P5-3**: Orchestrator 연동 ✅
  - 기존 Orchestrator 동작 유지
  - AnalysisAgent 독립 사용 가능

- [x] **P5-4**: `config.py` - AnalysisAgentConfig 추가 ✅
  - use_llm_planning, use_cache, code_gen_max_retries 등

---

### Phase 6: Testing & Documentation

- [ ] **P6-1**: 단위 테스트
  - `test_context_builder.py`
  - `test_planner.py`
  - `test_executor.py`
  - `test_result_store.py`

- [ ] **P6-2**: 통합 테스트
  - `test_analysis_agent.py`
  - `test_orchestrator_integration.py`

- [ ] **P6-3**: 예제 코드
  - `examples/example_analysis.py`
  - `examples/example_with_tools.py`

- [ ] **P6-4**: 문서화
  - `ARCHITECTURE.md` 업데이트
  - 각 모듈 docstring

---

## 📊 의존성 관계

```
┌─────────────────────────────────────────────────────────────────┐
│                         agent.py                                 │
│                      AnalysisAgent                               │
└─────────────────────────────────────────────────────────────────┘
          │              │              │              │
          ▼              ▼              ▼              ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ context/ │  │ planner/ │  │ executor/│  │ results/ │
    │ builder  │  │ planner  │  │ executor │  │  store   │
    └──────────┘  └──────────┘  └──────────┘  └──────────┘
          │              │              │
          ▼              │              ▼
    ┌──────────┐         │        ┌──────────┐
    │ context/ │         │        │  tools/  │
    │  schema  │         │        │ registry │
    └──────────┘         │        └──────────┘
                         │              │
                         ▼              ▼
                   ┌──────────┐  ┌──────────┐
                   │ planner/ │  │  tools/  │
                   │  models  │  │   base   │
                   └──────────┘  └──────────┘
                         │              │
                         └──────┬───────┘
                                ▼
                          ┌──────────┐
                          │ models/  │
                          │   io     │
                          └──────────┘
```

---

## 🚀 구현 우선순위

### 1차 (MVP - 핵심 기능)
1. **P1-1, P1-2**: Context Building
2. **P2-1, P2-2, P2-3**: Planning
3. **P3-1**: I/O 모델
4. **P3-5, P3-6**: Executor + CodeGen 연동
5. **P5-1**: AnalysisAgent 기본 동작

### 2차 (Tool 시스템)
1. **P3-2, P3-3, P3-4**: Tool Registry & Router
2. **P5-3**: Orchestrator 연동

### 3차 (결과 관리)
1. **P4-1, P4-2**: ResultStore
2. **P5-4**: 설정

### 4차 (품질)
1. **P6-1, P6-2**: 테스트
2. **P6-3, P6-4**: 예제 및 문서

---

## 📝 기존 코드 재사용 계획

| 기존 파일 | 상태 | 변경 사항 |
|----------|------|----------|
| `code_gen/generator.py` | 리팩토링 | StepInput/Output 호환, code_hint 활용 |
| `code_gen/sandbox.py` | 유지 | 변경 없음 (이미 잘 동작) |
| `code_gen/validator.py` | 유지 | 변경 없음 |
| `code_gen/prompts.py` | 업데이트 | 제약사항 프롬프트 개선 |
| `models/context.py` | 유지 | ExecutionContext 유지 (CodeGen용) |
| `models/code_gen.py` | 유지 | CodeRequest, GenerationResult 유지 |
| `facade.py` | Deprecated | AnalysisAgent로 대체 |
| `config.py` | 업데이트 | AnalysisAgentConfig 추가 |

---

## ⚠️ 주의사항

1. **하드코딩 금지**: 분석 유형, 힌트 등을 하드코딩하지 않음
2. **LLM 의존도**: Planner가 LLM에 의존 → 프롬프트 품질이 중요
3. **Tool 없이도 동작**: 현재 Tool 없음 → CodeGen으로 모든 분석 가능해야 함
4. **기존 테스트 유지**: 기존 `example_end_to_end.py` 테스트 통과해야 함

---

## 📅 예상 일정

| Phase | 작업량 | 예상 소요 |
|-------|-------|----------|
| Phase 0 | 준비 | 1시간 |
| Phase 1 | Context | 2시간 |
| Phase 2 | Planning | 3시간 |
| Phase 3 | Execution | 4시간 |
| Phase 4 | Results | 2시간 |
| Phase 5 | Integration | 3시간 |
| Phase 6 | Testing | 3시간 |
| **Total** | | **~18시간** |

---

## 🔗 관련 문서

- `OrchestrationAgent/ARCHITECTURE.md` - Orchestrator 설계
- `ExtractionAgent/ARCHITECTURE.md` - ExtractionAgent 설계
- `shared/data/context.py` - DataContext 구현
- `technical_spec.md` - 전체 기술 스펙
