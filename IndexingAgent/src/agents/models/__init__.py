# src/agents/models/__init__.py
"""
Pydantic 모델 패키지

모든 Pydantic 스키마를 중앙에서 관리합니다.

구조:
- enums.py: 열거형 타입 (ColumnRole, SourceType, DictMatchStatus)
- base.py: 공통 베이스 클래스 (LLMAnalysisBase, PhaseResultBase)
- state_schemas.py: AgentState 관련 스키마 (ColumnSchema, EntityIdentification, ...)
- llm_responses.py: Phase별 LLM 응답 스키마

사용 예시:
    from src.agents.models import LLMAnalysisBase, ColumnSchema, FileClassificationItem
    from src.agents.models import ColumnRole, SourceType
    
    # Enum 사용
    if column_role == ColumnRole.PARAMETER_CONTAINER:
        ...
    
    # 커스텀 모델 정의
    class MyResult(LLMAnalysisBase):
        custom_field: str
    
    # LLM 응답을 구조화
    item = FileClassificationItem(**llm_response)
"""

# =============================================================================
# enums.py - 열거형 타입
# =============================================================================
from .enums import (
    ColumnRole,
    SourceType,
    DictMatchStatus,
)

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
# llm_responses.py - Node별 LLM 응답 스키마
# =============================================================================
from .llm_responses import (
    # [file_classification] node
    FileClassificationItem,
    FileClassificationResponse,
    FileClassificationResult,
    
    # [column_classification] node
    ColumnClassificationItem,
    ColumnClassificationResponse,
    ColumnClassificationResult,
    
    # [metadata_semantic] node
    ColumnRoleMapping,
    ColumnRoleMappingResponse,
    DataDictionaryEntry,
    MetadataSemanticResult,
    
    # [parameter_semantic] node
    ParameterSemanticResult,
    ParameterSemanticResponse,
    ParameterSemanticResultSummary,
    
    # [entity_identification] node
    TableEntityResult,
    EntityIdentificationResponse,
    EntityIdentificationResult,
    
    # [relationship_inference] node
    TableRelationship,
    RelationshipInferenceResponse,
    RelationshipInferenceResult,
    
    # [ontology_enhancement] node
    SubCategoryResult,
    ConceptHierarchyResponse,
    SemanticEdge,
    SemanticEdgesResponse,
    MedicalTermMapping,
    MedicalTermResponse,
    CrossTableSemantic,
    CrossTableResponse,
    OntologyEnhancementResult,
)


__all__ = [
    # === enums.py ===
    "ColumnRole",
    "SourceType",
    "DictMatchStatus",
    
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
    # [file_classification]
    "FileClassificationItem",
    "FileClassificationResponse",
    "FileClassificationResult",
    # [column_classification]
    "ColumnClassificationItem",
    "ColumnClassificationResponse",
    "ColumnClassificationResult",
    # [metadata_semantic]
    "ColumnRoleMapping",
    "ColumnRoleMappingResponse",
    "DataDictionaryEntry",
    "MetadataSemanticResult",
    # [parameter_semantic]
    "ParameterSemanticResult",
    "ParameterSemanticResponse",
    "ParameterSemanticResultSummary",
    # [entity_identification]
    "TableEntityResult",
    "EntityIdentificationResponse",
    "EntityIdentificationResult",
    # [relationship_inference]
    "TableRelationship",
    "RelationshipInferenceResponse",
    "RelationshipInferenceResult",
    # [ontology_enhancement]
    "SubCategoryResult",
    "ConceptHierarchyResponse",
    "SemanticEdge",
    "SemanticEdgesResponse",
    "MedicalTermMapping",
    "MedicalTermResponse",
    "CrossTableSemantic",
    "CrossTableResponse",
    "OntologyEnhancementResult",
]
