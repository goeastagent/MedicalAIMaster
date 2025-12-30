# src/agents/models/__init__.py
"""
Pydantic 모델들 - LLM 응답 구조화

사용 예시:
    from src.agents.models.llm_responses import FileClassificationItem
    
    # LLM 응답을 구조화
    item = FileClassificationItem(**llm_response)
"""

from .llm_responses import (
    # 헬퍼 함수
    parse_llm_response,
    
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
    # 헬퍼 함수
    "parse_llm_response",
    
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
