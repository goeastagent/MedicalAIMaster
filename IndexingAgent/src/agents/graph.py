"""
3-Phase Batch Workflow Architecture
====================================

Phase 0: Data Catalog (규칙 기반 메타데이터 추출)
  ┌─────────────┐
  │   START     │
  └──────┬──────┘
         │
         ▼
┌────────────────────┐
│  phase0_catalog    │  ← 모든 파일 메타데이터 추출 (DB 저장)
└────────┬───────────┘
         │
         ▼

Phase 1: Classification (전체 파일 분류)
         │
         ▼
┌────────────────────┐
│  batch_classifier  │  ← 모든 파일 분류
└────────┬───────────┘
         │
    ┌────┴────┐
    │         │
uncertain?   all ok?
    │         │
    ▼         │
┌─────────────────────┐
│classification_review│ ← Human-in-Loop
└────────┬────────────┘
         │
         └────┬────────┘
              ▼

Phase 2: Processing (메타데이터 → 데이터 순서)
              │
              ▼
┌──────────────────────┐
│ process_metadata     │ ← 메타데이터 먼저!
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ process_data_batch   │ ← 데이터 파일 처리 시작
└──────────┬───────────┘
           │
           ▼
    ┌─────────────┐
    │   loader    │  ← 현재 파일 로드
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │  analyzer   │  ← 의미 분석
    └──────┬──────┘
           │
      ┌────┴────┐
      │         │
low conf?    high conf?
      │         │
      ▼         │
┌────────────┐  │
│human_review│  │
└─────┬──────┘  │
      │         │
      └────┬────┘
           ▼
    ┌─────────────┐
    │   indexer   │  ← DB 저장
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │   advance   │  ← 다음 파일?
    └──────┬──────┘
           │
      ┌────┴────┐
      │         │
 has more?   all done?
      │         │
      ↺ loop    ▼
              ┌─────┐
              │ END │
              └─────┘
"""

from langgraph.graph import StateGraph, END
from src.agents.state import AgentState
from src.agents.nodes import (
    # Phase 0: Data Catalog
    phase0_catalog_node,
    # Phase 0.5: Schema Aggregation
    phase05_aggregation_node,
    # Phase 1: Semantic Analysis
    phase1_semantic_node,
    # Core nodes
    load_data_node,
    analyze_semantics_node,
    human_review_node,
    index_data_node,
    # Batch workflow nodes (legacy)
    batch_classifier_node,
    classification_review_node,
    process_metadata_batch_node,
    process_data_batch_node,
    advance_to_next_file_node,
    # Routing functions
    check_classification_needs_review,
    check_has_more_files,
    check_data_needs_review,
)


def build_agent(checkpointer=None):
    """
    3-Phase Batch Workflow 빌드
    
    Phase 0: 규칙 기반 메타데이터 추출 및 DB 카탈로그 저장
    Phase 1: LLM 기반 파일 분류 (메타데이터/데이터)
    Phase 2: 개별 파일 semantic 분석 및 인덱싱
    
    Args:
        checkpointer: (선택) 상태 저장용 checkpointer (예: MemorySaver())
                     Human-in-the-Loop에서 interrupt/resume을 위해 필요
    
    Returns:
        컴파일된 LangGraph 워크플로우
    """
    workflow = StateGraph(AgentState)
    
    # ==========================================================================
    # Phase 0: Data Catalog (규칙 기반 메타데이터 추출)
    # ==========================================================================
    workflow.add_node("phase0_catalog", phase0_catalog_node)
    
    # ==========================================================================
    # Phase 0.5: Schema Aggregation (유니크 컬럼 집계)
    # ==========================================================================
    workflow.add_node("phase05_aggregation", phase05_aggregation_node)
    
    # ==========================================================================
    # Phase 1: Classification (파일 분류)
    # ==========================================================================
    workflow.add_node("batch_classifier", batch_classifier_node)
    workflow.add_node("classification_review", classification_review_node)
    
    # ==========================================================================
    # Phase 2: Processing (메타데이터 → 데이터)
    # ==========================================================================
    workflow.add_node("process_metadata", process_metadata_batch_node)
    workflow.add_node("process_data_batch", process_data_batch_node)
    
    # 개별 데이터 파일 처리 노드
    workflow.add_node("loader", load_data_node)
    workflow.add_node("analyzer", analyze_semantics_node)
    workflow.add_node("human_review", human_review_node)
    workflow.add_node("indexer", index_data_node)
    workflow.add_node("advance", advance_to_next_file_node)
    
    # ==========================================================================
    # Edges: Phase 0 → Phase 0.5 → Phase 1
    # ==========================================================================
    
    # Entry Point: Phase 0
    workflow.set_entry_point("phase0_catalog")
    
    # phase0_catalog → phase05_aggregation
    workflow.add_edge("phase0_catalog", "phase05_aggregation")
    
    # phase05_aggregation → batch_classifier
    workflow.add_edge("phase05_aggregation", "batch_classifier")
    
    # batch_classifier → classification_review (불확실한 파일 있으면)
    # batch_classifier → process_metadata (모두 확실하면)
    workflow.add_conditional_edges(
        "batch_classifier",
        check_classification_needs_review,
        {
            "needs_review": "classification_review",
            "all_confident": "process_metadata"
        }
    )
    
    # classification_review → process_metadata
    # NOTE: classification_review_node가 내부에서 interrupt()를 사용하므로
    #       노드 완료 후에는 항상 process_metadata로 진행
    workflow.add_edge("classification_review", "process_metadata")
    
    # ==========================================================================
    # Edges: Phase 2
    # ==========================================================================
    
    # process_metadata → process_data_batch
    workflow.add_edge("process_metadata", "process_data_batch")
    
    # process_data_batch → loader (첫 데이터 파일 로드)
    # process_data_batch → END (데이터 파일 없으면)
    workflow.add_conditional_edges(
        "process_data_batch",
        lambda state: "has_data" if state.get("classification_result", {}).get("data_files") else "no_data",
        {
            "has_data": "loader",
            "no_data": END
        }
    )
    
    # loader → analyzer
    workflow.add_edge("loader", "analyzer")
    
    # analyzer → human_review / indexer (confidence 체크)
    workflow.add_conditional_edges(
        "analyzer",
        check_data_needs_review,
        {
            "review_required": "human_review",
            "approved": "indexer"
        }
    )
    
    # human_review → analyzer (피드백 반영)
    workflow.add_edge("human_review", "analyzer")
    
    # indexer → advance (다음 파일로)
    workflow.add_edge("indexer", "advance")
    
    # advance → loader (더 있으면) / END (완료)
    workflow.add_conditional_edges(
        "advance",
        check_has_more_files,
        {
            "has_more": "loader",
            "all_done": END
        }
    )
    
    # ==========================================================================
    # Compile with Checkpointer
    # ==========================================================================
    # NOTE: interrupt_before는 더 이상 사용하지 않음
    # 각 노드가 내부에서 interrupt()를 직접 호출하여 human input을 처리함
    # - classification_review_node: 내부 interrupt()
    # - human_review_node: 내부 interrupt() (TODO: 추후 구현)
    
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
    
    return workflow.compile(**compile_config)


# Alias for backward compatibility
build_batch_agent = build_agent


def build_phase0_only_agent(checkpointer=None):
    """
    Phase 0만 실행하는 워크플로우 빌드 (테스트용)
    
    START → phase0_catalog → END
    """
    workflow = StateGraph(AgentState)
    
    workflow.add_node("phase0_catalog", phase0_catalog_node)
    
    workflow.set_entry_point("phase0_catalog")
    workflow.add_edge("phase0_catalog", END)
    
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
    
    return workflow.compile(**compile_config)


def build_phase05_only_agent(checkpointer=None):
    """
    Phase 0 + 0.5만 실행하는 워크플로우 빌드 (테스트용)
    
    START → phase0_catalog → phase05_aggregation → END
    """
    workflow = StateGraph(AgentState)
    
    workflow.add_node("phase0_catalog", phase0_catalog_node)
    workflow.add_node("phase05_aggregation", phase05_aggregation_node)
    
    workflow.set_entry_point("phase0_catalog")
    workflow.add_edge("phase0_catalog", "phase05_aggregation")
    workflow.add_edge("phase05_aggregation", END)
    
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
    
    return workflow.compile(**compile_config)


def build_phase1_only_agent(checkpointer=None):
    """
    Phase 0 + 0.5 + 1 실행하는 워크플로우 빌드 (테스트용)
    
    START → phase0_catalog → phase05_aggregation → phase1_semantic → END
    
    Phase 1에서 LLM을 사용하여 컬럼과 파일의 의미를 분석합니다.
    """
    workflow = StateGraph(AgentState)
    
    workflow.add_node("phase0_catalog", phase0_catalog_node)
    workflow.add_node("phase05_aggregation", phase05_aggregation_node)
    workflow.add_node("phase1_semantic", phase1_semantic_node)
    
    workflow.set_entry_point("phase0_catalog")
    workflow.add_edge("phase0_catalog", "phase05_aggregation")
    workflow.add_edge("phase05_aggregation", "phase1_semantic")
    workflow.add_edge("phase1_semantic", END)
    
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
    
    return workflow.compile(**compile_config)
