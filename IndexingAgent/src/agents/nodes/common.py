# src/agents/nodes/common.py
"""
공통 모듈 - 전역 리소스 및 공유 헬퍼 함수
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.processors.tabular import TabularProcessor
from src.processors.signal import SignalProcessor
from src.utils.llm_client import get_llm_client
from src.utils.ontology_manager import get_ontology_manager
from src.utils.llm_cache import get_llm_cache
from src.agents.state import ConversationHistory, ConversationTurn


# =============================================================================
# Conversation Storage Configuration
# =============================================================================
CONVERSATIONS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "conversations"

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
        "entity_decisions": [],
        "user_preferences": {}
    }


def add_conversation_turn(
    history: ConversationHistory,
    review_type: str,
    agent_question: str,
    human_response: str,
    agent_action: str,
    file_path: Optional[str] = None,
    context_summary: Optional[str] = None,
    context_snapshot: Optional[Dict[str, Any]] = None,
    auto_save: bool = True
) -> ConversationHistory:
    """
    대화 히스토리에 새 턴 추가 + 자동 파일 저장
    
    Args:
        history: 대화 히스토리
        review_type: 리뷰 유형 (classification, entity, schema 등)
        agent_question: 에이전트가 한 질문
        human_response: 사용자 응답
        agent_action: 응답에 따른 에이전트 액션
        file_path: 관련 파일 경로
        context_summary: 컨텍스트 요약
        context_snapshot: 당시 상태 스냅샷 (나중에 Knowledge Graph 구축 시 활용)
        auto_save: 파일로 자동 저장 여부
    
    Returns:
        업데이트된 대화 히스토리
    """
    turn: ConversationTurn = {
        "turn_id": len(history.get("turns", [])) + 1,
        "timestamp": datetime.now().isoformat(),
        "file_path": file_path,
        "review_type": review_type,
        "agent_question": agent_question,
        "human_response": human_response,
        "agent_action": agent_action,
        "context_summary": context_summary,
        "context_snapshot": context_snapshot  # 추가: Knowledge Graph용 상태 스냅샷
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
    elif review_type in ["entity", "entity_detection"]:
        if "entity_decisions" not in history:
            history["entity_decisions"] = []
        history["entity_decisions"].append({
            "file": os.path.basename(file_path) if file_path else "unknown",
            "response": human_response,
            "timestamp": turn["timestamp"]
        })
    
    # 자동 파일 저장 (영속성)
    if auto_save:
        save_conversation_to_file(history)
    
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
    if history.get("entity_decisions"):
        lines.append("[PREVIOUS ENTITY IDENTIFIER DECISIONS]")
        for dec in history["entity_decisions"][-3:]:
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
    entity_responses = [
        t["human_response"].lower()
        for t in turns
        if t["review_type"] in ["entity", "entity_detection"]
    ]
    
    if entity_responses:
        from collections import Counter
        common_identifiers = Counter(entity_responses).most_common(2)
        if common_identifiers and common_identifiers[0][1] > 1:
            preferences["preferred_identifier"] = common_identifiers[0][0]
    
    return preferences


# =============================================================================
# Conversation File Storage (영속성)
# =============================================================================

def save_conversation_to_file(history: ConversationHistory) -> Optional[str]:
    """
    대화 히스토리를 JSON 파일로 저장
    
    저장 위치: data/conversations/{dataset_id}_{session_id}.json
    
    Returns:
        저장된 파일 경로 (실패 시 None)
    """
    try:
        # 디렉토리 생성
        CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
        
        dataset_id = history.get("dataset_id", "unknown")
        session_id = history.get("session_id", "unknown")
        
        # 안전한 파일명 생성
        safe_dataset_id = dataset_id.replace("/", "_").replace("\\", "_")
        filename = f"{safe_dataset_id}_{session_id}.json"
        filepath = CONVERSATIONS_DIR / filename
        
        # 저장할 데이터 준비 (업데이트 시간 추가)
        save_data = {
            **history,
            "last_updated": datetime.now().isoformat(),
            "total_turns": len(history.get("turns", []))
        }
        
        # JSON 저장 (한글 지원, 예쁘게 포맷)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
        
        return str(filepath)
        
    except Exception as e:
        print(f"⚠️ [ConversationSave] 저장 실패: {e}")
        return None


def load_conversation_from_file(dataset_id: str, session_id: str = None) -> Optional[ConversationHistory]:
    """
    저장된 대화 히스토리 로드
    
    Args:
        dataset_id: 데이터셋 ID
        session_id: 세션 ID (None이면 가장 최근 세션)
    
    Returns:
        대화 히스토리 (없으면 None)
    """
    try:
        if not CONVERSATIONS_DIR.exists():
            return None
        
        safe_dataset_id = dataset_id.replace("/", "_").replace("\\", "_")
        
        if session_id:
            # 특정 세션 로드
            filepath = CONVERSATIONS_DIR / f"{safe_dataset_id}_{session_id}.json"
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        else:
            # 가장 최근 세션 찾기
            pattern = f"{safe_dataset_id}_*.json"
            matching_files = sorted(
                CONVERSATIONS_DIR.glob(pattern),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            if matching_files:
                with open(matching_files[0], 'r', encoding='utf-8') as f:
                    return json.load(f)
        
        return None
        
    except Exception as e:
        print(f"⚠️ [ConversationLoad] 로드 실패: {e}")
        return None


def list_conversation_sessions(dataset_id: str = None) -> List[Dict[str, Any]]:
    """
    저장된 대화 세션 목록 조회
    
    Args:
        dataset_id: 특정 데이터셋만 필터 (None이면 전체)
    
    Returns:
        세션 정보 리스트 [{dataset_id, session_id, started_at, total_turns, filepath}, ...]
    """
    sessions = []
    
    try:
        if not CONVERSATIONS_DIR.exists():
            return sessions
        
        for filepath in CONVERSATIONS_DIR.glob("*.json"):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                session_dataset_id = data.get("dataset_id", "unknown")
                
                # 필터링
                if dataset_id and session_dataset_id != dataset_id:
                    continue
                
                sessions.append({
                    "dataset_id": session_dataset_id,
                    "session_id": data.get("session_id"),
                    "started_at": data.get("started_at"),
                    "last_updated": data.get("last_updated"),
                    "total_turns": data.get("total_turns", len(data.get("turns", []))),
                    "filepath": str(filepath)
                })
            except:
                continue
        
        # 최신순 정렬
        sessions.sort(key=lambda x: x.get("last_updated", ""), reverse=True)
        
    except Exception as e:
        print(f"⚠️ [ConversationList] 목록 조회 실패: {e}")
    
    return sessions


def export_conversations_for_knowledge_graph(dataset_id: str = None) -> Dict[str, Any]:
    """
    Knowledge Graph 구축을 위한 대화 데이터 추출
    
    모든 사용자 결정과 선호도를 구조화하여 반환
    
    Returns:
        {
            "classification_decisions": [...],  # 분류 결정들
            "entity_decisions": [...],          # Entity 식별 결정들
            "user_preferences": {...},          # 학습된 선호도
            "all_turns": [...],                 # 전체 대화 턴
            "context_snapshots": [...]          # 상태 스냅샷들
        }
    """
    result = {
        "classification_decisions": [],
        "entity_decisions": [],
        "user_preferences": {},
        "all_turns": [],
        "context_snapshots": []
    }
    
    sessions = list_conversation_sessions(dataset_id)
    
    for session_info in sessions:
        try:
            with open(session_info["filepath"], 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 분류 결정 수집
            for dec in data.get("classification_decisions", []):
                dec["dataset_id"] = data.get("dataset_id")
                dec["session_id"] = data.get("session_id")
                result["classification_decisions"].append(dec)
            
            # 앵커 결정 수집
            for dec in data.get("entity_decisions", []):
                dec["dataset_id"] = data.get("dataset_id")
                dec["session_id"] = data.get("session_id")
                result["entity_decisions"].append(dec)
            
            # 사용자 선호도 병합
            for key, value in data.get("user_preferences", {}).items():
                result["user_preferences"][key] = value
            
            # 전체 턴 수집
            for turn in data.get("turns", []):
                turn["dataset_id"] = data.get("dataset_id")
                turn["session_id"] = data.get("session_id")
                result["all_turns"].append(turn)
                
                # 컨텍스트 스냅샷 수집
                if turn.get("context_snapshot"):
                    result["context_snapshots"].append({
                        "turn_id": turn["turn_id"],
                        "dataset_id": data.get("dataset_id"),
                        "timestamp": turn["timestamp"],
                        "snapshot": turn["context_snapshot"]
                    })
        except:
            continue
    
    return result

