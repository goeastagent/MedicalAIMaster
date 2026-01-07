# AnalysisAgent 설계 TODO

> 경량 Tool 세트 + 제한된 Code Generation (샌드박스) 아키텍처

---

## 📌 설계 원칙

```
1. DataContext 중심: Agent가 DataContext를 생성하지 않음, 외부에서 주입
2. 경량 Tool: 10-15개의 범용적인 핵심 도구만 제공
3. 안전한 Code Gen: 샌드박스 환경에서만 실행, 제한된 import
4. Interactive 지원: 같은 DataContext로 여러 질의 처리
5. Orchestrator 친화적: 나중에 상위 모듈에서 관리 가능
```

---

## 🏗️ Phase 1: 기반 구조 (Foundation)

### 1.1 프로젝트 구조 생성

- [ ] **디렉토리 구조 생성**
  ```
  AnalysisAgent/
  ├── src/
  │   ├── __init__.py
  │   ├── agents/
  │   │   ├── __init__.py
  │   │   ├── analysis_agent.py      # Main Interface
  │   │   └── core/
  │   │       ├── __init__.py
  │   │       ├── react_agent.py     # ReAct Core
  │   │       ├── context_adapter.py # DataContext ↔ LLM
  │   │       └── decisions.py       # ActionType, AgentDecision
  │   ├── tools/
  │   │   ├── __init__.py
  │   │   ├── registry.py            # ToolRegistry
  │   │   ├── models.py              # ToolInput, ToolOutput
  │   │   └── implementations/       # 실제 도구 구현
  │   ├── code_gen/
  │   │   ├── __init__.py
  │   │   ├── generator.py           # CodeGenerator
  │   │   ├── sandbox.py             # SandboxExecutor
  │   │   ├── validator.py           # CodeValidator
  │   │   └── models.py              # CodeRequest, CodeResult
  │   └── config.py
  ├── tests/
  ├── examples/
  ├── ARCHITECTURE.md
  └── requirements.txt
  ```

- [ ] **requirements.txt 작성**
  - pydantic
  - langgraph (optional)
  - RestrictedPython 또는 Docker SDK
  - 기존 shared 패키지 의존성

### 1.2 핵심 모델 정의

- [ ] **ToolInput 모델** (`src/tools/models.py`)
  ```python
  class ToolInput(BaseModel):
      tool_name: str
      parameters: Dict[str, Any] = {}
      
      def get_parameter(self, name: str, default: Any = None) -> Any
  ```

- [ ] **ToolOutput 모델** (`src/tools/models.py`)
  ```python
  class ToolOutput(BaseModel):
      tool_name: str
      status: Literal["success", "error", "warning"]
      result: Dict[str, Any] = {}
      message: Optional[str] = None
      error_detail: Optional[str] = None
      execution_time: Optional[float] = None
      
      def is_success(self) -> bool
  ```

- [ ] **ActionType 및 AgentDecision** (`src/agents/core/decisions.py`)
  ```python
  class ActionType(str, Enum):
      USE_TOOL = "use_tool"
      GENERATE_CODE = "generate_code"
      FINISH = "finish"
  
  class AgentDecision(BaseModel):
      thought: str
      action_type: ActionType
      tool_name: Optional[str] = None
      tool_parameters: Optional[Dict] = None
      code_request: Optional[CodeRequest] = None
      final_answer: Optional[str] = None
  ```

---

## 🔧 Phase 2: Tool 시스템

### 2.1 Tool Registry

- [ ] **ToolRegistry 구현** (`src/tools/registry.py`)
  ```python
  class ToolRegistry:
      def register(self, spec: ToolSpec) -> None
      def get_tool(self, name: str) -> Optional[ToolSpec]
      def list_tools(self) -> Dict[str, List[str]]
      def get_tools_schema(self) -> List[Dict]  # LLM용
      def get_tools_description(self) -> str     # 프롬프트용
      async def execute(
          self, 
          tool_input: ToolInput, 
          context: DataContext
      ) -> ToolOutput
  ```

- [ ] **ToolSpec 정의**
  ```python
  @dataclass
  class ToolSpec:
      name: str
      description: str
      category: str
      func: Callable
      parameters: Dict[str, Any]  # JSON Schema
      examples: List[Dict] = field(default_factory=list)
  ```

- [ ] **데코레이터 기반 등록 지원**
  ```python
  @registry.tool(
      name="compute_statistics",
      description="...",
      parameters={...}
  )
  def compute_statistics(tool_input: ToolInput, context: DataContext) -> ToolOutput:
      ...
  ```

### 2.2 핵심 Tool 구현 (10-15개)

#### Category: Data Access
- [ ] **get_data_summary** - 현재 데이터 요약 (케이스 수, 파라미터 목록 등)
- [ ] **get_sample_data** - 샘플 데이터 조회 (LLM 컨텍스트용)
- [ ] **get_available_parameters** - 사용 가능한 파라미터 목록

#### Category: Statistics
- [ ] **compute_statistics** - 기술통계 (mean, std, percentiles, min, max 통합)
  ```python
  parameters:
    param_keys: List[str]          # 분석할 파라미터
    metrics: List[str]             # ["mean", "std", "percentile", ...]
    percentiles: List[float]       # [0.25, 0.5, 0.75]
    group_by: Optional[str]        # 그룹화 컬럼
  ```

- [ ] **compute_correlation** - 상관분석
  ```python
  parameters:
    param_x: str
    param_y: str
    method: str  # "pearson", "spearman"
  ```

- [ ] **compare_groups** - 그룹 간 비교 (t-test, ANOVA)
  ```python
  parameters:
    param_key: str
    group_column: str
    test_method: str  # "ttest", "anova", "mannwhitney"
  ```

#### Category: Aggregation
- [ ] **aggregate_data** - 범용 집계
  ```python
  parameters:
    param_keys: List[str]
    group_by: str           # "time", "case", "column_name"
    time_window: str        # "1min", "5min", "1hour" (group_by="time"일 때)
    agg_func: str           # "mean", "sum", "count", "first", "last"
  ```

#### Category: Signal Analysis
- [ ] **detect_events** - 이벤트/피크 탐지
  ```python
  parameters:
    param_key: str
    event_type: str         # "peak", "valley", "threshold_crossing"
    threshold: Optional[float]
    min_duration: Optional[float]  # 초
  ```

- [ ] **filter_by_condition** - 조건 기반 필터링
  ```python
  parameters:
    conditions: List[Dict]  # [{"column": "HR", "op": ">", "value": 100}]
    logic: str              # "and", "or"
  ```

#### Category: Clinical (Optional)
- [ ] **detect_clinical_event** - 임상 이벤트 탐지
  ```python
  parameters:
    event_type: str  # "hypotension", "tachycardia", "desaturation"
    custom_threshold: Optional[Dict]
  ```

#### Category: Visualization
- [ ] **create_visualization** - 시각화 생성
  ```python
  parameters:
    chart_type: str         # "timeseries", "histogram", "boxplot", "scatter"
    param_keys: List[str]
    group_by: Optional[str]
    options: Dict           # 차트별 옵션
  ```

### 2.3 Tool 테스트

- [ ] 각 Tool별 단위 테스트 작성
- [ ] Mock DataContext를 이용한 테스트
- [ ] Edge case 처리 (빈 데이터, 잘못된 파라미터 등)

---

## 🔐 Phase 3: Code Generation 시스템

### 3.1 Code Generation 모델

- [ ] **CodeRequest 정의** (`src/code_gen/models.py`)
  ```python
  class CodeRequest(BaseModel):
      task_description: str        # 무엇을 하는 코드인지
      expected_output: str         # 기대 출력 형태
      available_variables: Dict[str, str]  # {"df": "signals DataFrame", ...}
      constraints: List[str] = []  # ["pandas만 사용", ...]
      hints: Optional[str] = None  # 구현 힌트
  ```

- [ ] **CodeResult 정의**
  ```python
  class CodeResult(BaseModel):
      success: bool
      generated_code: str
      execution_result: Optional[Any] = None
      error_message: Optional[str] = None
      error_type: Optional[str] = None  # "generation", "validation", "execution"
      execution_time: Optional[float] = None
  ```

### 3.2 Code Validator

- [ ] **CodeValidator 구현** (`src/code_gen/validator.py`)
  ```python
  class CodeValidator:
      FORBIDDEN_PATTERNS = [
          r"import\s+os",
          r"import\s+subprocess",
          r"import\s+sys",
          r"exec\s*\(",
          r"eval\s*\(",
          r"__import__",
          r"open\s*\(",
          r"globals\s*\(",
          r"locals\s*\(",
          ...
      ]
      
      ALLOWED_IMPORTS = [
          "pandas",
          "numpy", 
          "scipy.stats",
          "datetime",
          "math",
      ]
      
      def validate(self, code: str) -> ValidationResult
      def extract_imports(self, code: str) -> List[str]
      def check_forbidden_patterns(self, code: str) -> List[str]
  ```

### 3.3 Sandbox Executor

- [ ] **SandboxExecutor 인터페이스** (`src/code_gen/sandbox.py`)
  ```python
  class SandboxExecutor(ABC):
      @abstractmethod
      async def execute(
          self,
          code: str,
          context_data: Dict[str, Any],
          timeout: int = 30
      ) -> ExecutionResult
  ```

- [ ] **RestrictedPython 기반 구현** (가벼운 샌드박스)
  ```python
  class RestrictedExecutor(SandboxExecutor):
      """RestrictedPython을 사용한 경량 샌드박스"""
      
      async def execute(self, code: str, context_data: Dict, timeout: int = 30):
          # RestrictedPython으로 컴파일
          # 제한된 built-ins만 제공
          # 타임아웃 적용
          ...
  ```

- [ ] **Docker 기반 구현** (완전 격리, 선택적)
  ```python
  class DockerExecutor(SandboxExecutor):
      """Docker 컨테이너를 사용한 완전 격리 샌드박스"""
      
      DOCKER_IMAGE = "analysis-sandbox:latest"
      MEMORY_LIMIT = "512m"
      CPU_LIMIT = 1
      
      async def execute(self, code: str, context_data: Dict, timeout: int = 30):
          # 데이터를 컨테이너로 전달
          # 격리된 환경에서 실행
          # 결과 수집
          ...
  ```

- [ ] **Sandbox Docker 이미지 정의** (선택적)
  ```dockerfile
  # Dockerfile.sandbox
  FROM python:3.9-slim
  
  # 최소한의 패키지만 설치
  RUN pip install pandas numpy scipy
  
  # 비root 사용자로 실행
  RUN useradd -m sandbox
  USER sandbox
  
  WORKDIR /workspace
  ```

### 3.4 Code Generator

- [ ] **CodeGenerator 구현** (`src/code_gen/generator.py`)
  ```python
  class CodeGenerator:
      def __init__(
          self,
          llm_client,
          validator: CodeValidator,
          executor: SandboxExecutor
      ):
          ...
      
      async def generate(self, request: CodeRequest) -> str:
          """코드만 생성 (실행 없이)"""
          ...
      
      async def generate_and_execute(
          self,
          request: CodeRequest,
          context: DataContext
      ) -> CodeResult:
          """코드 생성 → 검증 → 실행"""
          
          # 1. 코드 생성
          code = await self.generate(request)
          
          # 2. 검증
          validation = self.validator.validate(code)
          if not validation.is_valid:
              return CodeResult(
                  success=False,
                  generated_code=code,
                  error_message=validation.error,
                  error_type="validation"
              )
          
          # 3. 컨텍스트 데이터 준비
          context_data = self._prepare_context_data(context)
          
          # 4. 샌드박스 실행
          result = await self.executor.execute(code, context_data)
          
          return CodeResult(
              success=result.success,
              generated_code=code,
              execution_result=result.output,
              error_message=result.error,
              error_type="execution" if not result.success else None
          )
      
      def _prepare_context_data(self, context: DataContext) -> Dict:
          """DataContext에서 샌드박스로 전달할 데이터 추출"""
          return {
              "cohort": context.get_cohort().to_dict(),
              "signals": context.get_signals().to_dict(),
              "case_ids": context.get_case_ids(),
              "param_keys": context.get_available_parameters()
          }
  ```

- [ ] **Code Generation 프롬프트**
  ```python
  CODE_GEN_SYSTEM_PROMPT = """
  You are a Python code generator for medical data analysis.
  
  ## Rules
  1. Only use allowed imports: pandas, numpy, scipy.stats, datetime, math
  2. Do not use: os, subprocess, sys, open(), eval(), exec()
  3. Write clean, efficient code
  4. Use vectorized operations (no loops when possible)
  5. Handle missing values appropriately
  6. Return result in the specified format
  
  ## Available Variables
  - df: pandas DataFrame with signal data
  - cohort: pandas DataFrame with cohort data
  - param_keys: list of available parameter names
  
  ## Output Format
  Assign the final result to a variable named `result`
  """
  ```

### 3.5 Code Gen 테스트

- [ ] Validator 단위 테스트 (금지 패턴 탐지)
- [ ] Sandbox 실행 테스트 (타임아웃, 메모리 제한)
- [ ] 전체 흐름 통합 테스트

---

## 🤖 Phase 4: ReAct Agent Core

### 4.1 Context Adapter

- [ ] **ContextAdapter 구현** (`src/agents/core/context_adapter.py`)
  ```python
  class ContextAdapter:
      def __init__(self, context: DataContext):
          self._context = context
      
      def get_data_overview(self) -> Dict[str, Any]:
          """LLM에게 제공할 데이터 개요"""
          ...
      
      def get_llm_context_prompt(self) -> str:
          """LLM 프롬프트용 컨텍스트 문자열"""
          ...
      
      def get_sample_for_llm(self, n_cases: int = 2) -> Dict:
          """LLM에게 보여줄 샘플 데이터"""
          ...
  ```

### 4.2 ReAct Agent

- [ ] **ReActAgent 구현** (`src/agents/core/react_agent.py`)
  ```python
  class ReActAgent:
      def __init__(
          self,
          context: DataContext,
          tool_registry: ToolRegistry,
          code_generator: Optional[CodeGenerator] = None,
          max_steps: int = 10,
          verbose: bool = True
      ):
          ...
      
      async def run(self, query: str) -> Dict[str, Any]:
          """ReAct 루프 실행"""
          ...
      
      async def _decide(self, query: str, step_num: int) -> AgentDecision:
          """LLM이 다음 행동 결정"""
          ...
      
      async def _execute_tool(self, name: str, params: Dict) -> ToolOutput:
          """Tool 실행"""
          ...
      
      async def _execute_code_gen(self, request: CodeRequest) -> CodeResult:
          """Code Generation 실행"""
          ...
      
      def _compile_result(self, query: str) -> Dict[str, Any]:
          """최종 결과 조립"""
          ...
  ```

- [ ] **Decision Prompt 설계**
  ```
  ## 판단 기준
  
  ### USE_TOOL 선택 기준
  - 기술통계 (평균, 표준편차 등) → compute_statistics
  - 상관분석 → compute_correlation
  - 그룹 비교 → compare_groups
  - 이벤트 탐지 → detect_events
  - 데이터 집계 → aggregate_data
  
  ### GENERATE_CODE 선택 기준
  - 복합 조건 필터링 (AND/OR 조합)
  - 커스텀 계산 (비율, 누적값 등)
  - 기존 도구로 표현 불가능한 로직
  - 데이터 형태 변환
  
  ### FINISH 선택 기준
  - 질문에 대한 충분한 정보가 수집됨
  - 더 이상 분석이 필요 없음
  ```

### 4.3 실행 이력 관리

- [ ] **실행 이력 기록**
  ```python
  @dataclass
  class ExecutionStep:
      step_num: int
      thought: str
      action_type: ActionType
      action_detail: Dict[str, Any]
      observation: Dict[str, Any]
      timestamp: datetime
  ```

- [ ] **세션 관리**
  ```python
  @dataclass
  class AnalysisSession:
      session_id: str
      created_at: datetime
      query_count: int
      history: List[Dict[str, Any]]
  ```

---

## 🎯 Phase 5: AnalysisAgent (Main Interface)

### 5.1 Main Agent 구현

- [ ] **AnalysisAgent 구현** (`src/agents/analysis_agent.py`)
  ```python
  class AnalysisAgent:
      def __init__(
          self,
          data_context: Optional[DataContext] = None,
          config: Optional[AnalysisConfig] = None
      ):
          ...
      
      # Context Management
      def set_context(self, data_context: DataContext) -> "AnalysisAgent"
      def has_context(self) -> bool
      def get_context_summary(self) -> Dict[str, Any]
      
      # Analysis
      async def analyze(self, query: str) -> AnalysisResult
      def analyze_sync(self, query: str) -> AnalysisResult
      
      # Session
      def get_session_info(self) -> Dict[str, Any]
      def get_query_history(self, limit: int = 10) -> List[Dict]
      def clear_session(self) -> None
      
      # Tools
      def get_available_tools(self) -> Dict[str, List[str]]
  ```

- [ ] **AnalysisConfig 정의**
  ```python
  @dataclass
  class AnalysisConfig:
      max_steps: int = 10
      verbose: bool = True
      enable_code_gen: bool = True
      code_gen_timeout: int = 30
      sandbox_type: str = "restricted"  # "restricted" or "docker"
  ```

- [ ] **AnalysisResult 정의**
  ```python
  class AnalysisResult(BaseModel):
      query: str
      answer: str
      reasoning_steps: List[Dict]
      data: Dict[str, Any]
      visualizations: List[Dict]
      used_code_generation: bool
      metadata: Dict[str, Any]
  ```

### 5.2 에러 처리

- [ ] **Custom Exception 정의**
  ```python
  class AnalysisAgentError(Exception): ...
  class NoContextError(AnalysisAgentError): ...
  class ToolExecutionError(AnalysisAgentError): ...
  class CodeGenerationError(AnalysisAgentError): ...
  class SandboxError(AnalysisAgentError): ...
  ```

- [ ] **Graceful Degradation**
  - Code Gen 실패 시 → 대안 제시 또는 Tool로 부분 해결
  - Tool 실패 시 → 에러 메시지와 함께 다른 방법 시도

---

## 📚 Phase 6: 문서화 및 테스트

### 6.1 문서화

- [ ] **ARCHITECTURE.md** - 전체 아키텍처 설명
- [ ] **Tool 목록 및 사용법**
- [ ] **Code Generation 가이드라인**
- [ ] **보안 고려사항**

### 6.2 테스트

- [ ] **단위 테스트**
  - 각 Tool 테스트
  - CodeValidator 테스트
  - SandboxExecutor 테스트

- [ ] **통합 테스트**
  - ReActAgent 전체 흐름 테스트
  - Tool + Code Gen 혼합 시나리오 테스트

- [ ] **E2E 테스트**
  - 실제 DataContext와 연동 테스트
  - 다양한 쿼리 시나리오 테스트

### 6.3 Examples

- [ ] **basic_usage.py** - 기본 사용 예시
- [ ] **interactive_mode.py** - 대화형 분석 예시
- [ ] **with_code_gen.py** - Code Gen 사용 예시

---

## 🔗 Phase 7: 통합 (Integration)

### 7.1 shared 패키지 연동

- [ ] DataContext import 및 사용
- [ ] LLM Client 공유
- [ ] Config 통합

### 7.2 Orchestrator 준비 (Future)

- [ ] AnalysisAgent 인터페이스 확정
- [ ] ExtractionAgent와의 데이터 흐름 정의
- [ ] 세션/상태 관리 방안

---

## 📅 구현 우선순위

### 🔴 High Priority (Week 1-2)
1. Phase 1: 기반 구조
2. Phase 2.1-2.2: Tool Registry + 핵심 Tool 5개
3. Phase 4.1-4.2: Context Adapter + ReAct Agent (Tool만)

### 🟡 Medium Priority (Week 3-4)
4. Phase 2.2: 나머지 Tool 구현
5. Phase 3: Code Generation 시스템 전체
6. Phase 5: AnalysisAgent Main Interface

### 🟢 Low Priority (Week 5+)
7. Phase 6: 문서화 및 테스트
8. Phase 7: 통합
9. 최적화 및 개선

---

## ✅ 완료 체크리스트

### Foundation
- [ ] 디렉토리 구조 생성
- [ ] requirements.txt 작성
- [ ] 핵심 모델 (ToolInput, ToolOutput, ActionType) 정의

### Tool System
- [ ] ToolRegistry 구현
- [ ] 핵심 Tool 10개 이상 구현
- [ ] Tool 테스트 완료

### Code Generation
- [ ] CodeValidator 구현
- [ ] SandboxExecutor (RestrictedPython) 구현
- [ ] CodeGenerator 구현
- [ ] Code Gen 테스트 완료

### Agent
- [ ] ContextAdapter 구현
- [ ] ReActAgent 구현
- [ ] AnalysisAgent 구현
- [ ] 전체 흐름 테스트 완료

### Documentation
- [ ] ARCHITECTURE.md 작성
- [ ] 사용 예시 작성
- [ ] 테스트 커버리지 확보

---

## 📝 Notes

### 보안 고려사항
- 의료 데이터 환경이므로 Code Gen은 반드시 샌드박스에서만 실행
- 생성된 모든 코드 로깅 (감사 추적)
- 타임아웃 및 리소스 제한 필수

### 확장 가능성
- 새로운 Tool 추가 용이한 구조
- 샌드박스 구현체 교체 가능 (RestrictedPython ↔ Docker)
- Orchestrator 연동 준비

### 성능 고려사항
- Tool 실행은 DataContext 캐시 활용
- Code Gen은 비용이 크므로 필요시에만 사용
- LLM 호출 최소화 (적절한 프롬프트 설계)

