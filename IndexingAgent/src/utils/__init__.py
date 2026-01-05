# src/utils/__init__.py
"""
Utils 모듈 - shared.llm에서 Re-export

이 파일은 shared.llm에 정의된 클래스/함수를 re-export합니다.
기존 import 경로 호환성을 유지하기 위한 목적입니다.

실제 정의: shared/llm/
"""

import sys
from pathlib import Path

# shared 패키지를 찾을 수 있도록 경로 추가
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Re-export from shared.llm
from shared.llm import (
    AbstractLLMClient,
    OpenAIClient,
    ClaudeClient,
    LoggingLLMClient,
    get_llm_client,
    reset_llm_client,
    enable_llm_logging,
    disable_llm_logging,
    get_llm_log_session_dir,
    LLMRetryConfig,
)

__all__ = [
    'AbstractLLMClient',
    'OpenAIClient',
    'ClaudeClient',
    'LoggingLLMClient',
    'get_llm_client',
    'reset_llm_client',
    'enable_llm_logging',
    'disable_llm_logging',
    'get_llm_log_session_dir',
    'LLMRetryConfig',
]

