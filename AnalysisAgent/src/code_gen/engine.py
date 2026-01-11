# AnalysisAgent/src/code_gen/engine.py
"""
코드 실행 엔진 - 생성 + 검증 + 실행 + 재시도 통합

Orchestrator와 AnalysisAgent.StepExecutor에서 공통으로 사용되는
코드 생성/실행/재시도 로직을 통합합니다.

Usage:
    from AnalysisAgent.src.code_gen import CodeExecutionEngine, CodeGenerator, SandboxExecutor
    from AnalysisAgent.src.models import CodeRequest
    
    engine = CodeExecutionEngine(
        generator=CodeGenerator(llm_client),
        sandbox=SandboxExecutor(timeout_seconds=30),
        max_retries=2
    )
    
    result = engine.execute(request, runtime_data)
    
    if result.success:
        print(result.result)
        print(result.code)
    else:
        print(f"Failed after {result.retry_count} attempts: {result.error}")
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .generator import CodeGenerator
    from .sandbox import SandboxExecutor
    from ..models.code_gen import CodeRequest

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """코드 실행 결과
    
    Attributes:
        success: 실행 성공 여부
        result: 실행 결과 (success=True일 때)
        code: 최종 생성된 코드
        error: 에러 메시지 (success=False일 때)
        retry_count: 재시도 횟수 (0부터 시작)
        execution_time_ms: 총 실행 시간 (ms)
        validation_errors: 검증 에러 목록
    """
    success: bool
    result: Any = None
    code: str = ""
    error: Optional[str] = None
    retry_count: int = 0
    execution_time_ms: float = 0.0
    validation_errors: list = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "success": self.success,
            "result": self.result,
            "code": self.code,
            "error": self.error,
            "retry_count": self.retry_count,
            "execution_time_ms": self.execution_time_ms,
            "validation_errors": self.validation_errors,
        }


class CodeExecutionEngine:
    """
    코드 생성 + 검증 + 실행 + 재시도 엔진
    
    CodeGenerator로 코드를 생성하고, SandboxExecutor로 실행하며,
    실패 시 에러 메시지를 기반으로 자동 재시도합니다.
    
    재시도 로직:
    1. CodeGenerator.generate()로 코드 생성
    2. 검증 실패 시 에러와 함께 재시도
    3. 실행 실패 시 에러와 함께 재시도
    4. max_retries 초과 시 실패 반환
    
    Attributes:
        generator: CodeGenerator 인스턴스
        sandbox: SandboxExecutor 인스턴스
        max_retries: 최대 재시도 횟수 (기본: 2)
    """
    
    def __init__(
        self,
        generator: "CodeGenerator",
        sandbox: "SandboxExecutor",
        max_retries: int = 2,
    ):
        """
        Args:
            generator: 코드 생성기
            sandbox: 샌드박스 실행기
            max_retries: 최대 재시도 횟수 (첫 시도 제외)
        """
        self.generator = generator
        self.sandbox = sandbox
        self.max_retries = max_retries
    
    def execute(
        self,
        request: "CodeRequest",
        runtime_data: Dict[str, Any],
        log_prefix: str = "",
    ) -> ExecutionResult:
        """
        코드 생성 및 실행 (with retry)
        
        Args:
            request: 코드 생성 요청
            runtime_data: 실행 시 사용할 데이터 (signals, cohort 등)
            log_prefix: 로그 메시지 접두사 (예: "[Step1]")
        
        Returns:
            ExecutionResult
        """
        start_time = time.time()
        
        last_code = ""
        last_error = ""
        validation_errors = []
        
        for attempt in range(self.max_retries + 1):
            attempt_str = f"Attempt {attempt + 1}/{self.max_retries + 1}"
            
            # ─────────────────────────────────────────────────────────────
            # 1. 코드 생성
            # ─────────────────────────────────────────────────────────────
            if attempt == 0:
                logger.debug(f"{log_prefix}{attempt_str}: Generating code...")
                gen_result = self.generator.generate(request)
            else:
                logger.debug(f"{log_prefix}{attempt_str}: Regenerating with fix...")
                gen_result = self.generator.generate_with_fix(
                    request, last_code, last_error
                )
            
            last_code = gen_result.code
            
            # ─────────────────────────────────────────────────────────────
            # 2. 검증 확인
            # ─────────────────────────────────────────────────────────────
            if not gen_result.is_valid:
                last_error = f"Validation failed: {gen_result.validation_errors}"
                validation_errors = gen_result.validation_errors
                logger.warning(f"{log_prefix}{attempt_str}: {last_error}")
                continue
            
            # ─────────────────────────────────────────────────────────────
            # 3. 코드 실행
            # ─────────────────────────────────────────────────────────────
            logger.debug(f"{log_prefix}{attempt_str}: Executing code...")
            exec_result = self.sandbox.execute(gen_result.code, runtime_data)
            
            if exec_result.success:
                execution_time = (time.time() - start_time) * 1000
                logger.info(
                    f"{log_prefix}✅ Code execution successful "
                    f"(attempt {attempt + 1}, {execution_time:.0f}ms)"
                )
                
                return ExecutionResult(
                    success=True,
                    result=exec_result.result,
                    code=gen_result.code,
                    retry_count=attempt,
                    execution_time_ms=execution_time,
                )
            
            # 실행 실패
            last_error = exec_result.error or "Unknown execution error"
            logger.warning(f"{log_prefix}{attempt_str}: Execution failed - {last_error}")
        
        # ─────────────────────────────────────────────────────────────
        # 모든 재시도 실패
        # ─────────────────────────────────────────────────────────────
        execution_time = (time.time() - start_time) * 1000
        logger.error(
            f"{log_prefix}❌ Code execution failed after {self.max_retries + 1} attempts"
        )
        
        return ExecutionResult(
            success=False,
            code=last_code,
            error=last_error,
            retry_count=self.max_retries + 1,
            execution_time_ms=execution_time,
            validation_errors=validation_errors,
        )
    
    def execute_with_context(
        self,
        request: "CodeRequest",
        runtime_data: Dict[str, Any],
        on_attempt: Optional[callable] = None,
        on_success: Optional[callable] = None,
        on_failure: Optional[callable] = None,
    ) -> ExecutionResult:
        """
        콜백과 함께 코드 실행 (고급 사용)
        
        Args:
            request: 코드 생성 요청
            runtime_data: 실행 데이터
            on_attempt: 각 시도 시작 시 호출 (attempt_num, max_retries)
            on_success: 성공 시 호출 (result)
            on_failure: 각 실패 시 호출 (attempt_num, error)
        
        Returns:
            ExecutionResult
        """
        start_time = time.time()
        
        last_code = ""
        last_error = ""
        validation_errors = []
        
        for attempt in range(self.max_retries + 1):
            if on_attempt:
                on_attempt(attempt, self.max_retries)
            
            # Generate
            if attempt == 0:
                gen_result = self.generator.generate(request)
            else:
                gen_result = self.generator.generate_with_fix(
                    request, last_code, last_error
                )
            
            last_code = gen_result.code
            
            # Validate
            if not gen_result.is_valid:
                last_error = f"Validation failed: {gen_result.validation_errors}"
                validation_errors = gen_result.validation_errors
                if on_failure:
                    on_failure(attempt, last_error)
                continue
            
            # Execute
            exec_result = self.sandbox.execute(gen_result.code, runtime_data)
            
            if exec_result.success:
                execution_time = (time.time() - start_time) * 1000
                result = ExecutionResult(
                    success=True,
                    result=exec_result.result,
                    code=gen_result.code,
                    retry_count=attempt,
                    execution_time_ms=execution_time,
                )
                if on_success:
                    on_success(result)
                return result
            
            last_error = exec_result.error or "Unknown error"
            if on_failure:
                on_failure(attempt, last_error)
        
        execution_time = (time.time() - start_time) * 1000
        return ExecutionResult(
            success=False,
            code=last_code,
            error=last_error,
            retry_count=self.max_retries + 1,
            execution_time_ms=execution_time,
            validation_errors=validation_errors,
        )
