# src/agents/nodes/human_review.py
"""
Human Review Node - Human-in-the-Loop 처리

interrupt()를 사용하여 노드 내부에서 직접 사용자 입력을 받습니다.
대화 히스토리는 자동으로 파일에 저장됩니다.
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
    [Node] Human-in-the-loop with interrupt()
    
    데이터 파일 분석 결과에 대한 사용자 확인을 처리합니다.
    - Entity Identifier 컬럼 확인/수정
    - 스키마 분석 결과 확인
    
    interrupt()를 사용하여 노드 내부에서 직접 사용자 입력을 받습니다.
    대화 히스토리는 자동으로 파일에 저장됩니다.
    """
    from langgraph.types import interrupt
    
    print("\n" + "="*80)
    print("🛑 [HUMAN REVIEW NODE] Human-in-the-Loop")
    print("="*80)
    
    question = state.get("human_question", "확인이 필요합니다.")
    retry_count = state.get("retry_count", 0)
    file_path = state.get("file_path", "")
    review_type = state.get("review_type", "general")
    
    # 대화 히스토리 가져오기 (없으면 생성)
    history = state.get("conversation_history")
    dataset_id = state.get("current_dataset_id", "unknown")
    
    if not history:
        history = create_empty_conversation_history(dataset_id)
    
    # 최대 재시도 횟수 체크
    max_retries = 3
    if retry_count >= max_retries:
        print(f"   ⚠️ 최대 재시도 횟수 초과 ({max_retries}회)")
        return {
            "retry_count": retry_count,
            "skip_indexing": True,
            "conversation_history": history,
            "logs": [f"⚠️ [Human Review] 최대 재시도 초과 - 파일 스킵"]
        }
    
    # =========================================================================
    # 컨텍스트 스냅샷 생성 (Knowledge Graph용)
    # =========================================================================
    
    entity_identification = state.get("entity_identification", {})
    finalized_schema = state.get("finalized_schema", [])
    raw_metadata = state.get("raw_metadata", {})
    
    context_snapshot = {
        "file_path": file_path,
        "file_type": state.get("file_type"),
        "review_type": review_type,
        "entity_info": {
            "status": entity_identification.get("status"),
            "column_name": entity_identification.get("column_name"),
            "confidence": entity_identification.get("confidence"),
            "reasoning": entity_identification.get("reasoning", "")[:200]
        } if entity_identification else None,
        "schema_summary": {
            "total_columns": len(finalized_schema),
            "columns": [
                {
                    "name": col.get("original_name"),
                    "inferred": col.get("inferred_name"),
                    "confidence": col.get("confidence")
                }
                for col in finalized_schema[:10]  # 처음 10개만
            ]
        } if finalized_schema else None,
        "row_count": raw_metadata.get("row_count"),
        "retry_count": retry_count
    }
    
    print(f"\n   📄 파일: {os.path.basename(file_path)}")
    print(f"   🔄 재시도: {retry_count + 1}/{max_retries}")
    print(f"   ❓ 질문: {question[:100]}...")
    print("="*80)
    
    # =========================================================================
    # interrupt() 호출 - 사용자 입력 대기
    # =========================================================================
    
    human_response = interrupt({
        "type": "entity_review",
        "question": question,
        "file_path": file_path,
        "file_name": os.path.basename(file_path),
        "review_type": review_type,
        "context": context_snapshot,
        "retry_count": retry_count,
        "instructions": {
            "approve": "확인, ok, yes - AI 추천 승인",
            "set_identifier": "컬럼명 입력 - 해당 컬럼을 Entity Identifier로 지정",
            "skip": "skip, 제외 - 이 파일 건너뛰기"
        }
    })
    
    # =========================================================================
    # 사용자 응답 처리
    # =========================================================================
    
    print(f"\n   💬 사용자 피드백 수신: '{human_response}'")
    
    # 액션 결정
    action_taken = _determine_action_from_feedback(human_response, review_type)
    
    # 대화 히스토리에 기록 + 자동 저장
    history = add_conversation_turn(
        history=history,
        review_type=review_type,
        agent_question=question,
        human_response=human_response,
        agent_action=action_taken,
        file_path=file_path,
        context_summary=f"데이터 분석 확인 (재시도 #{retry_count + 1})",
        context_snapshot=context_snapshot,
        auto_save=True
    )
    
    # 사용자 선호도 업데이트
    history["user_preferences"] = extract_user_preferences(history)
    
    print(f"   ✅ 액션: {action_taken}")
    print(f"   📝 대화 히스토리에 기록됨 (턴 #{len(history['turns'])})")
    print("="*80)
    
    # 결과에 따른 처리
    response_lower = human_response.lower().strip()
    
    # Skip 처리
    if response_lower in ["skip", "제외", "스킵", "건너뛰기"]:
        return {
            "retry_count": retry_count + 1,
            "human_feedback": human_response,
            "skip_indexing": True,
            "conversation_history": history,
            "logs": [f"⏭️ [Human Review] 사용자 요청으로 파일 스킵: {os.path.basename(file_path)}"]
        }
    
    # 일반 피드백 (analyzer로 다시 전달)
    return {
        "retry_count": retry_count + 1,
        "human_feedback": human_response,
        "conversation_history": history,
        "logs": [f"✅ [Human Review] 피드백 수신: '{human_response[:50]}...'"]
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
    elif review_type in ["entity", "entity_detection"]:
        return f"Set entity identifier to: {feedback}"
    
    return f"Applied feedback: {feedback[:50]}"

