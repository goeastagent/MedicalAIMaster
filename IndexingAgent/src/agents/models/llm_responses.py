# src/agents/models/llm_responses.py
"""
LLM 응답 구조화를 위한 Pydantic 모델들

모든 LLM 호출의 응답을 타입 안전하게 관리합니다.
- 자동 타입 검증
- 누락 필드 기본값
- IDE 자동완성 지원
- 디버깅 용이
"""

from enum import Enum
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, validator


# =============================================================================
# Enum 정의
# =============================================================================

class FeedbackAction(str, Enum):
    """
    사용자 피드백 액션 타입 (단순화)
    
    - SKIP: 파일 제외 (처리하지 않음)
    - ACCEPT: LLM 제안 수락 또는 사용자가 명시한 entity identifier 사용
    - CLARIFY: 추가 정보 제공 (LLM이 재분석에 활용)
    """
    SKIP = "skip"
    ACCEPT = "accept"      # confirm + use_column + use_filename_as_id 통합
    CLARIFY = "clarify"    # provide_info 대체


class IdentifierSource(str, Enum):
    """Entity Identifier 값의 출처"""
    COLUMN = "column"           # 기존 컬럼에서
    FILENAME = "filename"       # 파일명에서 추출
    INFERRED = "inferred"       # LLM이 추론 (FK 등)
    USER_SPECIFIED = "user"     # 사용자가 직접 지정


class IdentificationStatus(str, Enum):
    """Entity 식별 상태"""
    FOUND = "FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    MISSING = "MISSING"
    ERROR = "ERROR"
    CONFIRMED = "CONFIRMED"
    FK_LINK = "FK_LINK"
    INDIRECT_LINK = "INDIRECT_LINK"


class ColumnType(str, Enum):
    """컬럼 타입"""
    CATEGORICAL = "categorical"
    CONTINUOUS = "continuous"
    IDENTIFIER = "identifier"
    TIMESTAMP = "timestamp"
    TEXT = "text"


class EntityRelationType(str, Enum):
    """Entity 관계 타입 (계층 구조에서)"""
    SELF = "self"           # 현재 테이블의 행을 식별하는 컬럼
    PARENT = "parent"       # 상위 entity (1:N 관계의 1 쪽)
    CHILD = "child"         # 하위 entity (1:N 관계의 N 쪽)
    SIBLING = "sibling"     # 동일 레벨의 다른 entity
    REFERENCE = "reference" # 참조 관계 (lookup 등)


# =============================================================================
# LLM 응답 모델들
# =============================================================================

class FeedbackParseResult(BaseModel):
    """
    사용자 피드백 파싱 결과
    
    LLM이 컨텍스트(파일명, 컬럼, 피드백)를 종합하여:
    - action: 어떤 행동을 할지
    - identifier_column: 어떤 컬럼을 identifier로 쓸지 (ACCEPT 시)
    - identifier_source: identifier 값의 출처
    - identifier_value: 파일명에서 추출한 경우 실제 값
    """
    action: FeedbackAction = FeedbackAction.CLARIFY
    
    # Entity Identifier 관련 (action=ACCEPT 시 사용)
    identifier_column: Optional[str] = None       # identifier로 사용할 컬럼명
    identifier_source: Optional[IdentifierSource] = None  # 값의 출처
    identifier_value: Optional[Any] = None        # filename에서 추출한 값 등
    
    # 공통
    reasoning: str = ""
    user_intent: str = ""                     # 사용자 의도 요약 (한글)
    clarification: Optional[str] = None       # CLARIFY 시 추가 정보
    
    class Config:
        use_enum_values = True


class ColumnSchemaResult(BaseModel):
    """analyze_columns_with_llm의 개별 컬럼 분석 결과"""
    original_name: str
    inferred_name: Optional[str] = None
    full_name: Optional[str] = None
    description: str = ""
    description_kr: str = ""
    data_type: str = "VARCHAR"
    semantic_type: Optional[str] = None
    column_type: Optional[ColumnType] = None
    unit: Optional[str] = None
    typical_range: Optional[str] = None
    is_pii: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    value_mappings: Optional[Dict[str, str]] = None
    
    # 계층 관계 (analyze_intra_table_hierarchy에서 추가)
    parent_column: Optional[str] = None
    cardinality: Optional[str] = None
    hierarchy_type: Optional[str] = None
    
    # 분석 컨텍스트 (추적용)
    analysis_context: Optional[str] = None
    
    class Config:
        use_enum_values = True


class ColumnAnalysisResponse(BaseModel):
    """analyze_columns_with_llm 전체 응답"""
    columns: List[ColumnSchemaResult] = []


# =============================================================================
# Entity Understanding 모델 (NEW - Primary Key 대신 Entity 관계 중심)
# =============================================================================

class LinkableColumnInfo(BaseModel):
    """
    다른 테이블과 연결 가능한 컬럼 정보
    
    예: caseid가 surgery를 나타내고, lab_data와 연결 가능
    """
    column_name: str                              # 컬럼명 (예: "caseid")
    represents_entity: str                        # 이 컬럼이 나타내는 entity (예: "surgery")
    represents_entity_kr: str = ""                # 한글 (예: "수술")
    relation_type: EntityRelationType = EntityRelationType.REFERENCE  # 관계 유형
    cardinality: str = "N:1"                      # "1:1", "1:N", "N:1", "N:M"
    linkable_to_tables: List[str] = []            # 연결 가능한 테이블 목록
    is_primary_identifier: bool = False           # 이 테이블의 행을 식별하는 주 컬럼인지


class EntityAnalysisResult(BaseModel):
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
    row_represents: str                           # 예: "surgery", "patient", "lab_result"
    row_represents_kr: str = ""                   # 한글 설명 (예: "수술 기록")
    
    # 해당 entity의 식별자 컬럼 (이 테이블에서 행을 유일하게 식별)
    entity_identifier: str                        # 예: "caseid"
    
    # 다른 테이블과 연결 가능한 컬럼들 (FK 역할을 할 수 있는 모든 컬럼)
    linkable_columns: List[LinkableColumnInfo] = []
    
    # 계층 관계 설명 (사용자 피드백 기반)
    hierarchy_explanation: str = ""               # 예: "한 환자가 여러 수술을 받을 수 있음"
    
    # 분석 메타데이터
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    status: str = "CONFIRMED"                     # CONFIRMED, NEEDS_REVIEW, ERROR
    needs_human_confirmation: bool = False
    
    # 사용자 피드백 (있는 경우)
    user_feedback_applied: Optional[str] = None
    
    # Signal 파일용: 파일명에서 추출한 ID 값 (예: 0001.vital → 1)
    # Tabular 파일에서는 None (각 행마다 다른 값이 있으므로)
    id_value: Optional[Any] = None
    
    class Config:
        use_enum_values = True


# =============================================================================
# Phase 1: Batch Semantic Analysis 모델
# =============================================================================

class ColumnSemanticMapping(BaseModel):
    """
    Phase 1: 단일 컬럼의 의미론적 분석 결과
    
    LLM이 컬럼명과 통계를 보고 추론한 의미 정보
    """
    original: str                         # 원본 컬럼명 (매칭용 키)
    semantic: str                         # 표준화된 이름 (예: "Heart Rate")
    unit: Optional[str] = None            # 측정 단위 (예: "bpm", "mmHg")
    concept: str = "Other"                # 개념 카테고리
    description: str = ""                 # 상세 설명
    standard_code: Optional[str] = None   # LOINC, SNOMED 코드 (있으면)
    is_pii: bool = False                  # 개인식별정보 여부
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ColumnBatchResponse(BaseModel):
    """Phase 1: 배치 컬럼 분석 LLM 응답"""
    mappings: List[ColumnSemanticMapping] = []


class FileSemanticMapping(BaseModel):
    """
    Phase 1: 파일의 의미론적 분석 결과
    
    LLM이 파일명, 컬럼 목록, 메타데이터를 보고 추론한 파일 의미
    """
    file_name: str                        # 파일명 (매칭용 키)
    semantic_type: str                    # "Signal:Physiological", "Clinical:Demographics"
    semantic_name: str                    # 표준화된 파일명/설명
    purpose: str = ""                     # 파일 목적/용도
    primary_entity: str = "unknown"       # 각 행이 나타내는 entity
    entity_identifier_column: Optional[str] = None  # entity 식별자 컬럼
    domain: str = "Medical"               # 의료 도메인
    data_quality_notes: Optional[str] = None  # 데이터 품질 관련 노트
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class FileBatchResponse(BaseModel):
    """Phase 1: 배치 파일 분석 LLM 응답"""
    files: List[FileSemanticMapping] = []


class Phase1Result(BaseModel):
    """Phase 1 전체 결과 요약"""
    # 컬럼 분석 결과
    total_columns_analyzed: int = 0
    columns_with_semantic: int = 0
    columns_high_conf: int = 0      # conf >= threshold
    columns_low_conf: int = 0       # conf < threshold
    column_batches_processed: int = 0
    
    # 파일 분석 결과
    total_files_analyzed: int = 0
    files_with_semantic: int = 0
    files_high_conf: int = 0
    files_low_conf: int = 0
    file_batches_processed: int = 0
    
    # Human Review 통계
    total_review_requests: int = 0      # 리뷰 요청 횟수
    total_reanalyzes: int = 0           # 재분석 횟수
    batches_force_accepted: int = 0     # max_retries로 강제 수락된 배치
    
    # 비용/성능
    total_llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    
    # 시간
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# =============================================================================
# Phase 1: Human Review 모델
# =============================================================================

class ColumnCorrection(BaseModel):
    """개별 컬럼에 대한 Human 수정 지시"""
    original_name: str                        # 수정할 컬럼명
    correct_semantic: Optional[str] = None    # 올바른 semantic name
    correct_unit: Optional[str] = None        # 올바른 단위
    correct_concept: Optional[str] = None     # 올바른 concept category
    hint: Optional[str] = None                # LLM에게 전달할 힌트
    # 예: "이 컬럼은 마취 시작 시간이야"


class FileCorrection(BaseModel):
    """개별 파일에 대한 Human 수정 지시"""
    file_name: str                                    # 수정할 파일명
    correct_semantic_type: Optional[str] = None       # 올바른 semantic type
    correct_semantic_name: Optional[str] = None       # 올바른 이름
    correct_primary_entity: Optional[str] = None      # 올바른 primary entity
    hint: Optional[str] = None                        # LLM에게 전달할 힌트


class Phase1HumanFeedback(BaseModel):
    """
    Human이 제공하는 구조화된 피드백
    
    interrupt() 후 Human이 반환하는 JSON 형식
    """
    action: Literal["accept", "correct", "skip"]
    # accept: 현재 결과 그대로 수락
    # correct: 수정 사항 반영 후 재분석
    # skip: 이 배치 스킵 (DB에 저장 안 함)
    
    # 수정 사항 (action == "correct"인 경우)
    column_corrections: List[ColumnCorrection] = []
    file_corrections: List[FileCorrection] = []
    
    # 전체 배치에 대한 추가 컨텍스트
    additional_context: Optional[str] = None
    # 예: "이 데이터셋은 마취/수술 모니터링 데이터야"
    
    domain_hints: List[str] = []
    # 예: ["Anesthesia", "Surgery", "VitalDB"]


class BatchReviewState(BaseModel):
    """
    배치별 리뷰 상태 추적
    
    각 배치의 분석 결과와 리뷰 상태를 관리
    """
    batch_type: Literal["column", "file"]
    batch_index: int
    batch_size: int
    
    # 분석 결과 통계
    avg_confidence: float = 0.0
    min_confidence: float = 0.0
    max_confidence: float = 0.0
    low_conf_count: int = 0                 # conf < threshold 개수
    low_conf_items: List[str] = []          # 낮은 confidence 항목명들
    
    # 리뷰 상태
    retry_count: int = 0
    status: Literal["analyzing", "needs_review", "accepted", "max_retries", "skipped"] = "analyzing"
    
    # 피드백 히스토리 (재분석에 사용)
    feedback_history: List[Dict[str, Any]] = []
    
    # 현재 분석 결과 (리뷰용)
    current_mappings: List[Dict[str, Any]] = []


class Phase1ReviewQueue(BaseModel):
    """Phase 1 리뷰 대기열 및 전체 상태"""
    # 현재 리뷰 중인 배치
    current_batch: Optional[BatchReviewState] = None
    
    # 완료된 배치들의 상태
    completed_batches: List[BatchReviewState] = []
    
    # 설정
    confidence_threshold: float = 0.8
    max_retries: int = 3
    
    # 전체 통계
    total_batches: int = 0
    reviewed_batches: int = 0
    accepted_batches: int = 0
    force_accepted_batches: int = 0
    skipped_batches: int = 0


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


def safe_parse_entity(response: Dict[str, Any]) -> EntityAnalysisResult:
    """
    Entity 분석 결과를 안전하게 변환
    
    LLM 응답 형식 예시:
    {
        "row_represents": "surgery",
        "row_represents_kr": "수술 기록",
        "entity_identifier": "caseid",
        "linkable_columns": [
            {"column_name": "caseid", "represents_entity": "surgery", ...},
            {"column_name": "subjectid", "represents_entity": "patient", ...}
        ],
        "hierarchy_explanation": "한 환자가 여러 수술을 받을 수 있음",
        "confidence": 0.95,
        "reasoning": "..."
    }
    """
    # 기본값 설정
    if not response:
        response = {}
    
    # linkable_columns를 LinkableColumnInfo 객체로 변환
    if "linkable_columns" in response:
        linkable_cols = []
        for col in response.get("linkable_columns", []):
            if isinstance(col, dict):
                # relation_type을 EntityRelationType으로 변환
                if "relation_type" in col and isinstance(col["relation_type"], str):
                    try:
                        col["relation_type"] = EntityRelationType(col["relation_type"])
                    except ValueError:
                        col["relation_type"] = EntityRelationType.REFERENCE
                linkable_cols.append(LinkableColumnInfo(**col))
            elif isinstance(col, LinkableColumnInfo):
                linkable_cols.append(col)
        response["linkable_columns"] = linkable_cols
    
    # confidence 범위 확인
    if "confidence" in response:
        response["confidence"] = max(0.0, min(1.0, float(response["confidence"])))
    
    return parse_llm_response(response, EntityAnalysisResult)

