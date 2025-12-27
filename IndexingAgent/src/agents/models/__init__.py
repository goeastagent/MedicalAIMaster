# src/agents/models/__init__.py
"""
Pydantic 모델들 - LLM 응답 구조화

사용 예시:
    from src.agents.models import FeedbackParseResult, EntityAnalysisResult
    
    # LLM 응답을 구조화
    result = FeedbackParseResult(**llm_response)
    
    # 타입 안전한 접근
    if result.action == "skip":
        ...
"""

from .llm_responses import (
    # Enums
    FeedbackAction,
    IdentifierSource,
    IdentificationStatus,
    ColumnType,
    EntityRelationType,
    
    # 응답 모델들
    FeedbackParseResult,
    ColumnSchemaResult,
    ColumnAnalysisResponse,
    
    # Entity Understanding 모델
    LinkableColumnInfo,
    EntityAnalysisResult,
    
    # 헬퍼 함수
    parse_llm_response,
    safe_parse_entity,
)

__all__ = [
    # Enums
    "FeedbackAction",
    "IdentifierSource",
    "IdentificationStatus",
    "ColumnType",
    "EntityRelationType",
    
    # 응답 모델들
    "FeedbackParseResult",
    "ColumnSchemaResult",
    "ColumnAnalysisResponse",
    
    # Entity Understanding 모델
    "LinkableColumnInfo",
    "EntityAnalysisResult",
    
    # 헬퍼 함수
    "parse_llm_response",
    "safe_parse_entity",
]
