"""
2-Phase Workflow Architecture
=============================

Phase 1: Classification (전체 파일 분류)
  ┌─────────────┐
  │   START     │
  └──────┬──────┘
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

# 새로운 nodes 패키지에서 import
from src.agents.nodes import (
    # 기존 노드
    load_data_node,
    ontology_builder_node,
    analyze_semantics_node,
    human_review_node,
    index_data_node,
    # 2-Phase 새 노드
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


def build_agent(checkpointer=None, mode="batch"):
    """
    LangGraph 워크플로우 빌드
    
    Args:
        checkpointer: (선택) 상태 저장용 checkpointer (예: MemorySaver())
                     Human-in-the-Loop에서 interrupt/resume을 위해 필요
        mode: 워크플로우 모드
            - "batch": 2-Phase Workflow (권장, 여러 파일 일괄 처리)
            - "single": 기존 단일 파일 처리 워크플로우
    """
    if mode == "batch":
        return _build_batch_workflow(checkpointer)
    else:
        return _build_single_file_workflow(checkpointer)


def _build_batch_workflow(checkpointer=None):
    """
    [NEW] 2-Phase Batch Workflow
    
    메타데이터를 먼저 처리하여 온톨로지를 구축한 후,
    데이터 파일들을 처리합니다.
    """
    workflow = StateGraph(AgentState)
    
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
    
    # 개별 데이터 파일 처리 노드 (기존 로직 재사용)
    workflow.add_node("loader", load_data_node)
    workflow.add_node("analyzer", analyze_semantics_node)
    workflow.add_node("human_review", human_review_node)
    workflow.add_node("indexer", index_data_node)
    workflow.add_node("advance", advance_to_next_file_node)
    
    # ==========================================================================
    # Edges: Phase 1
    # ==========================================================================
    
    # Entry Point
    workflow.set_entry_point("batch_classifier")
    
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
    
    # classification_review → process_metadata (확정 후)
    # classification_review → classification_review (계속 질문 - 자체 루프는 state로 처리)
    workflow.add_conditional_edges(
        "classification_review",
        lambda state: "continue" if not state.get("needs_human_review") else "wait",
        {
            "continue": "process_metadata",
            "wait": "classification_review"  # Human Review 대기 (interrupt로 처리)
        }
    )
    
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
    # Compile with Interrupt Points
    # ==========================================================================
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
        # Human-in-Loop 지점들
        compile_config["interrupt_before"] = [
            "classification_review",  # 분류 확인
            "human_review"           # 데이터 분석 확인
        ]
    
    return workflow.compile(**compile_config)


def _build_single_file_workflow(checkpointer=None):
    """
    [LEGACY] 기존 단일 파일 처리 워크플로우
    
    호환성을 위해 유지합니다.
    """
    workflow = StateGraph(AgentState)

    # 노드 등록
    workflow.add_node("loader", load_data_node)
    workflow.add_node("ontology_builder", ontology_builder_node)
    workflow.add_node("analyzer", analyze_semantics_node)
    workflow.add_node("human_review", human_review_node)
    workflow.add_node("indexer", index_data_node)

    # 엣지 연결
    workflow.set_entry_point("loader")
    workflow.add_edge("loader", "ontology_builder")
    
    workflow.add_conditional_edges(
        "ontology_builder",
        lambda state: "skip" if state.get("skip_indexing") else "continue",
        {
            "skip": END,
            "continue": "analyzer"
        }
    )

    workflow.add_conditional_edges(
        "analyzer",
        check_confidence,
        {
            "review_required": "human_review",
            "approved": "indexer"
        }
    )

    workflow.add_edge("human_review", "analyzer")
    workflow.add_edge("indexer", END)

    # 컴파일
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
        compile_config["interrupt_before"] = ["human_review"]
    
    return workflow.compile(**compile_config)


# =============================================================================
# Routing Functions (Legacy - for single file mode)
# =============================================================================

def check_confidence(state: AgentState):
    """상태를 보고 다음 단계 결정 (단일 파일 모드용)"""
    
    print("\n" + "🔍"*40)
    print("[DEBUG] check_confidence 호출")
    print("🔍"*40)
    
    needs_human = state.get("needs_human_review", False)
    finalized_anchor = state.get("finalized_anchor", {})
    anchor_status = finalized_anchor.get("status") if finalized_anchor else None
    
    print(f"[DEBUG] needs_human_review: {needs_human}")
    print(f"[DEBUG] finalized_anchor status: {anchor_status}")
    
    # Anchor가 확정된 경우 (FK_LINK 포함!)
    if anchor_status in ["CONFIRMED", "INDIRECT_LINK", "FK_LINK"]:
        print(f"[DEBUG] → approved (Anchor 확정됨: {anchor_status})")
        print("🔍"*40)
        return "approved"
    
    # Processor가 확인 요청
    if state.get("raw_metadata", {}).get("anchor_info", {}).get("needs_human_confirmation"):
        print(f"[DEBUG] → review_required (Processor 요청)")
        return "review_required"
    
    # needs_human_review 플래그
    if state.get("needs_human_review"):
        print(f"[DEBUG] → review_required (needs_human_review=True)")
        return "review_required"

    print(f"[DEBUG] → approved (정상 진행)")
    print("🔍"*40)
    
    return "approved"


# =============================================================================
# Convenience Functions
# =============================================================================

def build_batch_agent(checkpointer=None):
    """2-Phase Batch Workflow 빌드 (편의 함수)"""
    return build_agent(checkpointer=checkpointer, mode="batch")


def build_single_agent(checkpointer=None):
    """단일 파일 워크플로우 빌드 (편의 함수)"""
    return build_agent(checkpointer=checkpointer, mode="single")
