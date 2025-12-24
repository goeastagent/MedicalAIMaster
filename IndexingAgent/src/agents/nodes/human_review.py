# src/agents/nodes/human_review.py
"""
Human Review Node - Human-in-the-Loop 처리
"""

import os
from typing import Dict, Any

from src.agents.state import AgentState
from src.agents.nodes.common import (
    create_empty_conversation_history,
    add_conversation_turn,
    extract_user_preferences,
)


def human_review_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node] Human-in-the-loop waiting node
    In actual execution, LangGraph's interrupt mechanism stops here
    In test environment, increase retry count to prevent infinite loop
    
    대화 히스토리에 턴 기록
    """
    print("\n" + "="*80)
    print("🛑 [HUMAN REVIEW NODE] Starting - User confirmation required")
    print("="*80)
    
    question = state.get("human_question", "Confirmation required.")
    retry_count = state.get("retry_count", 0)
    human_feedback = state.get("human_feedback")
    file_path = state.get("file_path", "")
    review_type = state.get("review_type", "general")
    
    # 대화 히스토리 가져오기 (없으면 생성)
    history = state.get("conversation_history")
    dataset_id = state.get("current_dataset_id", "unknown")
    
    if not history:
        history = create_empty_conversation_history(dataset_id)
    
    # 피드백이 있으면 히스토리에 기록 (재진입 시)
    if human_feedback:
        # 사용자 응답에 기반한 액션 결정
        action_taken = _determine_action_from_feedback(human_feedback, review_type)
        
        history = add_conversation_turn(
            history=history,
            review_type=review_type,
            agent_question=question,
            human_response=human_feedback,
            agent_action=action_taken,
            file_path=file_path,
            context_summary=f"Retry #{retry_count+1} for {os.path.basename(file_path)}"
        )
        
        # 사용자 선호도 업데이트
        history["user_preferences"] = extract_user_preferences(history)
        
        print(f"   📝 대화 히스토리에 기록됨 (턴 #{len(history['turns'])})")
    
    # Increase retry count
    new_retry_count = retry_count + 1
    
    print(f"\n⚠️  Question: {question[:150]}...")
    print(f"🔄 Retry count: {new_retry_count}/3")
    print(f"📚 대화 히스토리: {len(history.get('turns', []))}개 턴")
    print("="*80)
    
    return {
        "retry_count": new_retry_count,
        "conversation_history": history,
        "logs": [f"🛑 [Human Review] Waiting (retry: {new_retry_count}/3). Question: {question[:100]}..."]
    }


def _determine_action_from_feedback(feedback: str, review_type: str) -> str:
    """피드백에서 취한 액션 결정"""
    feedback_lower = feedback.lower().strip()
    
    if feedback_lower in ["skip", "제외", "스킵"]:
        return "Skipped file"
    elif feedback_lower in ["확인", "ok", "yes", "approve", "y"]:
        return "Approved AI decision"
    elif review_type == "classification":
        if "메타데이터" in feedback_lower or "metadata" in feedback_lower:
            return "Reclassified as metadata"
        elif "데이터" in feedback_lower or "data" in feedback_lower:
            return "Reclassified as data"
    elif review_type in ["anchor", "anchor_detection"]:
        return f"Set anchor to: {feedback}"
    
    return f"Applied feedback: {feedback[:50]}"

