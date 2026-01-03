# src/agents/models/llm_responses.py
"""
LLM 응답 구조화를 위한 Pydantic 모델들

모든 LLM 호출의 응답을 타입 안전하게 관리합니다.
- 자동 타입 검증
- 누락 필드 기본값
- IDE 자동완성 지원
- 디버깅 용이

Node별 모델:
- [file_classification]: File Classification (metadata vs data)
- [column_classification]: Column Classification (column_role + parameter 생성)
- [metadata_semantic]: Metadata Semantic
- [data_semantic]: Data Semantic
- [entity_identification]: Entity Identification
- [relationship_inference]: Relationship Inference
- [ontology_enhancement]: Ontology Enhancement
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# 베이스 클래스 import
from .base import (
    LLMAnalysisBase,
    PhaseResultBase,
    Neo4jPhaseResultBase,
)


# =============================================================================
# [file_classification] node 모델
# =============================================================================

class FileClassificationItem(LLMAnalysisBase):
    """[file_classification] 개별 파일 분류 결과"""
    file_name: str = Field(
        default="",
        description="Target file name to classify"
    )
    is_metadata: bool = Field(
        default=False,
        description="True=metadata/dictionary file, False=actual data file"
    )
    # confidence, reasoning은 LLMAnalysisBase에서 상속


class FileClassificationResponse(BaseModel):
    """[file_classification] LLM 응답 전체"""
    classifications: List[FileClassificationItem] = []


class FileClassificationResult(PhaseResultBase):
    """[file_classification] 파일 분류 최종 결과"""
    total_files: int = 0
    metadata_files: List[str] = []        # is_metadata=true 파일 경로
    data_files: List[str] = []            # is_metadata=false 파일 경로
    classifications: Dict[str, Dict[str, Any]] = {}  # 파일별 상세 분류 정보
    # llm_calls, started_at, completed_at은 PhaseResultBase에서 상속


# =============================================================================
# [column_classification] node 모델
# =============================================================================

class ColumnClassificationItem(LLMAnalysisBase):
    """
    [column_classification] 개별 컬럼 분류 결과
    
    LLM이 각 컬럼에 대해 역할을 분류한 결과.
    column_role은 ColumnRole enum 값 중 하나여야 함.
    """
    column_name: str = Field(
        default="",
        description="Original column name"
    )
    column_role: str = Field(
        default="other",
        description="Column role: parameter_name, parameter_container, identifier, value, unit, timestamp, attribute, other"
    )
    is_parameter_name: bool = Field(
        default=False,
        description="True if column name itself is a measurement parameter (Wide-format)"
    )
    is_parameter_container: bool = Field(
        default=False,
        description="True if column values are parameter names (Long-format key column)"
    )
    parameters: List[str] = Field(
        default_factory=list,
        description="If is_parameter_container=True, list of parameter names from unique values"
    )
    # confidence, reasoning은 LLMAnalysisBase에서 상속


class ColumnClassificationResponse(BaseModel):
    """[column_classification] LLM 응답 전체"""
    columns: List[ColumnClassificationItem] = []
    file_summary: Optional[str] = Field(
        default=None,
        description="Optional summary of the file's data format (wide/long/mixed)"
    )


class ColumnClassificationResult(PhaseResultBase):
    """[column_classification] 컬럼 분류 최종 결과"""
    total_files: int = 0
    total_columns: int = 0
    columns_by_role: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of columns by role: {role: count}"
    )
    parameters_created: int = 0                 # parameter 테이블에 생성된 수
    parameters_from_column_name: int = 0        # Wide-format (column_name → parameter)
    parameters_from_column_value: int = 0       # Long-format (column_value → parameter)
    # llm_calls, started_at, completed_at은 PhaseResultBase에서 상속


# =============================================================================
# [metadata_semantic] node 모델
# =============================================================================

class ColumnRoleMapping(LLMAnalysisBase):
    """[metadata_semantic] 컬럼 역할 매핑 결과"""
    key_column: str = Field(
        default="",
        description="Column containing parameter name/code"
    )
    desc_column: Optional[str] = Field(
        default=None,
        description="Column containing parameter description (null if not found)"
    )
    unit_column: Optional[str] = Field(
        default=None,
        description="Column containing measurement unit (null if not found)"
    )
    extra_columns: Dict[str, str] = Field(
        default_factory=dict,
        description="Additional column mappings {role: column_name}"
    )
    # confidence, reasoning은 LLMAnalysisBase에서 상속


class ColumnRoleMappingResponse(LLMAnalysisBase):
    """[metadata_semantic] 컬럼 역할 LLM 응답"""
    key_column: str = ""
    desc_column: Optional[str] = None
    unit_column: Optional[str] = None
    extra_columns: Dict[str, str] = {}
    # confidence, reasoning은 LLMAnalysisBase에서 상속


class DataDictionaryEntry(BaseModel):
    """[metadata_semantic] data_dictionary 테이블에 저장될 엔트리"""
    source_file_id: str = ""
    source_file_name: str = ""
    parameter_key: str = ""
    parameter_desc: Optional[str] = None
    parameter_unit: Optional[str] = None
    extra_info: Dict[str, Any] = {}
    llm_confidence: Optional[float] = None


class MetadataSemanticResult(PhaseResultBase):
    """[metadata_semantic] 메타데이터 시맨틱 분석 최종 결과"""
    total_metadata_files: int = 0
    processed_files: int = 0
    total_entries_extracted: int = 0
    entries_by_file: Dict[str, int] = {}
    # llm_calls, started_at, completed_at은 PhaseResultBase에서 상속


# =============================================================================
# [parameter_semantic] node 모델
# =============================================================================

class ParameterSemanticResult(BaseModel):
    """
    [parameter_semantic] parameter의 의미론적 분석 결과
    
    LLM이 param_key, 통계, data_dictionary를 참조하여 분석
    """
    param_key: str = Field(
        default="",
        description="Parameter key (used as matching key)"
    )
    semantic_name: str = Field(
        default="",
        description="Standardized semantic name (e.g., Heart Rate)"
    )
    unit: Optional[str] = Field(
        default=None,
        description="Measurement unit (e.g., bpm, mmHg, kg)"
    )
    description: Optional[str] = Field(
        default=None,
        description="Detailed description of the parameter"
    )
    concept_category: Optional[str] = Field(
        default=None,
        description="Concept category (e.g., Vital Signs, Laboratory)"
    )
    dict_entry_key: Optional[str] = Field(
        default=None,
        description="Exact parameter_key from data_dictionary (null if no match)"
    )
    match_confidence: float = Field(
        default=0.0, 
        ge=0.0, 
        le=1.0,
        description="Dictionary matching confidence score (0.0~1.0)"
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Reasoning for the matching decision"
    )


class ParameterSemanticResponse(BaseModel):
    """[parameter_semantic] LLM 응답"""
    parameters: List[ParameterSemanticResult] = []
    summary: Optional[str] = None


class ParameterSemanticResultSummary(PhaseResultBase):
    """[parameter_semantic] 최종 결과 요약"""
    total_parameters: int = 0
    parameters_analyzed: int = 0
    parameters_matched: int = 0          # dict_entry_id 매칭 성공
    parameters_not_found: int = 0        # dict에 없는 key 반환
    parameters_null_from_llm: int = 0    # LLM이 null 반환
    batches_processed: int = 0
    # llm_calls, started_at, completed_at은 PhaseResultBase에서 상속


# =============================================================================
# [entity_identification] node 모델
# =============================================================================

class TableEntityResult(LLMAnalysisBase):
    """
    [entity_identification] 단일 테이블의 Entity 분석 결과
    
    LLM이 각 테이블에 대해 분석한 결과:
    - row_represents: 각 행이 무엇을 나타내는지
    - entity_identifier: 행을 고유하게 식별하는 컬럼
    """
    file_name: str = Field(
        default="",
        description="Target table/file name to analyze"
    )
    row_represents: str = Field(
        default="",
        description="Entity type each row represents (e.g., surgery, patient, lab_result)"
    )
    entity_identifier: Optional[str] = Field(
        default=None,
        description="Column name that uniquely identifies each row (null if composite key)"
    )
    # confidence, reasoning은 LLMAnalysisBase에서 상속


class EntityIdentificationResponse(BaseModel):
    """[entity_identification] LLM 응답 전체"""
    tables: List[TableEntityResult] = []


class EntityIdentificationResult(PhaseResultBase):
    """[entity_identification] Entity Identification 최종 결과"""
    total_tables: int = 0                       # 분석 대상 테이블 수
    tables_analyzed: int = 0                    # 실제 분석된 수
    entities_identified: int = 0                # row_represents가 식별된 수
    identifiers_found: int = 0                  # entity_identifier가 있는 수
    high_confidence: int = 0                    # conf >= threshold
    low_confidence: int = 0                     # conf < threshold
    # llm_calls, started_at, completed_at은 PhaseResultBase에서 상속


# Backward compatibility alias
Phase8Result = EntityIdentificationResult


# =============================================================================
# [relationship_inference] node 모델
# =============================================================================

class TableRelationship(LLMAnalysisBase):
    """
    [relationship_inference] 테이블 간 관계
    
    LLM이 분석한 FK 관계 정보
    """
    source_table: str = Field(
        default="",
        description="Source table file name"
    )
    target_table: str = Field(
        default="",
        description="Target table file name"
    )
    source_column: str = Field(
        default="",
        description="Foreign key column in source table"
    )
    target_column: str = Field(
        default="",
        description="Primary key column in target table"
    )
    relationship_type: str = Field(
        default="foreign_key",
        description="Relationship type: foreign_key or shared_identifier"
    )
    cardinality: str = Field(
        default="1:N",
        description="Relationship cardinality: 1:1, 1:N, or N:1"
    )
    # confidence, reasoning은 LLMAnalysisBase에서 상속


class RelationshipInferenceResponse(BaseModel):
    """[relationship_inference] LLM 응답"""
    relationships: List[TableRelationship] = []


class RelationshipInferenceResult(Neo4jPhaseResultBase):
    """[relationship_inference] Relationship Inference + Neo4j 최종 결과"""
    # FK 관계
    relationships_found: int = 0
    relationships_high_conf: int = 0
    
    # Neo4j 통계
    row_entity_nodes: int = 0
    concept_category_nodes: int = 0
    parameter_nodes: int = 0
    edges_links_to: int = 0
    edges_has_concept: int = 0
    edges_contains: int = 0
    edges_has_column: int = 0
    # llm_calls, started_at, completed_at, neo4j_synced는 Neo4jPhaseResultBase에서 상속


# Backward compatibility alias
Phase9Result = RelationshipInferenceResult


# =============================================================================
# [ontology_enhancement] node 모델
# =============================================================================

class SubCategoryResult(LLMAnalysisBase):
    """
    [ontology_enhancement] Task 1: 서브카테고리 결과
    
    ConceptCategory를 세분화한 결과
    """
    parent_category: str = Field(
        default="",
        description="Parent ConceptCategory name (e.g., Vitals)"
    )
    subcategory_name: str = Field(
        default="",
        description="Refined subcategory name (e.g., Cardiovascular)"
    )
    parameters: List[str] = Field(
        default_factory=list,
        description="List of parameter keys belonging to this subcategory"
    )
    # confidence, reasoning은 LLMAnalysisBase에서 상속


class ConceptHierarchyResponse(BaseModel):
    """[ontology_enhancement] Task 1: LLM 응답 - Concept Hierarchy"""
    subcategories: List[SubCategoryResult] = []


class SemanticEdge(LLMAnalysisBase):
    """
    [ontology_enhancement] Task 2: 의미 관계
    
    Parameter 간 의미적 관계
    """
    source_parameter: str = Field(
        default="",
        description="Source parameter key"
    )
    target_parameter: str = Field(
        default="",
        description="Target parameter key"
    )
    relationship_type: str = Field(
        default="",
        description="Relationship type: DERIVED_FROM, RELATED_TO, or OPPOSITE_OF"
    )
    # confidence, reasoning은 LLMAnalysisBase에서 상속


class SemanticEdgesResponse(BaseModel):
    """[ontology_enhancement] Task 2: LLM 응답 - Semantic Edges"""
    edges: List[SemanticEdge] = []


class MedicalTermMapping(LLMAnalysisBase):
    """
    [ontology_enhancement] Task 3: 의학 용어 매핑
    
    표준 의학 용어 시스템(SNOMED-CT, LOINC, ICD-10)으로 매핑
    """
    parameter_key: str = Field(
        default="",
        description="Parameter key to map"
    )
    snomed_code: Optional[str] = Field(
        default=None,
        description="SNOMED-CT code (e.g., 364075005)"
    )
    snomed_name: Optional[str] = Field(
        default=None,
        description="SNOMED-CT standard term name"
    )
    loinc_code: Optional[str] = Field(
        default=None,
        description="LOINC code (e.g., 8867-4)"
    )
    loinc_name: Optional[str] = Field(
        default=None,
        description="LOINC standard term name"
    )
    icd10_code: Optional[str] = Field(
        default=None,
        description="ICD-10 code (if applicable)"
    )
    icd10_name: Optional[str] = Field(
        default=None,
        description="ICD-10 term name"
    )
    # confidence, reasoning은 LLMAnalysisBase에서 상속


class MedicalTermResponse(BaseModel):
    """[ontology_enhancement] Task 3: LLM 응답 - Medical Term Mapping"""
    mappings: List[MedicalTermMapping] = []


class CrossTableSemantic(LLMAnalysisBase):
    """
    [ontology_enhancement] Task 4: 테이블 간 시맨틱 관계
    
    다른 테이블에 있지만 의미적으로 연관된 컬럼
    """
    source_table: str = Field(
        default="",
        description="Source table file name"
    )
    source_column: str = Field(
        default="",
        description="Column name in source table"
    )
    target_table: str = Field(
        default="",
        description="Target table file name"
    )
    target_column: str = Field(
        default="",
        description="Column name in target table"
    )
    relationship_type: str = Field(
        default="SEMANTICALLY_SIMILAR",
        description="Relationship type: SEMANTICALLY_SIMILAR or SAME_CONCEPT"
    )
    # confidence, reasoning은 LLMAnalysisBase에서 상속


class CrossTableResponse(BaseModel):
    """[ontology_enhancement] Task 4: LLM 응답 - Cross Table Semantics"""
    semantics: List[CrossTableSemantic] = []


class OntologyEnhancementResult(Neo4jPhaseResultBase):
    """[ontology_enhancement] Ontology Enhancement 최종 결과"""
    # Task 1: Concept Hierarchy
    subcategories_created: int = 0
    subcategories_high_conf: int = 0
    
    # Task 2: Semantic Edges
    semantic_edges_created: int = 0
    derived_from_edges: int = 0
    related_to_edges: int = 0
    
    # Task 3: Medical Terms
    medical_terms_mapped: int = 0
    snomed_mappings: int = 0
    loinc_mappings: int = 0
    
    # Task 4: Cross Table
    cross_table_semantics: int = 0
    
    # Neo4j 통계
    neo4j_subcategory_nodes: int = 0
    neo4j_medical_term_nodes: int = 0
    neo4j_semantic_edges: int = 0
    neo4j_cross_table_edges: int = 0
    # llm_calls, started_at, completed_at, neo4j_synced는 Neo4jPhaseResultBase에서 상속


# Backward compatibility alias
Phase10Result = OntologyEnhancementResult
