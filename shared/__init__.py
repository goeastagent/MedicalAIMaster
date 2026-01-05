# shared/__init__.py
"""
MedicalAIMaster Shared Package

IndexingAgent와 ExtractionAgent가 공유하는 핵심 인프라 모듈입니다.

구조:
- database/: PostgreSQL 연결, 스키마, 매니저, 리포지토리
- neo4j/: Neo4j 연결 및 쿼리 빌더
- models/: 공유 열거형 및 데이터 모델
- config/: 데이터베이스, LLM 설정
- llm/: LLM 클라이언트 (OpenAI, Anthropic)

사용법:
    from shared.database import get_db_manager, FileRepository
    from shared.models import ColumnRole, ConceptCategory
    from shared.config import Neo4jConfig, LLMConfig
    from shared.llm import get_llm_client
"""

__version__ = "0.1.0"

# Convenience imports for common use cases
from .database import (
    DatabaseManager,
    get_db_manager,
    Neo4jConnection,
    get_neo4j_connection,
)

from .models import (
    ColumnRole,
    SourceType,
    DictMatchStatus,
    ConceptCategory,
)

from .config import (
    PostgresConfig,
    Neo4jConfig,
    LLMConfig,
)

__all__ = [
    '__version__',
    # Database connections
    'DatabaseManager',
    'get_db_manager',
    'Neo4jConnection',
    'get_neo4j_connection',
    # Models
    'ColumnRole',
    'SourceType',
    'DictMatchStatus',
    'ConceptCategory',
    # Config
    'PostgresConfig',
    'Neo4jConfig',
    'LLMConfig',
]
