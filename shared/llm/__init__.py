# shared/llm/__init__.py
"""
LLM Client Module

LLM 클라이언트 및 유틸리티:
- client.py: OpenAI, Anthropic, Ollama 클라이언트 및 로깅 기능
"""

from .client import (
    # Abstract base
    AbstractLLMClient,
    # Concrete implementations
    OpenAIClient,
    ClaudeClient,
    OllamaClient,
    LoggingLLMClient,
    # Helper functions
    get_llm_client,
    reset_llm_client,
    set_ollama_model,
    get_current_model_name,
    enable_llm_logging,
    disable_llm_logging,
    get_llm_log_session_dir,
    # Config
    LLMRetryConfig,
)

__all__ = [
    # Abstract base
    'AbstractLLMClient',
    # Concrete implementations
    'OpenAIClient',
    'ClaudeClient',
    'OllamaClient',
    'LoggingLLMClient',
    # Helper functions
    'get_llm_client',
    'reset_llm_client',
    'set_ollama_model',
    'get_current_model_name',
    'enable_llm_logging',
    'disable_llm_logging',
    'get_llm_log_session_dir',
    # Config
    'LLMRetryConfig',
]
