"""AnalysisAgent Configuration

Central configuration management for AnalysisAgent.
Includes settings for CodeGen, Sandbox, and the main Agent.
"""

from dataclasses import dataclass, field
from typing import List, Tuple


# =============================================================================
# AnalysisAgent Configuration
# =============================================================================

@dataclass
class AnalysisAgentConfig:
    """Configuration for AnalysisAgent"""
    
    # Planning
    use_llm_planning: bool = True
    """Use LLM for planning (False = rule-based only)"""
    
    planning_max_tokens: int = 2000
    """Max tokens for planning LLM response"""
    
    max_plan_steps: int = 10
    """Maximum allowed steps in a plan"""
    
    # Execution
    code_gen_max_retries: int = 2
    """Max retries for code generation"""
    
    code_gen_timeout: int = 30
    """Timeout for code execution (seconds)"""
    
    # Caching
    use_cache: bool = True
    """Enable result caching"""
    
    cache_ttl_minutes: int = 60
    """Cache TTL in minutes"""
    
    # Debugging
    debug_mode: bool = False
    """Enable debug logging"""


# =============================================================================
# CodeGen Configuration
# =============================================================================


@dataclass
class SandboxConfig:
    """샌드박스 실행 설정"""
    
    timeout_seconds: int = 30
    """최대 실행 시간 (초)"""
    
    max_result_size: int = 10_000_000
    """결과 크기 제한 (bytes, 기본 10MB)"""
    
    capture_stdout: bool = True
    """print 출력 캡처 여부"""
    
    truncate_dataframe_rows: int = 10000
    """DataFrame 결과 자동 잘림 기준 행 수"""
    
    truncate_list_length: int = 1000
    """List 결과 자동 잘림 기준 길이"""


@dataclass
class ValidatorConfig:
    """코드 검증 설정"""
    
    forbidden_patterns: List[Tuple[str, str]] = field(default_factory=lambda: [
        (r"\bimport\s+os\b", "os module import"),
        (r"\bimport\s+subprocess\b", "subprocess module import"),
        (r"\bimport\s+sys\b", "sys module import"),
        (r"\bfrom\s+os\s+import\b", "os module import"),
        (r"\bfrom\s+subprocess\s+import\b", "subprocess module import"),
        (r"\bfrom\s+sys\s+import\b", "sys module import"),
        (r"\b__import__\s*\(", "__import__ function"),
        (r"\bexec\s*\(", "exec function"),
        (r"\beval\s*\(", "eval function"),
        (r"\bcompile\s*\(", "compile function"),
        (r"\bglobals\s*\(", "globals function"),
        (r"\blocals\s*\(", "locals function"),
        (r"\bopen\s*\(", "open function"),
        (r"\binput\s*\(", "input function"),
        (r"\bbreakpoint\s*\(", "breakpoint function"),
        (r"\.read\s*\(", "file read"),
        (r"\.write\s*\(", "file write"),
        (r"requests\.", "requests library"),
        (r"urllib\.", "urllib library"),
        (r"socket\.", "socket library"),
    ])
    """금지 패턴 목록 (정규식, 설명)"""
    
    forbidden_modules: List[str] = field(default_factory=lambda: [
        "os", "subprocess", "sys", "shutil", "pathlib",
        "pickle", "shelve", "socket", "requests", "urllib",
        "http", "ftplib", "smtplib", "telnetlib",
        "ctypes", "multiprocessing", "threading",
        "builtins", "importlib",
    ])
    """금지 모듈 목록"""
    
    allowed_modules: List[str] = field(default_factory=lambda: [
        "pandas", "numpy", 
        "scipy", "scipy.stats", "scipy.signal", "scipy.interpolate",  # Full scipy support for signal processing
        "datetime", "math", "statistics",
        "collections", "itertools", "functools",
        "re", "json",
        "vitaldb",  # VitalDB for high-resolution medical signal loading
    ])
    """허용 모듈 목록"""


@dataclass
class GeneratorConfig:
    """코드 생성 설정"""
    
    max_tokens: int = 2000
    """LLM 응답 최대 토큰 수"""
    
    max_retries: int = 2
    """에러 발생 시 최대 재시도 횟수"""
    
    available_imports: List[str] = field(default_factory=lambda: [
        "pandas as pd",
        "numpy as np",
        "scipy.stats as stats",
        "scipy.signal",
        "scipy.interpolate",
        "datetime",
        "math",
        "vitaldb",
    ])
    """샌드박스에서 사용 가능한 import 목록"""


@dataclass
class CodeGenConfig:
    """Code Generation 통합 설정"""
    
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    """샌드박스 설정"""
    
    validator: ValidatorConfig = field(default_factory=ValidatorConfig)
    """검증 설정"""
    
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)
    """생성 설정"""
    
    debug_mode: bool = False
    """디버그 모드 (상세 로깅)"""
    
    log_generated_code: bool = True
    """생성된 코드 로깅 여부"""


# ═══════════════════════════════════════════════════════════════════════════
# 기본 설정 인스턴스
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG = CodeGenConfig()
"""기본 설정 - import하여 사용"""


def get_config() -> CodeGenConfig:
    """현재 설정 반환 (싱글톤 패턴)"""
    return DEFAULT_CONFIG


def create_config(
    timeout_seconds: int = None,
    max_retries: int = None,
    debug_mode: bool = None,
    **kwargs
) -> CodeGenConfig:
    """커스텀 설정 생성 헬퍼
    
    Example:
        config = create_config(timeout_seconds=60, max_retries=3)
    """
    sandbox = SandboxConfig(
        timeout_seconds=timeout_seconds or DEFAULT_CONFIG.sandbox.timeout_seconds,
        **{k: v for k, v in kwargs.items() if hasattr(SandboxConfig, k)}
    )
    
    generator = GeneratorConfig(
        max_retries=max_retries or DEFAULT_CONFIG.generator.max_retries,
        **{k: v for k, v in kwargs.items() if hasattr(GeneratorConfig, k)}
    )
    
    return CodeGenConfig(
        sandbox=sandbox,
        generator=generator,
        debug_mode=debug_mode if debug_mode is not None else DEFAULT_CONFIG.debug_mode,
    )

