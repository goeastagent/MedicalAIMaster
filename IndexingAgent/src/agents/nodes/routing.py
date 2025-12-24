# src/agents/nodes/routing.py
"""
Routing Functions - 조건부 라우팅 함수들
"""

from src.agents.state import AgentState


def check_classification_needs_review(state: AgentState) -> str:
    """분류 결과 중 불확실한 것이 있는지 확인"""
    classification_result = state.get("classification_result", {})
    uncertain_files = classification_result.get("uncertain_files", [])
    
    if uncertain_files:
        return "needs_review"
    return "all_confident"


def check_has_more_files(state: AgentState) -> str:
    """더 처리할 데이터 파일이 있는지 확인"""
    progress = state.get("processing_progress", {})
    
    # Single Source of Truth: advance 노드가 설정한 플래그만 확인
    # 이 방식으로 advance와 routing 간 로직 불일치 방지
    if progress.get("all_files_processed", False):
        return "all_done"
    
    return "has_more"


def check_data_needs_review(state: AgentState) -> str:
    """데이터 분석 후 Human Review 필요 여부 확인"""
    
    needs_human = state.get("needs_human_review", False)
    finalized_anchor = state.get("finalized_anchor", {})
    anchor_status = finalized_anchor.get("status") if finalized_anchor else None
    
    # Anchor가 확정된 경우 (FK_LINK 포함!)
    if anchor_status in ["CONFIRMED", "INDIRECT_LINK", "FK_LINK"]:
        return "approved"
    
    # Processor가 확인 요청
    if state.get("raw_metadata", {}).get("anchor_info", {}).get("needs_human_confirmation"):
        return "review_required"
    
    # needs_human_review 플래그
    if needs_human:
        return "review_required"
    
    return "approved"

