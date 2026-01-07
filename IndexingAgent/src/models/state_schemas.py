# src/agents/models/state_schemas.py
"""
상태(State) 관련 Pydantic 스키마

AgentState에서 사용되는 복잡한 필드들의 타입 정의:
- ColumnSchema: 컬럼/채널 분석 결과
- EntityIdentification: Entity 식별 정보
- ProjectContext: 프로젝트 레벨 지식
- Relationship: 테이블 간 관계
- EntityUnderstanding: Entity 이해 결과
- OntologyContext: 온톨로지 지식 그래프
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Column Schema
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


# =============================================================================
# Entity Identification
# =============================================================================

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


# =============================================================================
# Project Context
# =============================================================================

class ProjectContext(BaseModel):
    """여러 파일 간 공유되는 프로젝트 레벨 지식"""
    master_entity_identifier: Optional[str] = Field(None, description="프로젝트 표준 Entity 식별자 컬럼명")
    known_aliases: List[str] = Field(default_factory=list, description="ID로 식별된 컬럼명들")
    example_id_values: List[str] = Field(default_factory=list, description="실제 ID 값 샘플")


# =============================================================================
# Relationship
# =============================================================================

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
# Entity Understanding
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


# =============================================================================
# Ontology Context
# =============================================================================

class OntologyContext(BaseModel):
    """프로젝트 전체의 온톨로지 지식 그래프"""
    dataset_id: Optional[str] = Field(None)
    definitions: Dict[str, str] = Field(default_factory=dict, description="용어 사전")
    relationships: List[Dict[str, Any]] = Field(default_factory=list, description="테이블 간 관계")
    hierarchy: List[Dict[str, Any]] = Field(default_factory=list, description="Entity 계층")
    file_tags: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="파일 태그")
    column_metadata: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="컬럼 메타데이터")

