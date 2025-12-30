# src/agents/state.py
"""
Agent State Definitions using Pydantic

10-Phase Sequential Pipeline Architecture:
- Phase 1-3: Rule-based 메타데이터 수집
- Phase 4-10: LLM 기반 의미 분석 및 온톨로지 구축

Dataset-First Architecture:
- current_dataset_id로 현재 데이터셋 식별
- data_catalog로 전역 카탈로그 참조
"""

import operator
from typing import Annotated, List, Dict, Any, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# 2-Phase Workflow Types
# =============================================================================

class FileClassification(BaseModel):
    """개별 파일의 분류 결과"""
    file_path: str = Field(..., description="파일 경로")
    filename: str = Field(..., description="파일명")
    classification: Literal["metadata", "data", "unknown"] = Field("unknown", description="분류 결과")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="분류 확신도")
    reasoning: str = Field("", description="판단 근거")
    indicators: Dict[str, Any] = Field(default_factory=dict, description="분류 지표")
    needs_review: bool = Field(False, description="Human Review 필요 여부")
    human_confirmed: bool = Field(False, description="Human이 확인했는지")


class ClassificationResult(BaseModel):
    """전체 파일 분류 결과 (Phase 1 출력)"""
    total_files: int = Field(0, description="전체 파일 수")
    metadata_files: List[str] = Field(default_factory=list, description="메타데이터 파일 경로 목록")
    data_files: List[str] = Field(default_factory=list, description="데이터 파일 경로 목록")
    uncertain_files: List[str] = Field(default_factory=list, description="불확실한 파일 목록")
    classifications: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="파일별 상세 분류 정보")


class ProcessingProgress(BaseModel):
    """처리 진행 상황 추적"""
    phase: Literal["classification", "classification_review", "metadata_processing", "data_processing", "complete"] = Field("classification")
    metadata_processed: List[str] = Field(default_factory=list, description="처리 완료된 메타데이터 파일")
    data_processed: List[str] = Field(default_factory=list, description="처리 완료된 데이터 파일")
    current_file: Optional[str] = Field(None, description="현재 처리 중인 파일")
    current_file_index: int = Field(0, description="현재 인덱스")
    total_files: int = Field(0, description="전체 파일 수")


class ConversationTurn(BaseModel):
    """Human-in-the-Loop 대화 한 턴"""
    turn_id: int = Field(..., description="대화 턴 번호")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(), description="발생 시간")
    file_path: Optional[str] = Field(None, description="관련 파일")
    review_type: str = Field("general", description="리뷰 유형")
    agent_question: str = Field("", description="에이전트 질문")
    human_response: str = Field("", description="사용자 응답")
    agent_action: str = Field("", description="에이전트 액션")
    context_summary: Optional[str] = Field(None, description="컨텍스트 요약")


class ConversationHistory(BaseModel):
    """전체 인덱싱 세션의 대화 히스토리"""
    session_id: str = Field(default_factory=lambda: f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    dataset_id: str = Field("unknown", description="데이터셋 ID")
    started_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    turns: List[Dict[str, Any]] = Field(default_factory=list, description="대화 턴 목록")
    classification_decisions: List[Dict[str, Any]] = Field(default_factory=list, description="분류 결정 기록")
    entity_decisions: List[Dict[str, Any]] = Field(default_factory=list, description="Entity 식별 결정 기록")
    user_preferences: Dict[str, Any] = Field(default_factory=dict, description="사용자 선호도")


# =============================================================================
# Dataset-First Architecture Types
# =============================================================================

class DatasetInfo(BaseModel):
    """데이터셋 메타정보"""
    dataset_id: str = Field(..., description="고유 ID")
    dataset_name: str = Field("", description="표시명")
    source_path: str = Field("", description="원본 경로")
    version: str = Field("1.0", description="버전")
    master_entity_identifier: Optional[str] = Field(None, description="Master Entity Identifier")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    indexed_at: Optional[str] = Field(None)


class TableInfo(BaseModel):
    """테이블 메타정보 (버전 관리 포함)"""
    table_id: str = Field(..., description="고유 ID")
    dataset_id: str = Field(..., description="소속 데이터셋")
    original_filename: str = Field("", description="원본 파일명")
    table_name: str = Field("", description="DB 테이블명")
    row_count: int = Field(0)
    column_count: int = Field(0)
    schema_hash: str = Field("", description="스키마 변경 감지용")
    indexed_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    version: int = Field(1, description="인덱싱 횟수")
    previous_version_id: Optional[str] = Field(None)


class DatasetOntology(BaseModel):
    """데이터셋별 독립 온톨로지"""
    dataset_id: str = Field("")
    definitions: Dict[str, str] = Field(default_factory=dict)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)
    hierarchy: List[Dict[str, Any]] = Field(default_factory=list)
    column_metadata: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    file_tags: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class DataCatalog(BaseModel):
    """전역 데이터 카탈로그"""
    version: str = Field("2.0", description="카탈로그 버전")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    datasets: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    tables: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    ontologies: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    cross_dataset_mappings: List[Dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# Schema Types
# =============================================================================

class ColumnSchema(BaseModel):
    """개별 컬럼/채널에 대한 심층 분석 결과"""
    original_name: str = Field(..., description="원본 컬럼명")
    inferred_name: str = Field("", description="추론된 논리명")
    full_name: Optional[str] = Field(None, description="전체 의료 용어")
    standard_concept_id: Optional[str] = Field(None, description="표준 코드")
    description: str = Field("", description="컬럼 설명")
    description_kr: str = Field("", description="한글 설명")
    data_type: str = Field("VARCHAR", description="데이터 타입")
    unit: Optional[str] = Field(None, description="측정 단위")
    typical_range: Optional[str] = Field(None, description="의료 정상 범위")
    is_pii: bool = Field(False, description="개인식별정보 여부")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="추론 확신도")


class EntityIdentification(BaseModel):
    """Entity 식별 정보"""
    status: Literal["FOUND", "MISSING", "CONFIRMED", "INDIRECT_LINK", "FK_LINK", "AMBIGUOUS", "ERROR"] = Field("MISSING")
    column_name: Optional[str] = Field(None, description="식별된 컬럼명")
    is_time_series: bool = Field(False, description="시계열 데이터 여부")
    reasoning: str = Field("", description="판단 근거")
    mapped_to_master: Optional[str] = Field(None, description="Master Entity Identifier")
    via_table: Optional[str] = Field(None, description="간접 연결 테이블 (FK 관계)")
    via_column: Optional[str] = Field(None, description="간접 연결 컬럼")
    link_type: Optional[str] = Field(None, description="연결 유형 (direct/indirect/fk)")
    fk_path: Optional[List[str]] = Field(None, description="FK 연결 경로")
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    row_represents: Optional[str] = Field(None, description="행이 나타내는 entity")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid_statuses = ["FOUND", "MISSING", "CONFIRMED", "INDIRECT_LINK", "FK_LINK", "AMBIGUOUS", "ERROR"]
        if v not in valid_statuses:
            raise ValueError(f"Invalid status: {v}. Must be one of {valid_statuses}")
        return v


class ProjectContext(BaseModel):
    """여러 파일 간 공유되는 프로젝트 레벨 지식"""
    master_entity_identifier: Optional[str] = Field(None, description="프로젝트 표준 Entity 식별자 컬럼명")
    known_aliases: List[str] = Field(default_factory=list, description="ID로 식별된 컬럼명들")
    example_id_values: List[str] = Field(default_factory=list, description="실제 ID 값 샘플")


class Relationship(BaseModel):
    """테이블 간 관계 (Foreign Key 등)"""
    source_table: str = Field(...)
    target_table: str = Field(...)
    source_column: str = Field(...)
    target_column: str = Field(...)
    relation_type: Literal["1:1", "1:N", "N:1", "M:N"] = Field("1:N")
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    description: str = Field("")
    llm_inferred: bool = Field(True)
    human_verified: Optional[bool] = Field(None)
    verified_at: Optional[str] = Field(None)


# =============================================================================
# Entity Understanding (NEW - Primary Key를 대체하는 개념)
# =============================================================================

class EntityUnderstanding(BaseModel):
    """
    테이블의 Entity 이해 결과
    
    "이 테이블의 Primary Key는 무엇인가?" 대신
    "이 테이블의 각 행은 무엇을 나타내고, 어떻게 다른 테이블과 연결되는가?"에 답함
    
    Example:
        clinical_data.csv:
        - row_represents: "surgery"
        - row_represents_kr: "수술 기록"
        - entity_identifier: "caseid"
        - linkable_columns: [
            {column: "caseid", entity: "surgery", relation: "self"},
            {column: "subjectid", entity: "patient", relation: "parent"}
          ]
        - hierarchy_explanation: "한 환자(subjectid)가 여러 수술(caseid)을 받을 수 있음"
    """
    # 행이 나타내는 것
    row_represents: str = Field("unknown", description="각 행이 나타내는 entity")
    row_represents_kr: str = Field("", description="한글 설명")
    
    # Entity 식별자
    entity_identifier: str = Field("id", description="행을 식별하는 컬럼")
    
    # 연결 가능한 컬럼들
    linkable_columns: List[Dict[str, Any]] = Field(default_factory=list, description="다른 테이블과 연결 가능한 컬럼들")
    
    # 계층 설명
    hierarchy_explanation: str = Field("", description="계층 관계 설명")
    
    # 메타데이터
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = Field("")
    status: Literal["CONFIRMED", "NEEDS_REVIEW", "ERROR"] = Field("NEEDS_REVIEW")
    needs_human_confirmation: bool = Field(False)
    user_feedback_applied: Optional[str] = Field(None)


class OntologyContext(BaseModel):
    """프로젝트 전체의 온톨로지 지식 그래프"""
    dataset_id: Optional[str] = Field(None)
    definitions: Dict[str, str] = Field(default_factory=dict, description="용어 사전")
    relationships: List[Dict[str, Any]] = Field(default_factory=list, description="테이블 간 관계")
    hierarchy: List[Dict[str, Any]] = Field(default_factory=list, description="Entity 계층")
    file_tags: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="파일 태그")
    column_metadata: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="컬럼 메타데이터")


# =============================================================================
# Main Agent State (TypedDict for LangGraph compatibility)
# =============================================================================
# Note: LangGraph는 TypedDict를 기대하므로 TypedDict를 유지합니다.
# Pydantic 모델은 개별 타입 정의에 사용됩니다.

from typing import TypedDict


class AgentState(TypedDict):
    """
    에이전트 워크플로우 전체를 관통하는 상태 객체
    
    Note: LangGraph 호환성을 위해 TypedDict를 사용합니다.
    개별 필드의 타입 검증은 Pydantic 모델로 수행합니다.
    
    10-Phase Sequential Pipeline:
    - Phase 1-3: Rule-based 메타데이터 수집 (Directory, File, Aggregation)
    - Phase 4-10: LLM 기반 분류, 의미 분석, 온톨로지 구축
    """
    
    # --- -1. Input Context ---
    input_directory: Optional[str]  # 입력 디렉토리 경로
    
    # --- 0. Dataset Context ---
    current_dataset_id: str
    current_table_name: Optional[str]
    data_catalog: Dict[str, Any]  # DataCatalog 형태
    
    # --- Phase 1 Result (Directory Catalog) ---
    phase1_result: Optional[Dict[str, Any]]  # 디렉토리 구조 분석 결과
    phase1_dir_ids: List[str]  # 생성된 dir_id 목록
    
    # --- Phase 2 Result (File Catalog) ---
    phase2_result: Optional[Dict[str, Any]]  # 파일 메타데이터 추출 결과
    phase2_file_ids: List[str]  # 처리된 모든 파일의 file_id (UUID 문자열)
    
    # --- Phase 3 Result (Schema Aggregation) ---
    phase3_result: Optional[Dict[str, Any]]  # 스키마 집계 결과
    unique_columns: List[Dict[str, Any]]  # 유니크 컬럼 리스트
    unique_files: List[Dict[str, Any]]  # 유니크 파일 리스트
    column_batches: List[List[Dict[str, Any]]]  # 컬럼 LLM 배치
    file_batches: List[List[Dict[str, Any]]]  # 파일 LLM 배치
    
    # --- Phase 4 Result (File Classification) ---
    phase4_result: Optional[Dict[str, Any]]  # 파일 분류 결과
    metadata_files: List[str]  # is_metadata=true 파일 경로 목록
    data_files: List[str]  # is_metadata=false 파일 경로 목록
    
    # --- Phase 5 Result (Metadata Semantic) ---
    phase5_result: Optional[Dict[str, Any]]  # 메타데이터 분석 결과
    data_dictionary_entries: List[Dict[str, Any]]  # 추출된 key-desc-unit 엔트리들
    
    # --- Phase 6 Result (Data Semantic) ---
    phase6_result: Optional[Dict[str, Any]]  # 데이터 시맨틱 분석 결과
    data_semantic_entries: List[Dict[str, Any]]  # LLM이 분석한 데이터 컬럼 의미 정보
    
    # --- Phase 7 Result (Directory Pattern) ---
    phase7_result: Optional[Dict[str, Any]]  # 디렉토리 패턴 분석 결과
    phase7_dir_patterns: Dict[str, Dict]  # {dir_id: pattern_info}
    
    # --- Phase 8 Result (Entity Identification) ---
    phase8_result: Optional[Dict[str, Any]]  # Entity 식별 결과
    table_entity_results: List[Dict[str, Any]]  # TableEntityResult 목록
    
    # --- Phase 9 Result (Relationship Inference + Neo4j) ---
    phase9_result: Optional[Dict[str, Any]]  # 관계 추론 결과
    table_relationships: List[Dict[str, Any]]  # TableRelationship 목록
    
    # --- Phase 10 Result (Ontology Enhancement) ---
    phase10_result: Optional[Dict[str, Any]]  # 온톨로지 강화 결과
    ontology_subcategories: List[Dict[str, Any]]  # SubCategoryResult 목록
    semantic_edges: List[Dict[str, Any]]  # SemanticEdge 목록
    medical_term_mappings: List[Dict[str, Any]]  # MedicalTermMapping 목록
    cross_table_semantics: List[Dict[str, Any]]  # CrossTableSemantic 목록
    
    # --- 1. Multi-Phase Workflow Context ---
    input_files: List[str]
    classification_result: Optional[Dict[str, Any]]  # ClassificationResult 형태
    processing_progress: Dict[str, Any]  # ProcessingProgress 형태
    
    # --- 2. 입력 데이터 (Current File Context) ---
    file_path: str
    file_type: Optional[str]
    
    # --- 3. 기술적 메타데이터 ---
    raw_metadata: Dict[str, Any] 
    
    # --- 4. 의미론적 분석 결과 ---
    entity_identification: Optional[Dict[str, Any]]  # EntityIdentification 형태
    finalized_schema: List[Dict[str, Any]]  # List[ColumnSchema] 형태
    entity_understanding: Optional[Dict[str, Any]]  # EntityUnderstanding 형태
    
    # --- 5. Human-in-the-Loop ---
    needs_human_review: bool
    human_question: str
    human_feedback: Optional[str]
    review_type: Optional[Literal["classification", "entity", "schema"]]
    conversation_history: Dict[str, Any]  # ConversationHistory 형태
    
    # --- 6. 시스템 로그 ---
    logs: Annotated[List[str], operator.add]
    
    # --- 7. 온톨로지 컨텍스트 ---
    ontology_context: Dict[str, Any]  # OntologyContext 형태
    skip_indexing: bool
    
    # --- 8. 실행 컨텍스트 ---
    retry_count: int
    error_message: Optional[str]
    project_context: Dict[str, Any]  # ProjectContext 형태


