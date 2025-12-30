# src/agents/models/llm_responses.py
"""
LLM 응답 구조화를 위한 Pydantic 모델들

모든 LLM 호출의 응답을 타입 안전하게 관리합니다.
- 자동 타입 검증
- 누락 필드 기본값
- IDE 자동완성 지원
- 디버깅 용이
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


# =============================================================================
# 헬퍼 함수: LLM 응답 → Pydantic 모델 변환
# =============================================================================

def parse_llm_response(response: Dict[str, Any], model_class: type) -> BaseModel:
    """
    LLM의 dict 응답을 Pydantic 모델로 변환
    
    Args:
        response: LLM 응답 (dict)
        model_class: 변환할 Pydantic 모델 클래스
    
    Returns:
        검증된 Pydantic 모델 인스턴스
    
    Raises:
        ValidationError: 응답이 모델 스키마와 맞지 않을 때
    """
    try:
        return model_class(**response)
    except Exception as e:
        print(f"⚠️ [LLM Response Parsing] Validation failed: {e}")
        print(f"   Response: {response}")
        # 기본값으로 모델 생성
        return model_class()


# =============================================================================
# Phase 4: File Classification 모델
# =============================================================================

class FileClassificationItem(BaseModel):
    """Phase 4: 개별 파일 분류 결과"""
    file_name: str                        # 파일명
    is_metadata: bool                     # True=메타데이터, False=데이터
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str = ""                   # 판단 근거


class FileClassificationResponse(BaseModel):
    """Phase 4: LLM 응답 전체"""
    classifications: List[FileClassificationItem] = []


class FileClassificationResult(BaseModel):
    """Phase 4: 파일 분류 최종 결과"""
    total_files: int = 0
    metadata_files: List[str] = []        # is_metadata=true 파일 경로
    data_files: List[str] = []            # is_metadata=false 파일 경로
    classifications: Dict[str, Dict[str, Any]] = {}  # 파일별 상세 분류 정보
    llm_calls: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# =============================================================================
# Phase 5: MetaData Semantic 모델
# =============================================================================

class ColumnRoleMapping(BaseModel):
    """Phase 5: 컬럼 역할 매핑 결과"""
    key_column: str                       # 파라미터 이름/코드 컬럼
    desc_column: Optional[str] = None     # 설명 컬럼
    unit_column: Optional[str] = None     # 단위 컬럼
    extra_columns: Dict[str, str] = {}    # 추가 컬럼들 {역할: 컬럼명}
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str = ""


class ColumnRoleMappingResponse(BaseModel):
    """Phase 5: 컬럼 역할 LLM 응답"""
    key_column: str
    desc_column: Optional[str] = None
    unit_column: Optional[str] = None
    extra_columns: Dict[str, str] = {}
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str = ""


class DataDictionaryEntry(BaseModel):
    """Phase 5: data_dictionary 테이블에 저장될 엔트리"""
    source_file_id: str
    source_file_name: str
    parameter_key: str
    parameter_desc: Optional[str] = None
    parameter_unit: Optional[str] = None
    extra_info: Dict[str, Any] = {}
    llm_confidence: Optional[float] = None


class MetadataSemanticResult(BaseModel):
    """Phase 5: 메타데이터 시맨틱 분석 최종 결과"""
    total_metadata_files: int = 0
    processed_files: int = 0
    total_entries_extracted: int = 0
    entries_by_file: Dict[str, int] = {}
    llm_calls: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# =============================================================================
# Phase 6: Data Semantic Analysis 모델
# =============================================================================

class ColumnSemanticResult(BaseModel):
    """
    Phase 6: 데이터 파일 컬럼의 의미론적 분석 결과
    
    LLM이 컬럼 이름, 통계, data_dictionary를 참조하여 분석
    """
    original_name: str                        # 원본 컬럼명 (매칭용 키)
    semantic_name: str                        # 표준화된 이름 (예: "Heart Rate")
    unit: Optional[str] = None                # 측정 단위 (예: "bpm", "mmHg")
    description: Optional[str] = None         # 상세 설명
    concept_category: Optional[str] = None    # 개념 카테고리 (예: "Vital Signs")
    dict_entry_key: Optional[str] = None      # data_dictionary의 정확한 parameter_key (없으면 null)
    match_confidence: float = Field(default=0.0, ge=0.0, le=1.0)  # dictionary 매칭 확신도
    reasoning: Optional[str] = None           # 판단 근거


class DataSemanticResponse(BaseModel):
    """Phase 6: 파일별 LLM 응답"""
    columns: List[ColumnSemanticResult] = []
    file_summary: Optional[str] = None        # 파일 전체 요약 (선택)


class DataSemanticResult(BaseModel):
    """Phase 6: 데이터 시맨틱 분석 최종 결과"""
    total_data_files: int = 0
    processed_files: int = 0
    total_columns_analyzed: int = 0
    columns_matched: int = 0                  # dict_entry_id 매칭 성공
    columns_not_found: int = 0                # dict에 없는 key 반환
    columns_null_from_llm: int = 0            # LLM이 null 반환
    columns_by_file: Dict[str, int] = {}
    batches_processed: int = 0                # 배치 분할 횟수
    llm_calls: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# =============================================================================
# Phase 8: Entity Identification 모델
# =============================================================================

class TableEntityResult(BaseModel):
    """
    Phase 8: 단일 테이블의 Entity 분석 결과
    
    LLM이 각 테이블에 대해 분석한 결과:
    - row_represents: 각 행이 무엇을 나타내는지
    - entity_identifier: 행을 고유하게 식별하는 컬럼
    """
    file_name: str                              # 매칭용 키
    row_represents: str                         # "surgery", "patient", "lab_result"
    entity_identifier: Optional[str] = None     # "caseid" or null (복합키인 경우)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class EntityIdentificationResponse(BaseModel):
    """Phase 8: LLM 응답 전체"""
    tables: List[TableEntityResult] = []


class Phase8Result(BaseModel):
    """Phase 8: Entity Identification 최종 결과"""
    total_tables: int = 0                       # 분석 대상 테이블 수
    tables_analyzed: int = 0                    # 실제 분석된 수
    entities_identified: int = 0                # row_represents가 식별된 수
    identifiers_found: int = 0                  # entity_identifier가 있는 수
    high_confidence: int = 0                    # conf >= threshold
    low_confidence: int = 0                     # conf < threshold
    llm_calls: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# =============================================================================
# Phase 9: Relationship Inference 모델
# =============================================================================

class TableRelationship(BaseModel):
    """
    Phase 9: 테이블 간 관계
    
    LLM이 분석한 FK 관계 정보
    """
    source_table: str                           # source 테이블 파일명
    target_table: str                           # target 테이블 파일명
    source_column: str                          # source의 FK 컬럼
    target_column: str                          # target의 PK 컬럼
    relationship_type: str = "foreign_key"      # "foreign_key", "shared_identifier"
    cardinality: str = "1:N"                    # "1:1", "1:N", "N:1"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class RelationshipInferenceResponse(BaseModel):
    """Phase 9: LLM 응답"""
    relationships: List[TableRelationship] = []


class Phase9Result(BaseModel):
    """Phase 9: Relationship Inference + Neo4j 최종 결과"""
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
    
    # 메타
    llm_calls: int = 0
    neo4j_synced: bool = False
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# =============================================================================
# Phase 10: Ontology Enhancement 모델
# =============================================================================

class SubCategoryResult(BaseModel):
    """
    Phase 10 Task 1: 서브카테고리 결과
    
    ConceptCategory를 세분화한 결과
    """
    parent_category: str                        # "Vitals"
    subcategory_name: str                       # "Cardiovascular"
    parameters: List[str] = []                  # ["hr", "sbp", "dbp"]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class ConceptHierarchyResponse(BaseModel):
    """Phase 10 Task 1: LLM 응답 - Concept Hierarchy"""
    subcategories: List[SubCategoryResult] = []


class SemanticEdge(BaseModel):
    """
    Phase 10 Task 2: 의미 관계
    
    Parameter 간 의미적 관계
    """
    source_parameter: str                       # "bmi"
    target_parameter: str                       # "height"
    relationship_type: str                      # "DERIVED_FROM", "RELATED_TO", "OPPOSITE_OF"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class SemanticEdgesResponse(BaseModel):
    """Phase 10 Task 2: LLM 응답 - Semantic Edges"""
    edges: List[SemanticEdge] = []


class MedicalTermMapping(BaseModel):
    """
    Phase 10 Task 3: 의학 용어 매핑
    
    표준 의학 용어 시스템(SNOMED-CT, LOINC, ICD-10)으로 매핑
    """
    parameter_key: str                          # "hr"
    snomed_code: Optional[str] = None           # "364075005"
    snomed_name: Optional[str] = None           # "Heart rate"
    loinc_code: Optional[str] = None            # "8867-4"
    loinc_name: Optional[str] = None            # "Heart rate"
    icd10_code: Optional[str] = None            # 해당되는 경우
    icd10_name: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class MedicalTermResponse(BaseModel):
    """Phase 10 Task 3: LLM 응답 - Medical Term Mapping"""
    mappings: List[MedicalTermMapping] = []


class CrossTableSemantic(BaseModel):
    """
    Phase 10 Task 4: 테이블 간 시맨틱 관계
    
    다른 테이블에 있지만 의미적으로 연관된 컬럼
    """
    source_table: str                           # "clinical_data.csv"
    source_column: str                          # "preop_hb"
    target_table: str                           # "lab_data.csv"
    target_column: str                          # "value" (where name='Hb')
    relationship_type: str = "SEMANTICALLY_SIMILAR"  # "SEMANTICALLY_SIMILAR", "SAME_CONCEPT"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class CrossTableResponse(BaseModel):
    """Phase 10 Task 4: LLM 응답 - Cross Table Semantics"""
    semantics: List[CrossTableSemantic] = []


class Phase10Result(BaseModel):
    """Phase 10: Ontology Enhancement 최종 결과"""
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
    
    # 메타
    llm_calls: int = 0
    neo4j_synced: bool = False
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
