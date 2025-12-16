import operator
from typing import Annotated, TypedDict, List, Dict, Any, Optional, Literal

class ColumnSchema(TypedDict):
    """
    개별 컬럼/채널에 대한 심층 분석 결과 구조체
    """
    original_name: str          # 원본 컬럼명 (예: 'bp_sys')
    inferred_name: str          # 추론된 논리명 (예: 'Systolic Blood Pressure')
    standard_concept_id: Optional[str] # 표준 코드 (예: LOINC '8480-6', OMOP ID) - 나중을 위해 준비
    description: str            # 컬럼 설명
    data_type: str              # 데이터 타입 (Numerical, Categorical, String, Date)
    is_pii: bool                # 개인식별정보(PII) 여부
    confidence: float           # AI의 추론 확신도 (0.0 ~ 1.0)

class AnchorInfo(TypedDict):
    """
    환자 식별자(Anchor) 및 시계열 정보 확정 구조체
    """
    status: str                 # 'FOUND', 'MISSING', 'CONFIRMED'
    column_name: Optional[str]  # 식별된 컬럼명 (없으면 None)
    is_time_series: bool        # 시계열 데이터 여부
    reasoning: str              # 판단 근거
    mapped_to_master: Optional[str] # [NEW] 프로젝트 표준 Anchor 이름 (예: 'patient_id')

class ProjectContext(TypedDict):
    """
    [NEW] 여러 파일 간 공유되는 '프로젝트 레벨'의 지식
    """
    master_anchor_name: Optional[str]   # 프로젝트 표준 ID 컬럼명 (예: 'patient_id')
    known_aliases: List[str]            # ID로 식별된 컬럼명들 (예: ['pid', 'subj_no'])
    example_id_values: List[str]        # 실제 ID 값 샘플 (매칭 검증용, 예: ['P001', 'P002'])


class Relationship(TypedDict):
    """
    테이블 간 관계 (Foreign Key 등)
    """
    source_table: str                   # 예: 'lab_data'
    target_table: str                   # 예: 'clinical_data'
    source_column: str                  # 예: 'caseid'
    target_column: str                  # 예: 'caseid'
    relation_type: Literal["1:1", "1:N", "N:1", "M:N"]
    confidence: float                   # LLM 확신도
    description: str                    # 관계 설명
    llm_inferred: bool                  # LLM이 추론했는지 여부
    human_verified: Optional[bool]      # Human이 검증했는지
    verified_at: Optional[str]          # 검증 시간


class EntityHierarchy(TypedDict):
    """
    Entity 계층 구조 (Patient > Case > Measurement)
    """
    level: int                          # 1(최상위), 2, 3...
    entity_name: str                    # 'Patient', 'Case', 'Laboratory' 등
    anchor_column: str                  # 이 레벨의 식별자 컬럼명
    mapping_table: Optional[str]        # 상위 레벨로 매핑해주는 허브 테이블
    confidence: float                   # LLM 확신도


class OntologyContext(TypedDict):
    """
    프로젝트 전체의 온톨로지 지식 그래프
    """
    # 1. 용어 사전 (메타데이터 파일에서 추출)
    definitions: Dict[str, str]         # {'caseid': 'Case ID; Random number...', ...}
    
    # 2. 테이블 간 관계
    relationships: List[Relationship]
    
    # 3. Entity 계층 구조
    hierarchy: List[EntityHierarchy]
    
    # 4. 파일 태그 (메타데이터 vs 데이터 구분)
    file_tags: Dict[str, Dict[str, Any]]  # {file_path: {"type": "metadata", ...}}


class AgentState(TypedDict):
    """
    [핵심] 에이전트 워크플로우 전체를 관통하는 상태 객체
    """
    
    # --- 1. 입력 데이터 (Input Context) ---
    file_path: str              # 처리 중인 파일 경로
    file_type: Optional[str]    # 'tabular', 'signal', 'image' 등
    
    # --- 2. 기술적 메타데이터 (From Processors) ---
    # Processor가 추출한 Raw 데이터 (헤더, 샘플, 후보 Anchor 등)
    raw_metadata: Dict[str, Any] 
    
    # --- 3. 의미론적 분석 결과 (From Semantic Reasoner) ---
    # AI가 분석하고 정리한 최종 스키마 정보
    finalized_anchor: Optional[AnchorInfo] 
    finalized_schema: List[ColumnSchema]
    
    # --- 4. Human-in-the-Loop (사람 개입 제어) ---
    needs_human_review: bool    # True면 워크플로우가 일시 정지(Interrupt) 됨
    human_question: str         # 사용자에게 물어볼 구체적인 질문 내용
    human_feedback: Optional[str] # 사용자가 입력한 답변 (피드백)
    
    # --- 5. 시스템 로그 (History) ---
    # Annotated[..., operator.add]를 사용하면 
    # 각 노드에서 return {"logs": ["msg"]} 할 때 리스트가 계속 이어 붙습니다.
    logs: Annotated[List[str], operator.add]
    
    # --- 6. 온톨로지 컨텍스트 (Global Knowledge Graph) ---
    ontology_context: OntologyContext   # 전역 온톨로지 지식
    skip_indexing: bool                 # 메타데이터 파일인 경우 True
    
    # --- 7. 실행 컨텍스트 (Optional) ---
    retry_count: int            # 분석 재시도 횟수
    error_message: Optional[str] # 에러 발생 시 기록
    project_context: ProjectContext  # (기존 유지, 호환성)
