# Code Generation 구현 TODO

> 경량 샌드박스 기반 코드 생성 시스템

---

## 📌 설계 원칙

```
1. 책임 분리: Generator(생성) / Validator(검증) / Executor(실행) / Agent(조율)
2. Agent 제어: 실행 시점, 데이터 주입, 재시도 여부는 Agent가 결정
3. 안전 우선: 샌드박스 실행, 금지 패턴 검증, 타임아웃 필수
4. DataContext 연동: Agent만 DataContext 접근, 다른 컴포넌트는 runtime_data만 받음
```

---

## 📁 파일 구조

```
AnalysisAgent/
├── src/
│   ├── __init__.py
│   │
│   ├── models/                      # 📌 공통 모델
│   │   ├── __init__.py
│   │   ├── context.py               # ExecutionContext (Code Gen & Tool 공유)
│   │   └── code_gen.py              # CodeRequest, GenerationResult, 
│   │                                # ExecutionResult, CodeResult
│   │
│   ├── code_gen/                    # 📌 Code Generation 시스템
│   │   ├── __init__.py
│   │   ├── validator.py             # CodeValidator (검증만)
│   │   ├── sandbox.py               # SandboxExecutor (실행만)
│   │   ├── generator.py             # CodeGenerator (생성만)
│   │   └── prompts.py               # 프롬프트 템플릿
│   │
│   └── config.py                    # 설정
│
├── tests/
│   ├── __init__.py
│   ├── test_validator.py
│   ├── test_sandbox.py
│   ├── test_generator.py
│   └── test_integration.py          # 통합 테스트
│
├── requirements.txt
└── README.md
```

---

## 📋 Phase 1: 모델 정의

### 1.1 `src/models/context.py`

```python
"""실행 컨텍스트 - Code Gen과 Tool이 공유"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field


class ExecutionContext(BaseModel):
    """코드 생성 시 LLM에게 제공하는 컨텍스트"""
    
    available_variables: Dict[str, str]
    # 사용 가능한 변수와 설명
    # {
    #   "df": "pandas DataFrame - Signal 데이터, columns: [Time, HR, SpO2, ...]",
    #   "cohort": "pandas DataFrame - Cohort 데이터, columns: [caseid, age, sex, ...]",
    #   "case_ids": "List[str] - 분석 가능한 케이스 ID 목록",
    #   "param_keys": "List[str] - 사용 가능한 파라미터 키 목록"
    # }
    
    available_imports: List[str] = Field(default_factory=lambda: [
        "pandas as pd",
        "numpy as np",
        "scipy.stats",
        "datetime",
        "math",
    ])
    # 허용된 import 목록
    
    sample_data: Optional[Dict[str, Any]] = None
    # LLM에게 보여줄 샘플 데이터 (선택적)
    # {
    #   "df_columns": ["Time", "HR", "SpO2"],
    #   "df_shape": [10000, 5],
    #   "cohort_head": [{"caseid": 1, "age": 45, "sex": "M"}, ...]
    # }


class DataSummary(BaseModel):
    """데이터 요약 (Code Gen & Tool 공통)"""
    
    case_count: int
    param_keys: List[str]
    cohort_columns: List[str]
    signal_columns: List[str] = []
    signal_shape: Optional[tuple] = None
```

**TODO:**
- [ ] `ExecutionContext` 클래스 구현
- [ ] `DataSummary` 클래스 구현
- [ ] `__init__.py`에서 export

---

### 1.2 `src/models/code_gen.py`

```python
"""Code Generation 전용 모델"""

from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel, Field
from .context import ExecutionContext


class CodeRequest(BaseModel):
    """코드 생성 요청 (Agent → Generator)"""
    
    task_description: str
    # 무엇을 하는 코드인지
    # "심박수가 100 이상인 구간의 비율 계산"
    
    expected_output: str
    # 기대하는 출력 형태
    # "0.0 ~ 1.0 사이의 float (비율)"
    
    execution_context: ExecutionContext
    # 실행 컨텍스트 (사용 가능한 변수, import 등)
    
    hints: Optional[str] = None
    # 구현 힌트 (선택)
    # "df['HR'] > 100 조건 사용"
    
    constraints: Optional[List[str]] = None
    # 추가 제약사항
    # ["루프 대신 벡터 연산 사용", "NaN 처리 필수"]


class ValidationResult(BaseModel):
    """검증 결과 (Validator → Generator/Agent)"""
    
    is_valid: bool
    errors: List[str] = []           # 치명적 에러 (금지 패턴 등)
    warnings: List[str] = []         # 경고 (비효율적 코드 등)


class GenerationResult(BaseModel):
    """생성 결과 (Generator → Agent)"""
    
    code: str                        # 생성된 코드
    is_valid: bool                   # 검증 통과 여부
    validation_errors: List[str] = []
    validation_warnings: List[str] = []


class ExecutionResult(BaseModel):
    """실행 결과 (Executor → Agent)"""
    
    success: bool
    result: Optional[Any] = None     # result 변수의 값
    error: Optional[str] = None      # 에러 메시지
    error_type: Optional[str] = None # "timeout", "runtime", "memory"
    execution_time_ms: Optional[float] = None
    stdout: Optional[str] = None     # print 출력 (선택적)


class CodeResult(BaseModel):
    """최종 결과 (Agent가 조합해서 반환)"""
    
    success: bool
    
    # 생성된 코드
    generated_code: str
    
    # 실행 결과 (성공 시)
    execution_result: Optional[Any] = None
    
    # 에러 정보 (실패 시)
    error_type: Optional[Literal["generation", "validation", "execution"]] = None
    error_message: Optional[str] = None
    
    # 메타데이터
    execution_time_ms: Optional[float] = None
    retry_count: int = 0
```

**TODO:**
- [ ] `CodeRequest` 클래스 구현
- [ ] `ValidationResult` 클래스 구현
- [ ] `GenerationResult` 클래스 구현
- [ ] `ExecutionResult` 클래스 구현
- [ ] `CodeResult` 클래스 구현
- [ ] `__init__.py`에서 export

---

### 1.3 `src/models/__init__.py`

```python
"""AnalysisAgent Models"""

from .context import ExecutionContext, DataSummary
from .code_gen import (
    CodeRequest,
    ValidationResult,
    GenerationResult,
    ExecutionResult,
    CodeResult,
)

__all__ = [
    # Context
    "ExecutionContext",
    "DataSummary",
    # Code Gen
    "CodeRequest",
    "ValidationResult", 
    "GenerationResult",
    "ExecutionResult",
    "CodeResult",
]
```

**TODO:**
- [ ] `__init__.py` 작성

---

## 📋 Phase 2: Code Validator

### 2.1 `src/code_gen/validator.py`

```python
"""코드 검증기 - 보안 검사만 담당"""

import re
import ast
from typing import List, Tuple
from ..models import ValidationResult


class CodeValidator:
    """생성된 코드의 보안 검증"""
    
    # 금지 패턴 (정규식)
    FORBIDDEN_PATTERNS: List[Tuple[str, str]] = [
        # (패턴, 설명)
        (r"import\s+os", "os module import"),
        (r"import\s+subprocess", "subprocess module import"),
        (r"import\s+sys", "sys module import"),
        (r"from\s+os\s+import", "os module import"),
        (r"from\s+subprocess\s+import", "subprocess module import"),
        (r"__import__\s*\(", "__import__ function"),
        (r"exec\s*\(", "exec function"),
        (r"eval\s*\(", "eval function"),
        (r"compile\s*\(", "compile function"),
        (r"globals\s*\(", "globals function"),
        (r"locals\s*\(", "locals function"),
        (r"open\s*\(", "open function"),
        (r"file\s*\(", "file function"),
        (r"input\s*\(", "input function"),
        (r"breakpoint\s*\(", "breakpoint function"),
        (r"\.read\s*\(", "file read"),
        (r"\.write\s*\(", "file write"),
        (r"getattr\s*\(", "getattr function"),
        (r"setattr\s*\(", "setattr function"),
        (r"delattr\s*\(", "delattr function"),
    ]
    
    # 금지 모듈
    FORBIDDEN_MODULES: List[str] = [
        "os", "subprocess", "sys", "shutil", "pathlib",
        "pickle", "shelve", "socket", "requests", "urllib",
        "http", "ftplib", "smtplib", "telnetlib",
        "ctypes", "multiprocessing", "threading",
    ]
    
    # 허용 모듈
    ALLOWED_MODULES: List[str] = [
        "pandas", "numpy", "scipy", "scipy.stats",
        "datetime", "math", "statistics",
        "collections", "itertools", "functools",
        "re", "json",
    ]
    
    def validate(self, code: str) -> ValidationResult:
        """
        코드 검증
        
        Args:
            code: 검증할 Python 코드
        
        Returns:
            ValidationResult with is_valid, errors, warnings
        """
        errors = []
        warnings = []
        
        # 1. 구문 검사
        syntax_error = self._check_syntax(code)
        if syntax_error:
            errors.append(f"Syntax error: {syntax_error}")
            return ValidationResult(is_valid=False, errors=errors)
        
        # 2. 금지 패턴 검사
        pattern_errors = self._check_forbidden_patterns(code)
        errors.extend(pattern_errors)
        
        # 3. Import 검사
        import_errors, import_warnings = self._check_imports(code)
        errors.extend(import_errors)
        warnings.extend(import_warnings)
        
        # 4. result 변수 존재 확인
        if not self._has_result_variable(code):
            warnings.append("No 'result' variable assignment found")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    def _check_syntax(self, code: str) -> Optional[str]:
        """구문 검사"""
        try:
            ast.parse(code)
            return None
        except SyntaxError as e:
            return f"Line {e.lineno}: {e.msg}"
    
    def _check_forbidden_patterns(self, code: str) -> List[str]:
        """금지 패턴 검사"""
        errors = []
        for pattern, description in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                errors.append(f"Forbidden pattern detected: {description}")
        return errors
    
    def _check_imports(self, code: str) -> Tuple[List[str], List[str]]:
        """Import 검사"""
        errors = []
        warnings = []
        
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name.split('.')[0]
                        if module in self.FORBIDDEN_MODULES:
                            errors.append(f"Forbidden module: {module}")
                        elif module not in self.ALLOWED_MODULES:
                            warnings.append(f"Unknown module: {module}")
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module = node.module.split('.')[0]
                        if module in self.FORBIDDEN_MODULES:
                            errors.append(f"Forbidden module: {module}")
                        elif module not in self.ALLOWED_MODULES:
                            warnings.append(f"Unknown module: {module}")
        except:
            pass  # 구문 에러는 이미 체크됨
        
        return errors, warnings
    
    def _has_result_variable(self, code: str) -> bool:
        """result 변수 할당 확인"""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == 'result':
                            return True
        except:
            pass
        return False
```

**TODO:**
- [ ] `CodeValidator` 클래스 구현
- [ ] `FORBIDDEN_PATTERNS` 정의
- [ ] `FORBIDDEN_MODULES` 정의
- [ ] `ALLOWED_MODULES` 정의
- [ ] `validate()` 메서드 구현
- [ ] `_check_syntax()` 메서드 구현
- [ ] `_check_forbidden_patterns()` 메서드 구현
- [ ] `_check_imports()` 메서드 구현
- [ ] `_has_result_variable()` 메서드 구현

---

## 📋 Phase 3: Sandbox Executor

### 3.1 `src/code_gen/sandbox.py`

```python
"""샌드박스 실행기 - 안전한 코드 실행만 담당"""

import signal
import traceback
from typing import Dict, Any, Optional
from contextlib import contextmanager
from ..models import ExecutionResult

# RestrictedPython 사용 (권장)
try:
    from RestrictedPython import compile_restricted, safe_globals
    from RestrictedPython.Eval import default_guarded_getiter
    from RestrictedPython.Guards import guarded_iter_unpack_sequence
    HAS_RESTRICTED_PYTHON = True
except ImportError:
    HAS_RESTRICTED_PYTHON = False


class TimeoutError(Exception):
    """실행 시간 초과"""
    pass


class SandboxExecutor:
    """안전한 코드 실행 환경"""
    
    def __init__(
        self,
        timeout_seconds: int = 30,
        max_output_size: int = 10000  # 결과 크기 제한
    ):
        self.timeout_seconds = timeout_seconds
        self.max_output_size = max_output_size
    
    def execute(
        self,
        code: str,
        runtime_data: Dict[str, Any]
    ) -> ExecutionResult:
        """
        코드 실행
        
        Args:
            code: 실행할 Python 코드 (이미 검증됨)
            runtime_data: 실행 시 사용할 변수들
                {
                    "df": pandas.DataFrame,
                    "cohort": pandas.DataFrame,
                    "case_ids": List[str],
                    "param_keys": List[str]
                }
        
        Returns:
            ExecutionResult
        """
        import time
        start_time = time.time()
        
        try:
            # 실행 환경 구성
            exec_globals = self._create_exec_globals(runtime_data)
            
            # 타임아웃 설정
            with self._timeout(self.timeout_seconds):
                if HAS_RESTRICTED_PYTHON:
                    result = self._execute_restricted(code, exec_globals)
                else:
                    result = self._execute_simple(code, exec_globals)
            
            execution_time = (time.time() - start_time) * 1000
            
            return ExecutionResult(
                success=True,
                result=result,
                execution_time_ms=execution_time
            )
        
        except TimeoutError:
            return ExecutionResult(
                success=False,
                error="Execution timeout",
                error_type="timeout",
                execution_time_ms=self.timeout_seconds * 1000
            )
        
        except MemoryError:
            return ExecutionResult(
                success=False,
                error="Memory limit exceeded",
                error_type="memory"
            )
        
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            return ExecutionResult(
                success=False,
                error=str(e),
                error_type="runtime",
                execution_time_ms=execution_time
            )
    
    def _create_exec_globals(self, runtime_data: Dict[str, Any]) -> Dict[str, Any]:
        """실행 환경의 globals 구성"""
        import pandas as pd
        import numpy as np
        import math
        import datetime
        from scipy import stats
        
        # 기본 안전한 builtins
        safe_builtins = {
            'True': True,
            'False': False,
            'None': None,
            'abs': abs,
            'all': all,
            'any': any,
            'bool': bool,
            'dict': dict,
            'enumerate': enumerate,
            'filter': filter,
            'float': float,
            'frozenset': frozenset,
            'int': int,
            'isinstance': isinstance,
            'len': len,
            'list': list,
            'map': map,
            'max': max,
            'min': min,
            'pow': pow,
            'print': print,
            'range': range,
            'reversed': reversed,
            'round': round,
            'set': set,
            'slice': slice,
            'sorted': sorted,
            'str': str,
            'sum': sum,
            'tuple': tuple,
            'type': type,
            'zip': zip,
        }
        
        exec_globals = {
            '__builtins__': safe_builtins,
            # 허용된 모듈
            'pd': pd,
            'np': np,
            'numpy': np,
            'pandas': pd,
            'math': math,
            'datetime': datetime,
            'stats': stats,
            'scipy': __import__('scipy'),
        }
        
        # 런타임 데이터 추가
        exec_globals.update(runtime_data)
        
        return exec_globals
    
    def _execute_restricted(self, code: str, exec_globals: Dict) -> Any:
        """RestrictedPython으로 실행"""
        byte_code = compile_restricted(code, '<inline>', 'exec')
        exec(byte_code, exec_globals)
        return exec_globals.get('result')
    
    def _execute_simple(self, code: str, exec_globals: Dict) -> Any:
        """단순 exec 실행 (RestrictedPython 없을 때)"""
        exec(code, exec_globals)
        return exec_globals.get('result')
    
    @contextmanager
    def _timeout(self, seconds: int):
        """타임아웃 컨텍스트 매니저"""
        def timeout_handler(signum, frame):
            raise TimeoutError("Execution timed out")
        
        # SIGALRM 설정 (Unix only)
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)
        
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
```

**TODO:**
- [ ] `SandboxExecutor` 클래스 구현
- [ ] `_create_exec_globals()` 메서드 구현 (안전한 builtins)
- [ ] RestrictedPython 기반 실행 구현
- [ ] 폴백 실행 (RestrictedPython 없을 때)
- [ ] 타임아웃 처리 구현
- [ ] Windows 호환성 고려 (선택적)

---

## 📋 Phase 4: Code Generator

### 4.1 `src/code_gen/prompts.py`

```python
"""Code Generation 프롬프트 템플릿"""

SYSTEM_PROMPT = """You are a Python code generator for medical data analysis.

## Your Task
Generate Python code that accomplishes the user's analysis task.

## Available Variables (already defined, DO NOT load or create them)
{available_variables}

## Allowed Imports
```python
{allowed_imports}
```

## STRICT RULES - MUST FOLLOW
1. DO NOT use: os, subprocess, sys, open(), eval(), exec(), __import__
2. DO NOT read/write files
3. DO NOT make network requests
4. DO NOT define functions or classes (write inline code)
5. Use vectorized pandas/numpy operations instead of loops
6. Handle NaN/missing values with .dropna() or .fillna()
7. The final result MUST be assigned to a variable named `result`

## Output Format
- Return ONLY the Python code
- Wrap code in ```python ... ``` block
- Code must be complete and executable
- Result variable must contain the final answer

## Sample Data (for reference only)
{sample_data}
"""

USER_PROMPT = """## Task
{task_description}

## Expected Output Format
{expected_output}
{hints_section}
{constraints_section}

Generate the Python code now:"""


def build_prompt(request: "CodeRequest") -> tuple[str, str]:
    """
    CodeRequest로부터 프롬프트 생성
    
    Returns:
        (system_prompt, user_prompt)
    """
    ctx = request.execution_context
    
    # 변수 설명 포맷팅
    var_desc = "\n".join([
        f"- `{name}`: {desc}"
        for name, desc in ctx.available_variables.items()
    ])
    
    # Import 목록 포맷팅
    imports = "\n".join(ctx.available_imports)
    
    # 샘플 데이터 포맷팅
    sample = "No sample data provided"
    if ctx.sample_data:
        import json
        sample = json.dumps(ctx.sample_data, indent=2, default=str)
    
    system = SYSTEM_PROMPT.format(
        available_variables=var_desc,
        allowed_imports=imports,
        sample_data=sample
    )
    
    # 힌트/제약 섹션
    hints_section = ""
    if request.hints:
        hints_section = f"\n## Hints\n{request.hints}"
    
    constraints_section = ""
    if request.constraints:
        constraints_section = "\n## Additional Constraints\n" + "\n".join(
            f"- {c}" for c in request.constraints
        )
    
    user = USER_PROMPT.format(
        task_description=request.task_description,
        expected_output=request.expected_output,
        hints_section=hints_section,
        constraints_section=constraints_section
    )
    
    return system, user


# 에러 수정용 프롬프트
ERROR_FIX_PROMPT = """The previous code failed with the following error:

## Previous Code
```python
{previous_code}
```

## Error
{error_message}

Please fix the code and try again. Remember:
1. Assign the final result to `result` variable
2. Handle edge cases and NaN values
3. Follow all the rules from the original prompt

Generate the fixed Python code:"""
```

**TODO:**
- [ ] `SYSTEM_PROMPT` 작성
- [ ] `USER_PROMPT` 작성
- [ ] `build_prompt()` 함수 구현
- [ ] `ERROR_FIX_PROMPT` 작성

---

### 4.2 `src/code_gen/generator.py`

```python
"""코드 생성기 - LLM을 사용한 코드 생성만 담당"""

import re
from typing import Optional
from ..models import CodeRequest, GenerationResult, ValidationResult
from .validator import CodeValidator
from .prompts import build_prompt, ERROR_FIX_PROMPT


class CodeGenerator:
    """코드 생성기 - 생성과 검증만 담당 (실행은 Agent가)"""
    
    def __init__(
        self,
        llm_client,
        validator: Optional[CodeValidator] = None
    ):
        """
        Args:
            llm_client: LLM 클라이언트 (shared.llm.client)
            validator: CodeValidator (없으면 기본 생성)
        """
        self.llm = llm_client
        self.validator = validator or CodeValidator()
    
    async def generate(self, request: CodeRequest) -> GenerationResult:
        """
        코드 생성 + 검증
        
        Args:
            request: 코드 생성 요청
        
        Returns:
            GenerationResult with code and validation info
        """
        # 1. 프롬프트 생성
        system_prompt, user_prompt = build_prompt(request)
        
        # 2. LLM 호출
        response = await self.llm.ainvoke(
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )
        
        # 3. 코드 추출
        code = self._extract_code(response)
        
        # 4. 검증
        validation = self.validator.validate(code)
        
        return GenerationResult(
            code=code,
            is_valid=validation.is_valid,
            validation_errors=validation.errors,
            validation_warnings=validation.warnings
        )
    
    async def generate_with_retry(
        self,
        request: CodeRequest,
        previous_code: str,
        error_message: str
    ) -> GenerationResult:
        """
        에러 정보를 바탕으로 코드 재생성
        
        Args:
            request: 원본 요청
            previous_code: 실패한 이전 코드
            error_message: 에러 메시지
        
        Returns:
            GenerationResult
        """
        system_prompt, _ = build_prompt(request)
        
        user_prompt = ERROR_FIX_PROMPT.format(
            previous_code=previous_code,
            error_message=error_message
        )
        
        response = await self.llm.ainvoke(
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )
        
        code = self._extract_code(response)
        validation = self.validator.validate(code)
        
        return GenerationResult(
            code=code,
            is_valid=validation.is_valid,
            validation_errors=validation.errors,
            validation_warnings=validation.warnings
        )
    
    def _extract_code(self, response: str) -> str:
        """
        LLM 응답에서 코드 블록 추출
        
        ```python
        code here
        ```
        
        또는 그냥 코드만 있는 경우도 처리
        """
        # ```python ... ``` 블록 찾기
        pattern = r'```python\s*(.*?)\s*```'
        matches = re.findall(pattern, response, re.DOTALL)
        
        if matches:
            return matches[0].strip()
        
        # ``` ... ``` 블록 찾기 (언어 지정 없이)
        pattern = r'```\s*(.*?)\s*```'
        matches = re.findall(pattern, response, re.DOTALL)
        
        if matches:
            return matches[0].strip()
        
        # 코드 블록 없으면 전체를 코드로 간주
        return response.strip()
```

**TODO:**
- [ ] `CodeGenerator` 클래스 구현
- [ ] `generate()` 메서드 구현
- [ ] `generate_with_retry()` 메서드 구현
- [ ] `_extract_code()` 메서드 구현

---

## 📋 Phase 5: Config & Init

### 5.1 `src/config.py`

```python
"""AnalysisAgent 설정"""

from dataclasses import dataclass


@dataclass
class CodeGenConfig:
    """Code Generation 설정"""
    
    # 타임아웃
    execution_timeout_seconds: int = 30
    
    # 재시도
    max_retries: int = 2
    
    # 결과 크기 제한 (bytes)
    max_result_size: int = 10_000_000  # 10MB
    
    # LLM 설정
    temperature: float = 0.0
```

**TODO:**
- [ ] `CodeGenConfig` 정의

---

### 5.2 `src/code_gen/__init__.py`

```python
"""Code Generation 시스템"""

from .validator import CodeValidator
from .sandbox import SandboxExecutor
from .generator import CodeGenerator

__all__ = [
    "CodeValidator",
    "SandboxExecutor", 
    "CodeGenerator",
]
```

**TODO:**
- [ ] `__init__.py` 작성

---

## 📋 Phase 6: 테스트

### 6.1 `tests/test_validator.py`

```python
"""CodeValidator 테스트"""

import pytest
from src.code_gen.validator import CodeValidator


class TestCodeValidator:
    
    @pytest.fixture
    def validator(self):
        return CodeValidator()
    
    # === 금지 패턴 테스트 ===
    
    def test_forbidden_os_import(self, validator):
        code = "import os\nos.system('ls')"
        result = validator.validate(code)
        assert not result.is_valid
        assert any("os" in e.lower() for e in result.errors)
    
    def test_forbidden_subprocess(self, validator):
        code = "import subprocess\nsubprocess.run(['ls'])"
        result = validator.validate(code)
        assert not result.is_valid
    
    def test_forbidden_eval(self, validator):
        code = "result = eval('1+1')"
        result = validator.validate(code)
        assert not result.is_valid
    
    def test_forbidden_exec(self, validator):
        code = "exec('print(1)')"
        result = validator.validate(code)
        assert not result.is_valid
    
    def test_forbidden_open(self, validator):
        code = "f = open('test.txt', 'w')"
        result = validator.validate(code)
        assert not result.is_valid
    
    def test_forbidden_dunder_import(self, validator):
        code = "__import__('os')"
        result = validator.validate(code)
        assert not result.is_valid
    
    # === 허용 코드 테스트 ===
    
    def test_allowed_pandas(self, validator):
        code = """
import pandas as pd
import numpy as np

result = df['HR'].mean()
"""
        result = validator.validate(code)
        assert result.is_valid
    
    def test_allowed_scipy(self, validator):
        code = """
from scipy import stats
result = stats.pearsonr(df['HR'], df['SpO2'])
"""
        result = validator.validate(code)
        assert result.is_valid
    
    def test_allowed_math(self, validator):
        code = """
import math
result = math.sqrt(df['HR'].var())
"""
        result = validator.validate(code)
        assert result.is_valid
    
    # === 구문 에러 테스트 ===
    
    def test_syntax_error(self, validator):
        code = "def broken("
        result = validator.validate(code)
        assert not result.is_valid
        assert any("syntax" in e.lower() for e in result.errors)
    
    # === result 변수 경고 ===
    
    def test_missing_result_warning(self, validator):
        code = "x = df['HR'].mean()"
        result = validator.validate(code)
        assert result.is_valid  # 에러는 아님
        assert any("result" in w.lower() for w in result.warnings)
    
    def test_has_result_no_warning(self, validator):
        code = "result = df['HR'].mean()"
        result = validator.validate(code)
        assert result.is_valid
        assert not any("result" in w.lower() for w in result.warnings)
```

**TODO:**
- [ ] 금지 패턴 테스트 작성
- [ ] 허용 코드 테스트 작성
- [ ] 구문 에러 테스트 작성
- [ ] result 변수 경고 테스트 작성

---

### 6.2 `tests/test_sandbox.py`

```python
"""SandboxExecutor 테스트"""

import pytest
import pandas as pd
import numpy as np
from src.code_gen.sandbox import SandboxExecutor


class TestSandboxExecutor:
    
    @pytest.fixture
    def executor(self):
        return SandboxExecutor(timeout_seconds=5)
    
    @pytest.fixture
    def sample_data(self):
        return {
            "df": pd.DataFrame({
                "HR": [70, 80, 90, 100, 110],
                "SpO2": [98, 97, 96, 95, 94]
            }),
            "case_ids": ["1", "2", "3"],
            "param_keys": ["HR", "SpO2"]
        }
    
    # === 기본 실행 테스트 ===
    
    def test_simple_execution(self, executor, sample_data):
        code = "result = df['HR'].mean()"
        result = executor.execute(code, sample_data)
        
        assert result.success
        assert result.result == 90.0
    
    def test_pandas_operations(self, executor, sample_data):
        code = """
result = {
    'mean': df['HR'].mean(),
    'std': df['HR'].std(),
    'max': df['HR'].max()
}
"""
        result = executor.execute(code, sample_data)
        
        assert result.success
        assert result.result['mean'] == 90.0
    
    def test_numpy_operations(self, executor, sample_data):
        code = "result = np.mean(df['HR'].values)"
        result = executor.execute(code, sample_data)
        
        assert result.success
        assert result.result == 90.0
    
    def test_scipy_stats(self, executor, sample_data):
        code = """
from scipy import stats
corr, pval = stats.pearsonr(df['HR'], df['SpO2'])
result = {'correlation': corr, 'pvalue': pval}
"""
        result = executor.execute(code, sample_data)
        
        assert result.success
        assert 'correlation' in result.result
    
    # === 타임아웃 테스트 ===
    
    def test_timeout(self, executor, sample_data):
        code = """
import time
time.sleep(10)
result = 1
"""
        result = executor.execute(code, sample_data)
        
        assert not result.success
        assert result.error_type == "timeout"
    
    def test_infinite_loop_timeout(self, executor, sample_data):
        code = """
while True:
    pass
result = 1
"""
        result = executor.execute(code, sample_data)
        
        assert not result.success
        assert result.error_type == "timeout"
    
    # === 런타임 에러 테스트 ===
    
    def test_runtime_error(self, executor, sample_data):
        code = "result = df['NONEXISTENT'].mean()"
        result = executor.execute(code, sample_data)
        
        assert not result.success
        assert result.error_type == "runtime"
    
    def test_division_by_zero(self, executor, sample_data):
        code = "result = 1 / 0"
        result = executor.execute(code, sample_data)
        
        assert not result.success
        assert result.error_type == "runtime"
    
    # === 결과 없음 테스트 ===
    
    def test_no_result_variable(self, executor, sample_data):
        code = "x = df['HR'].mean()"
        result = executor.execute(code, sample_data)
        
        assert result.success
        assert result.result is None  # result 변수 없음
```

**TODO:**
- [ ] 기본 실행 테스트 작성
- [ ] 타임아웃 테스트 작성
- [ ] 런타임 에러 테스트 작성
- [ ] 결과 없음 테스트 작성

---

### 6.3 `tests/test_generator.py`

```python
"""CodeGenerator 테스트 (LLM Mock 사용)"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.models import CodeRequest, ExecutionContext
from src.code_gen.generator import CodeGenerator
from src.code_gen.validator import CodeValidator


class TestCodeGenerator:
    
    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        return llm
    
    @pytest.fixture
    def generator(self, mock_llm):
        return CodeGenerator(llm_client=mock_llm)
    
    @pytest.fixture
    def sample_request(self):
        return CodeRequest(
            task_description="Calculate mean of HR",
            expected_output="float",
            execution_context=ExecutionContext(
                available_variables={
                    "df": "DataFrame with HR column"
                },
                available_imports=["pandas as pd", "numpy as np"]
            )
        )
    
    # === 코드 추출 테스트 ===
    
    @pytest.mark.asyncio
    async def test_extract_code_with_python_block(self, generator, mock_llm, sample_request):
        mock_llm.ainvoke.return_value = """
Here's the code:

```python
result = df['HR'].mean()
```

This calculates the mean.
"""
        result = await generator.generate(sample_request)
        
        assert result.code == "result = df['HR'].mean()"
    
    @pytest.mark.asyncio
    async def test_extract_code_without_language(self, generator, mock_llm, sample_request):
        mock_llm.ainvoke.return_value = """
```
result = df['HR'].mean()
```
"""
        result = await generator.generate(sample_request)
        
        assert result.code == "result = df['HR'].mean()"
    
    @pytest.mark.asyncio
    async def test_extract_code_raw(self, generator, mock_llm, sample_request):
        mock_llm.ainvoke.return_value = "result = df['HR'].mean()"
        
        result = await generator.generate(sample_request)
        
        assert result.code == "result = df['HR'].mean()"
    
    # === 검증 통합 테스트 ===
    
    @pytest.mark.asyncio
    async def test_valid_code_passes_validation(self, generator, mock_llm, sample_request):
        mock_llm.ainvoke.return_value = "```python\nresult = df['HR'].mean()\n```"
        
        result = await generator.generate(sample_request)
        
        assert result.is_valid
        assert len(result.validation_errors) == 0
    
    @pytest.mark.asyncio
    async def test_forbidden_code_fails_validation(self, generator, mock_llm, sample_request):
        mock_llm.ainvoke.return_value = "```python\nimport os\nresult = os.getcwd()\n```"
        
        result = await generator.generate(sample_request)
        
        assert not result.is_valid
        assert len(result.validation_errors) > 0
```

**TODO:**
- [ ] Mock LLM 설정
- [ ] 코드 추출 테스트 작성
- [ ] 검증 통합 테스트 작성

---

### 6.4 `tests/test_integration.py`

```python
"""통합 테스트 - 실제 LLM 사용 (선택적)"""

import pytest
import pandas as pd
from src.models import CodeRequest, ExecutionContext
from src.code_gen import CodeGenerator, CodeValidator, SandboxExecutor


@pytest.mark.integration  # pytest -m integration으로 실행
class TestIntegration:
    
    @pytest.fixture
    def full_pipeline(self):
        from shared.llm import get_llm_client
        
        llm = get_llm_client()
        validator = CodeValidator()
        executor = SandboxExecutor(timeout_seconds=30)
        generator = CodeGenerator(llm, validator)
        
        return generator, executor
    
    @pytest.fixture
    def sample_data(self):
        return {
            "df": pd.DataFrame({
                "Time": range(100),
                "HR": [70 + i % 30 for i in range(100)],
                "SpO2": [98 - i % 5 for i in range(100)]
            }),
            "cohort": pd.DataFrame({
                "caseid": [1, 2, 3],
                "age": [45, 55, 65],
                "sex": ["M", "F", "M"]
            }),
            "case_ids": ["1", "2", "3"],
            "param_keys": ["HR", "SpO2"]
        }
    
    @pytest.mark.asyncio
    async def test_mean_calculation(self, full_pipeline, sample_data):
        generator, executor = full_pipeline
        
        request = CodeRequest(
            task_description="Calculate the mean of HR",
            expected_output="A single float value",
            execution_context=ExecutionContext(
                available_variables={
                    "df": f"DataFrame with columns {list(sample_data['df'].columns)}"
                }
            )
        )
        
        # 생성
        gen_result = await generator.generate(request)
        assert gen_result.is_valid, f"Validation failed: {gen_result.validation_errors}"
        
        # 실행
        exec_result = executor.execute(gen_result.code, sample_data)
        assert exec_result.success, f"Execution failed: {exec_result.error}"
        assert isinstance(exec_result.result, (int, float))
    
    @pytest.mark.asyncio
    async def test_ratio_calculation(self, full_pipeline, sample_data):
        generator, executor = full_pipeline
        
        request = CodeRequest(
            task_description="Calculate the ratio of HR values above 80",
            expected_output="A float between 0.0 and 1.0",
            execution_context=ExecutionContext(
                available_variables={
                    "df": f"DataFrame with HR column, values range 70-99"
                }
            ),
            hints="Use (df['HR'] > 80).mean() or similar"
        )
        
        gen_result = await generator.generate(request)
        assert gen_result.is_valid
        
        exec_result = executor.execute(gen_result.code, sample_data)
        assert exec_result.success
        assert 0.0 <= exec_result.result <= 1.0
```

**TODO:**
- [ ] 통합 테스트 환경 설정
- [ ] 실제 LLM 연동 테스트 (선택적)
- [ ] E2E 시나리오 테스트

---

## 📦 Dependencies

```
# requirements.txt

# Core
pydantic>=2.0
pandas>=2.0
numpy>=1.24

# Sandbox (택 1)
RestrictedPython>=7.0

# LLM (shared에서 가져오거나)
openai>=1.0

# Test
pytest>=7.0
pytest-asyncio>=0.21
pytest-cov>=4.0
```

**TODO:**
- [ ] requirements.txt 작성

---

## ✅ 구현 순서 체크리스트

```
=== Week 1: 기반 ===
[ ] 1. 디렉토리 구조 생성
[ ] 2. requirements.txt 작성
[ ] 3. src/models/context.py (ExecutionContext)
[ ] 4. src/models/code_gen.py (CodeRequest, GenerationResult, etc.)
[ ] 5. src/models/__init__.py
[ ] 6. src/code_gen/validator.py (CodeValidator)
[ ] 7. tests/test_validator.py

=== Week 2: 실행 ===
[ ] 8. src/code_gen/sandbox.py (SandboxExecutor)
[ ] 9. tests/test_sandbox.py
[ ] 10. src/code_gen/prompts.py

=== Week 3: 생성 ===
[ ] 11. src/code_gen/generator.py (CodeGenerator)
[ ] 12. tests/test_generator.py
[ ] 13. src/code_gen/__init__.py
[ ] 14. src/config.py

=== Week 4: 통합 ===
[ ] 15. tests/test_integration.py
[ ] 16. DataContext 연동 헬퍼
[ ] 17. README.md
```

---

## 🔄 테스트 시나리오

| # | 입력 | 기대 결과 |
|---|------|----------|
| 1 | "HR의 평균 계산" | `df["HR"].mean()` → float |
| 2 | "HR > 100인 비율" | `(df["HR"] > 100).mean()` → 0.0~1.0 |
| 3 | "HR과 SpO2 상관관계" | `stats.pearsonr(...)` → (corr, pval) |
| 4 | `import os` 포함 | Validation 실패 |
| 5 | `while True: pass` | Timeout 에러 |
| 6 | 문법 에러 코드 | Syntax 에러 |

