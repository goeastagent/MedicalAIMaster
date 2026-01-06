# src/agents/config.py
"""
VitalExtractionAgent Configuration Classes

각 노드별 설정을 정의합니다.
LLM 및 DB 설정은 shared 패키지에서 가져옵니다.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field

# shared 패키지 경로 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# shared 패키지에서 설정 import
from shared.config.llm import LLMConfig, BaseLLMNodeConfig
from shared.config.database import PostgresConfig, Neo4jConfig


@dataclass
class QueryUnderstandingConfig(BaseLLMNodeConfig):
    """
    [100] QueryUnderstanding 노드 설정
    
    LLM 설정은 shared.config.llm.LLMConfig에서 관리됩니다.
    - LLMConfig.OPENAI_MODEL / ANTHROPIC_MODEL
    - LLMConfig.TEMPERATURE
    - LLMConfig.MAX_TOKENS
    """
    
    # Schema Context 설정
    max_parameters_in_context: int = 100  # 컨텍스트에 포함할 최대 파라미터 수
    include_sample_values: bool = False   # 샘플 값 포함 여부 (현재 미사용)
    
    # LLM 응답 파싱
    strict_json: bool = True              # JSON 파싱 strict 모드


@dataclass
class ParameterResolverConfig(BaseLLMNodeConfig):
    """
    [200] ParameterResolver 노드 설정
    
    LLM 설정은 shared.config.llm.LLMConfig에서 관리됩니다.
    """
    
    # 검색 설정
    search_limit: int = 50                # PostgreSQL 검색 결과 제한
    similarity_threshold: float = 0.7     # 유사도 임계값 (미래 벡터 검색용)
    
    # Resolution Mode 설정
    auto_select_threshold: int = 5        # 후보 5개 이하면 all_sources 자동 선택
    ask_clarification: bool = True        # 모호할 때 사용자에게 질문


@dataclass
class PlanBuilderConfig:
    """
    [300] PlanBuilder 노드 설정
    
    이 노드는 LLM을 사용하지 않으므로 BaseLLMNodeConfig를 상속하지 않습니다.
    """
    
    # Validation 설정
    validate_files: bool = True           # 파일 존재 여부 확인
    min_confidence: float = 0.5           # 최소 신뢰도 (경고 발생 기준)
    
    # Temporal 기본값
    default_temporal_type: str = "full_record"
    default_margin_seconds: int = 300


@dataclass
class VitalExtractionConfig:
    """
    VitalExtractionAgent 전역 설정
    
    LLM, DB 연결은 shared 패키지에서 관리합니다:
    - LLM: shared.llm.client.get_llm_client()
    - PostgreSQL: shared.database.connection.get_db_manager()
    - Neo4j: shared.database.neo4j_connection.get_neo4j_driver()
    """
    
    # 노드별 설정
    query_understanding: QueryUnderstandingConfig = field(
        default_factory=QueryUnderstandingConfig
    )
    parameter_resolver: ParameterResolverConfig = field(
        default_factory=ParameterResolverConfig
    )
    plan_builder: PlanBuilderConfig = field(
        default_factory=PlanBuilderConfig
    )
    
    # DB 연결 (shared.config.database에서 설정)
    postgres_enabled: bool = True
    neo4j_enabled: bool = Neo4jConfig.ENABLED
    
    # 로깅
    verbose: bool = True
    log_llm_calls: bool = True  # shared.llm.client.enable_llm_logging() 사용


# 기본 설정 인스턴스
default_config = VitalExtractionConfig()


def get_config() -> VitalExtractionConfig:
    """전역 설정 인스턴스 반환"""
    return default_config


# =============================================================================
# Convenience Re-exports
# =============================================================================
# shared 패키지 설정을 ExtractionAgent에서 쉽게 접근할 수 있도록 re-export

__all__ = [
    # 노드별 설정
    "QueryUnderstandingConfig",
    "ParameterResolverConfig", 
    "PlanBuilderConfig",
    "VitalExtractionConfig",
    "get_config",
    "default_config",
    
    # shared에서 re-export
    "LLMConfig",
    "BaseLLMNodeConfig",
    "PostgresConfig",
    "Neo4jConfig",
]
