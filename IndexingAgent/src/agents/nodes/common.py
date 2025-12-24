# src/agents/nodes/common.py
"""
공통 모듈 - 전역 리소스 및 공유 헬퍼 함수
"""

import os
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.processors.tabular import TabularProcessor
from src.processors.signal import SignalProcessor
from src.utils.llm_client import get_llm_client
from src.utils.ontology_manager import get_ontology_manager
from src.utils.llm_cache import get_llm_cache
from src.agents.state import ConversationHistory, ConversationTurn

# --- Global resource initialization ---
llm_client = get_llm_client()
ontology_manager = get_ontology_manager()
llm_cache = get_llm_cache()

# Processors list
processors = [
    TabularProcessor(llm_client),
    SignalProcessor(llm_client)
]


# =============================================================================
# Conversation History Management
# =============================================================================

def create_empty_conversation_history(dataset_id: str = "unknown") -> ConversationHistory:
    """빈 대화 히스토리 생성"""
    return {
        "session_id": f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "dataset_id": dataset_id,
        "started_at": datetime.now().isoformat(),
        "turns": [],
        "classification_decisions": [],
        "anchor_decisions": [],
        "user_preferences": {}
    }


def add_conversation_turn(
    history: ConversationHistory,
    review_type: str,
    agent_question: str,
    human_response: str,
    agent_action: str,
    file_path: Optional[str] = None,
    context_summary: Optional[str] = None
) -> ConversationHistory:
    """대화 히스토리에 새 턴 추가"""
    turn: ConversationTurn = {
        "turn_id": len(history.get("turns", [])) + 1,
        "timestamp": datetime.now().isoformat(),
        "file_path": file_path,
        "review_type": review_type,
        "agent_question": agent_question,
        "human_response": human_response,
        "agent_action": agent_action,
        "context_summary": context_summary
    }
    
    if "turns" not in history:
        history["turns"] = []
    history["turns"].append(turn)
    
    # 분류 결정 기록
    if review_type == "classification":
        if "classification_decisions" not in history:
            history["classification_decisions"] = []
        history["classification_decisions"].append({
            "file": os.path.basename(file_path) if file_path else "unknown",
            "response": human_response,
            "timestamp": turn["timestamp"]
        })
    
    # 앵커 결정 기록
    elif review_type in ["anchor", "anchor_detection"]:
        if "anchor_decisions" not in history:
            history["anchor_decisions"] = []
        history["anchor_decisions"].append({
            "file": os.path.basename(file_path) if file_path else "unknown",
            "response": human_response,
            "timestamp": turn["timestamp"]
        })
    
    return history


def format_history_for_prompt(history: ConversationHistory, max_turns: int = 5) -> str:
    """
    대화 히스토리를 LLM 프롬프트용 텍스트로 변환
    
    Args:
        history: 대화 히스토리
        max_turns: 포함할 최대 턴 수 (최근 N개)
    
    Returns:
        프롬프트에 삽입할 문자열
    """
    if not history or not history.get("turns"):
        return ""
    
    turns = history.get("turns", [])[-max_turns:]
    
    if not turns:
        return ""
    
    lines = [
        "\n[CONVERSATION HISTORY - Previous User Interactions]",
        "The following shows previous questions and user responses during this indexing session.",
        "Use this context to make better decisions and follow user preferences.",
        ""
    ]
    
    for turn in turns:
        file_info = f" (File: {os.path.basename(turn['file_path'])})" if turn.get('file_path') else ""
        lines.append(f"--- Turn {turn['turn_id']}{file_info} ---")
        lines.append(f"Type: {turn['review_type']}")
        lines.append(f"Agent Asked: {turn['agent_question'][:200]}...")
        lines.append(f"User Response: {turn['human_response']}")
        lines.append(f"Action Taken: {turn['agent_action']}")
        lines.append("")
    
    # 학습된 패턴 요약
    if history.get("user_preferences"):
        lines.append("[LEARNED USER PREFERENCES]")
        for key, value in history["user_preferences"].items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    
    # 분류 결정 요약
    if history.get("classification_decisions"):
        lines.append("[PREVIOUS CLASSIFICATION DECISIONS]")
        for dec in history["classification_decisions"][-3:]:
            lines.append(f"- {dec['file']}: {dec['response']}")
        lines.append("")
    
    # 앵커 결정 요약
    if history.get("anchor_decisions"):
        lines.append("[PREVIOUS ANCHOR DECISIONS]")
        for dec in history["anchor_decisions"][-3:]:
            lines.append(f"- {dec['file']}: {dec['response']}")
        lines.append("")
    
    return "\n".join(lines)


def extract_user_preferences(history: ConversationHistory) -> Dict[str, Any]:
    """
    대화 히스토리에서 사용자 선호도 패턴 추출
    """
    preferences = {}
    
    turns = history.get("turns", [])
    
    # 분류 패턴 분석
    classification_responses = [
        t["human_response"].lower() 
        for t in turns 
        if t["review_type"] == "classification"
    ]
    
    if classification_responses:
        approval_count = sum(1 for r in classification_responses if r in ["확인", "ok", "yes", "approve"])
        if approval_count > len(classification_responses) * 0.7:
            preferences["trusts_ai_classification"] = True
    
    # 앵커 패턴 분석
    anchor_responses = [
        t["human_response"].lower()
        for t in turns
        if t["review_type"] in ["anchor", "anchor_detection"]
    ]
    
    if anchor_responses:
        from collections import Counter
        common_anchors = Counter(anchor_responses).most_common(2)
        if common_anchors and common_anchors[0][1] > 1:
            preferences["preferred_anchor"] = common_anchors[0][0]
    
    return preferences

