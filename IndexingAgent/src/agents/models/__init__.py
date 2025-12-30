# src/agents/models/__init__.py
"""
Pydantic 모델 패키지

모든 Pydantic 스키마를 중앙에서 관리합니다.

구조:
- base.py: 공통 베이스 클래스 (LLMAnalysisBase, PhaseResultBase)
- state_schemas.py: AgentState 관련 스키마 (ColumnSchema, EntityIdentification, ...)
- llm_responses.py: Phase별 LLM 응답 스키마

사용 예시:
    from src.agents.models import LLMAnalysisBase, ColumnSchema, FileClassificationItem
    
    # 커스텀 모델 정의
    class MyResult(LLMAnalysisBase):
        custom_field: str
    
    # LLM 응답을 구조화
    item = FileClassificationItem(**llm_response)
"""

# =============================================================================
# base.py - 공통 베이스 클래스
# =============================================================================
from .base import (
    # 헬퍼 함수
    parse_llm_response,
    
    # 베이스 클래스
    LLMAnalysisBase,
    PhaseResultBase,
    Neo4jPhaseResultBase,
)

# =============================================================================
# state_schemas.py - 상태 관련 스키마
# =============================================================================
from .state_schemas import (
    ColumnSchema,
    EntityIdentification,
    ProjectContext,
    Relationship,
    EntityUnderstanding,
    OntologyContext,
)

# =============================================================================
# llm_responses.py - Phase별 LLM 응답 스키마
# =============================================================================
from .llm_responses import (
    # Phase 4: File Classification
    FileClassificationItem,
    FileClassificationResponse,
    FileClassificationResult,
    
    # Phase 5: Metadata Semantic
    ColumnRoleMapping,
    ColumnRoleMappingResponse,
    DataDictionaryEntry,
    MetadataSemanticResult,
    
    # Phase 6: Data Semantic
    ColumnSemanticResult,
    DataSemanticResponse,
    DataSemanticResult,
    
    # Phase 8: Entity Identification
    TableEntityResult,
    EntityIdentificationResponse,
    Phase8Result,
    
    # Phase 9: Relationship Inference
    TableRelationship,
    RelationshipInferenceResponse,
    Phase9Result,
    
    # Phase 10: Ontology Enhancement
    SubCategoryResult,
    ConceptHierarchyResponse,
    SemanticEdge,
    SemanticEdgesResponse,
    MedicalTermMapping,
    MedicalTermResponse,
    CrossTableSemantic,
    CrossTableResponse,
    Phase10Result,
)


__all__ = [
    # === base.py ===
    # 헬퍼 함수
    "parse_llm_response",
    # 베이스 클래스
    "LLMAnalysisBase",
    "PhaseResultBase",
    "Neo4jPhaseResultBase",
    
    # === state_schemas.py ===
    "ColumnSchema",
    "EntityIdentification",
    "ProjectContext",
    "Relationship",
    "EntityUnderstanding",
    "OntologyContext",
    
    # === llm_responses.py ===
    # Phase 4
    "FileClassificationItem",
    "FileClassificationResponse",
    "FileClassificationResult",
    # Phase 5
    "ColumnRoleMapping",
    "ColumnRoleMappingResponse",
    "DataDictionaryEntry",
    "MetadataSemanticResult",
    # Phase 6
    "ColumnSemanticResult",
    "DataSemanticResponse",
    "DataSemanticResult",
    # Phase 8
    "TableEntityResult",
    "EntityIdentificationResponse",
    "Phase8Result",
    # Phase 9
    "TableRelationship",
    "RelationshipInferenceResponse",
    "Phase9Result",
    # Phase 10
    "SubCategoryResult",
    "ConceptHierarchyResponse",
    "SemanticEdge",
    "SemanticEdgesResponse",
    "MedicalTermMapping",
    "MedicalTermResponse",
    "CrossTableSemantic",
    "CrossTableResponse",
    "Phase10Result",
]
