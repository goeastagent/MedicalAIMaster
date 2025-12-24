# src/agents/state.py
"""
Agent State Definitions using Pydantic

2-Phase Workflow Architecture:
- Phase 1: 전체 파일 분류 (Classification)
- Phase 2: 메타데이터 → 데이터 순서로 처리

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
    anchor_decisions: List[Dict[str, Any]] = Field(default_factory=list, description="앵커 결정 기록")
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
    master_anchor: Optional[str] = Field(None, description="Master Anchor")
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


class AnchorInfo(BaseModel):
    """환자 식별자(Anchor) 및 시계열 정보"""
    status: Literal["FOUND", "MISSING", "CONFIRMED", "INDIRECT_LINK", "FK_LINK", "AMBIGUOUS", "ERROR"] = Field("MISSING")
    column_name: Optional[str] = Field(None, description="식별된 컬럼명")
    is_time_series: bool = Field(False, description="시계열 데이터 여부")
    reasoning: str = Field("", description="판단 근거")
    mapped_to_master: Optional[str] = Field(None, description="Master Anchor 이름")
    via_table: Optional[str] = Field(None, description="간접 연결 테이블 (FK 관계)")
    via_column: Optional[str] = Field(None, description="간접 연결 컬럼")
    link_type: Optional[str] = Field(None, description="연결 유형 (direct/indirect/fk)")
    fk_path: Optional[List[str]] = Field(None, description="FK 연결 경로 (예: ['lab_data.caseid', 'clinical_data.caseid', 'clinical_data.subjectid'])")
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    id_value: Optional[Any] = Field(None, description="ID 값 (Signal 파일용)")
    caseid_value: Optional[Any] = Field(None, description="Case ID 값")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid_statuses = ["FOUND", "MISSING", "CONFIRMED", "INDIRECT_LINK", "FK_LINK", "AMBIGUOUS", "ERROR"]
        if v not in valid_statuses:
            raise ValueError(f"Invalid status: {v}. Must be one of {valid_statuses}")
        return v


class ProjectContext(BaseModel):
    """여러 파일 간 공유되는 프로젝트 레벨 지식"""
    master_anchor_name: Optional[str] = Field(None, description="프로젝트 표준 ID 컬럼명")
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


class EntityHierarchy(BaseModel):
    """Entity 계층 구조 (Patient > Case > Measurement)"""
    level: int = Field(..., ge=1, le=10, description="계층 레벨")
    entity_name: str = Field(..., description="Entity 이름")
    anchor_column: str = Field(..., description="식별자 컬럼명")
    mapping_table: Optional[str] = Field(None)
    confidence: float = Field(0.5, ge=0.0, le=1.0)


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
    """
    
    # --- 0. Dataset Context ---
    current_dataset_id: str
    current_table_name: Optional[str]
    data_catalog: Dict[str, Any]  # DataCatalog 형태
    
    # --- 1. 2-Phase Workflow Context ---
    input_files: List[str]
    classification_result: Optional[Dict[str, Any]]  # ClassificationResult 형태
    processing_progress: Dict[str, Any]  # ProcessingProgress 형태
    
    # --- 2. 입력 데이터 (Current File Context) ---
    file_path: str
    file_type: Optional[str]
    
    # --- 3. 기술적 메타데이터 ---
    raw_metadata: Dict[str, Any]
    
    # --- 4. 의미론적 분석 결과 ---
    finalized_anchor: Optional[Dict[str, Any]]  # AnchorInfo 형태
    finalized_schema: List[Dict[str, Any]]  # List[ColumnSchema] 형태
    
    # --- 5. Human-in-the-Loop ---
    needs_human_review: bool
    human_question: str
    human_feedback: Optional[str]
    review_type: Optional[Literal["classification", "anchor", "schema"]]
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


# =============================================================================
# Helper Functions for Pydantic Conversion
# =============================================================================

def validate_anchor_info(data: Dict[str, Any]) -> AnchorInfo:
    """Dict를 AnchorInfo로 변환 및 검증"""
    return AnchorInfo(**data)


def validate_column_schema(data: Dict[str, Any]) -> ColumnSchema:
    """Dict를 ColumnSchema로 변환 및 검증"""
    return ColumnSchema(**data)


def validate_classification_result(data: Dict[str, Any]) -> ClassificationResult:
    """Dict를 ClassificationResult로 변환 및 검증"""
    return ClassificationResult(**data)


def validate_ontology_context(data: Dict[str, Any]) -> OntologyContext:
    """Dict를 OntologyContext로 변환 및 검증"""
    return OntologyContext(**data)
