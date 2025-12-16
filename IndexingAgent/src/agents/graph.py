from langgraph.graph import StateGraph, END
from src.agents.state import AgentState
from src.agents.nodes import (
    load_data_node,
    ontology_builder_node,  # [NEW] 온톨로지 구축 노드
    analyze_semantics_node,
    human_review_node,
    index_data_node
)

def build_agent(checkpointer=None):
    """
    LangGraph 워크플로우 빌드
    
    Args:
        checkpointer: (선택) 상태 저장용 checkpointer (예: MemorySaver())
                     Human-in-the-Loop에서 interrupt/resume을 위해 필요
    """
    workflow = StateGraph(AgentState)

    # --- 1. 노드(Node) 등록: 에이전트가 할 일들 ---
    workflow.add_node("loader", load_data_node)                # 파일 읽기 & 기초 분석
    workflow.add_node("ontology_builder", ontology_builder_node) # [NEW] 온톨로지 구축
    workflow.add_node("analyzer", analyze_semantics_node)      # 의미 추론 (LLM)
    workflow.add_node("human_review", human_review_node)        # 사람에게 물어보기
    workflow.add_node("indexer", index_data_node)               # DB 저장

    # --- 2. 엣지(Edge) 연결: 순서 정의 ---
    
    # 시작 -> 로더
    workflow.set_entry_point("loader")
    
    # 로더 -> 온톨로지 빌더 (새 단계!)
    workflow.add_edge("loader", "ontology_builder")
    
    # 온톨로지 빌더 -> 분석기 (메타데이터 아닌 경우만)
    workflow.add_conditional_edges(
        "ontology_builder",
        lambda state: "skip" if state.get("skip_indexing") else "continue",
        {
            "skip": END,        # 메타데이터면 여기서 종료
            "continue": "analyzer"  # 일반 데이터면 분석 계속
        }
    )

    # 분석기 -> [분기점] -> 사람 or 저장
    # 여기서 '조건부 엣지(Conditional Edge)'가 사용됩니다.
    workflow.add_conditional_edges(
        "analyzer",
        check_confidence,  # 판단 함수
        {
            "review_required": "human_review", # 확신 없으면 사람에게
            "approved": "indexer"              # 확신하면 바로 저장
        }
    )

    # 사람 피드백 -> 다시 분석 (피드백 반영하여 재추론)
    workflow.add_edge("human_review", "analyzer")

    # 저장 -> 끝
    workflow.add_edge("indexer", END)

    # --- 3. 컴파일 (Interrupt 설정) ---
    # checkpointer가 있으면 state 저장/복원 가능
    # interrupt_before: 해당 노드 실행 전에 멈춤
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
        compile_config["interrupt_before"] = ["human_review"]  # human_review 전에 멈춤
    
    return workflow.compile(**compile_config)

# --- 판단 함수 (Routing Logic) ---
def check_confidence(state: AgentState):
    """상태를 보고 다음 단계 결정"""
    
    print("\n" + "🔍"*40)
    print("[DEBUG] check_confidence 호출")
    print("🔍"*40)
    
    # 상태 확인
    needs_human = state.get("needs_human_review", False)
    has_schema = len(state.get("finalized_schema", [])) > 0
    retry_count = state.get("retry_count", 0)
    finalized_anchor = state.get("finalized_anchor", {})
    anchor_status = finalized_anchor.get("status") if finalized_anchor else None
    
    print(f"[DEBUG] needs_human_review: {needs_human}")
    print(f"[DEBUG] finalized_schema 개수: {len(state.get('finalized_schema', []))}")
    print(f"[DEBUG] finalized_anchor status: {anchor_status}")
    print(f"[DEBUG] retry_count: {retry_count}")
    
    # ⭐ [FIX] 0. Anchor가 이미 확정된 경우 (CONFIRMED, INDIRECT_LINK) → 승인
    # ANALYZER에서 확정했으면 Processor의 needs_human_confirmation은 무시
    if anchor_status in ["CONFIRMED", "INDIRECT_LINK"]:
        print(f"[DEBUG] → approved (Anchor 확정됨: {anchor_status})")
        print("🔍"*40)
        return "approved"
    
    # 1. Processor가 이미 사람 확인이 필요하다고 했거나
    if state.get("raw_metadata", {}).get("anchor_info", {}).get("needs_human_confirmation"):
        print(f"[DEBUG] → review_required (Processor 요청)")
        return "review_required"
    
    # 2. LLM 분석 결과 확신도가 낮거나
    # (로직 추가 예정)
    
    # 3. 상태에 'needs_human_review' 플래그가 켜져 있으면
    if state.get("needs_human_review"):
        print(f"[DEBUG] → review_required (needs_human_review=True)")
        return "review_required"

    print(f"[DEBUG] → approved (정상 진행)")
    print("🔍"*40)
    
    return "approved"