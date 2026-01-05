# shared/config/__init__.py
"""
Shared Configuration

공유 설정 모듈:
- database.py: PostgreSQL, Neo4j 연결 설정
- llm.py: LLM Provider 설정 (OpenAI, Anthropic)
"""

from .database import (
    PostgresConfig,
    Neo4jConfig,
)

from .llm import (
    LLMConfig,
    BaseLLMNodeConfig,
    BaseLLMPhaseConfig,  # Backward compatibility
    BaseNeo4jNodeConfig,
    BaseNeo4jPhaseConfig,  # Backward compatibility
)

__all__ = [
    # Database
    'PostgresConfig',
    'Neo4jConfig',
    # LLM
    'LLMConfig',
    'BaseLLMNodeConfig',
    'BaseLLMPhaseConfig',
    'BaseNeo4jNodeConfig',
    'BaseNeo4jPhaseConfig',
]
