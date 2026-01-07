# src/agents/state.py
"""
Agent State Definition

LangGraph 워크플로우에서 사용하는 상태 객체입니다.
LangGraph는 TypedDict를 기대하므로 TypedDict를 사용합니다.

Pydantic 스키마:
    - 모든 Pydantic 모델은 src.agents.models 패키지에서 정의됩니다.
    - AgentState의 각 필드는 Dict[str, Any]로 저장되며,
      개별 검증이 필요한 경우 models에서 스키마를 import하여 사용합니다.

10-Node Sequential Pipeline Architecture:
    - directory_catalog, file_catalog, schema_aggregation: Rule-based 메타데이터 수집
    - file_classification ~ ontology_enhancement: LLM 기반 의미 분석 및 온톨로지 구축
"""

import operator
from typing import Annotated, List, Dict, Any, Optional, Literal, TypedDict

# Pydantic 스키마는 필요한 곳에서 models 패키지에서 import하여 사용
# from src.models import ColumnSchema, EntityIdentification, ...


class AgentState(TypedDict):
    """
    에이전트 워크플로우 전체를 관통하는 상태 객체
    
    Note: LangGraph 호환성을 위해 TypedDict를 사용합니다.
    개별 필드의 타입 검증은 Pydantic 모델(models 패키지)로 수행합니다.
    
    10-Node Sequential Pipeline:
    - directory_catalog, file_catalog, schema_aggregation: Rule-based 메타데이터 수집
    - file_classification ~ ontology_enhancement: LLM 기반 분류, 의미 분석, 온톨로지 구축
    """
    
    # --- -1. Input Context ---
    input_directory: Optional[str]  # 입력 디렉토리 경로
    
    # --- 0. Dataset Context ---
    current_dataset_id: str
    current_table_name: Optional[str]
    data_catalog: Dict[str, Any]  # DataCatalog 형태
    
    # --- [directory_catalog] Result ---
    directory_catalog_result: Optional[Dict[str, Any]]  # 디렉토리 구조 분석 결과
    catalog_dir_ids: List[str]  # 생성된 dir_id 목록
    
    # --- [file_catalog] Result ---
    file_catalog_result: Optional[Dict[str, Any]]  # 파일 메타데이터 추출 결과
    catalog_file_ids: List[str]  # 처리된 모든 파일의 file_id (UUID 문자열)
    
    # --- [file_grouping_prep] Result --- NEW!
    grouping_prep_result: Optional[Dict[str, Any]]  # 그룹핑 준비 결과 요약
    directories_for_grouping: List[Dict[str, Any]]  # LLM 입력용 디렉토리 정보
    
    # --- [schema_aggregation] Result ---
    schema_aggregation_result: Optional[Dict[str, Any]]  # 스키마 집계 결과
    unique_columns: List[Dict[str, Any]]  # 유니크 컬럼 리스트
    unique_files: List[Dict[str, Any]]  # 유니크 파일 리스트
    column_batches: List[List[Dict[str, Any]]]  # 컬럼 LLM 배치
    file_batches: List[List[Dict[str, Any]]]  # 파일 LLM 배치
    
    # --- [file_grouping] Result --- NEW!
    file_grouping_result: Optional[Dict[str, Any]]  # 그룹핑 결과 요약
    file_groups: List[Dict[str, Any]]  # 생성된 그룹 정보
    
    # --- [file_classification] Result ---
    file_classification_result: Optional[Dict[str, Any]]  # 파일 분류 결과
    metadata_files: List[str]  # is_metadata=true 파일 경로 목록
    data_files: List[str]  # is_metadata=false 파일 경로 목록
    
    # --- [metadata_semantic] Result ---
    metadata_semantic_result: Optional[Dict[str, Any]]  # 메타데이터 분석 결과
    data_dictionary_entries: List[Dict[str, Any]]  # 추출된 key-desc-unit 엔트리들
    
    # --- [data_semantic] Result ---
    data_semantic_result: Optional[Dict[str, Any]]  # 데이터 시맨틱 분석 결과
    data_semantic_entries: List[Dict[str, Any]]  # LLM이 분석한 데이터 컬럼 의미 정보
    
    # --- [directory_pattern] Result ---
    directory_pattern_result: Optional[Dict[str, Any]]  # 디렉토리 패턴 분석 결과
    directory_patterns: Dict[str, Dict]  # {dir_id: pattern_info}
    
    # --- [entity_identification] Result ---
    entity_identification_result: Optional[Dict[str, Any]]  # Entity 식별 결과
    table_entity_results: List[Dict[str, Any]]  # TableEntityResult 목록
    
    # --- [relationship_inference] Result ---
    relationship_inference_result: Optional[Dict[str, Any]]  # 관계 추론 결과
    table_relationships: List[Dict[str, Any]]  # TableRelationship 목록
    
    # --- [ontology_enhancement] Result ---
    ontology_enhancement_result: Optional[Dict[str, Any]]  # 온톨로지 강화 결과
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
