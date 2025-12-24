import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.agents.state import (
    AgentState, ColumnSchema, AnchorInfo, ProjectContext, OntologyContext,
    FileClassification, ClassificationResult, ProcessingProgress,
    ConversationHistory, ConversationTurn
)
from src.processors.tabular import TabularProcessor
from src.processors.signal import SignalProcessor
from src.utils.llm_client import get_llm_client
from src.utils.ontology_manager import get_ontology_manager
from src.utils.llm_cache import get_llm_cache
from src.config import HumanReviewConfig, ProcessingConfig

# Dataset-First Architecture imports
from src.utils.naming import generate_table_name, generate_table_id, generate_schema_hash
from src.utils.dataset_detector import detect_dataset_from_path, get_dataset_source_path

# --- Global resource initialization ---
llm_client = get_llm_client()
ontology_manager = get_ontology_manager()
llm_cache = get_llm_cache()  # Global cache instance
processors = [
    TabularProcessor(llm_client),
    SignalProcessor(llm_client)
]


# =============================================================================
# Conversation History Management (NEW)
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
    
    turns = history.get("turns", [])[-max_turns:]  # 최근 N개만
    
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
    
    예: 특정 유형의 파일을 항상 메타데이터로 분류하는 경향 등
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
        # "확인" 또는 "ok"가 자주 나오면 AI 판단을 신뢰하는 경향
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
        # 특정 컬럼명을 자주 지정하면 선호 앵커로 기록
        from collections import Counter
        common_anchors = Counter(anchor_responses).most_common(2)
        if common_anchors and common_anchors[0][1] > 1:
            preferences["preferred_anchor"] = common_anchors[0][0]
    
    return preferences



def load_data_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 1] Load file and extract basic metadata
    """
    file_path = state["file_path"]
    
    print("\n" + "="*80)
    print(f"📂 [LOADER NODE] Starting - {os.path.basename(file_path)}")
    print("="*80)
    
    # 1. Find appropriate Processor
    selected_processor = next((p for p in processors if p.can_handle(file_path)), None)
    
    if not selected_processor:
        return {
            "logs": [f"❌ Error: Unsupported file format ({file_path})"],
            "needs_human_review": True,
            "human_question": "Unsupported file format. How would you like to process this file?"
        }

    # 2. Extract metadata (Anchor detection is also performed here)
    try:
        raw_metadata = selected_processor.extract_metadata(file_path)
        processor_type = raw_metadata.get("processor_type", "unknown")
        
        # Check if Processor failed to find or was uncertain about Anchor
        anchor_info = raw_metadata.get("anchor_info", {})
        anchor_status = anchor_info.get("status", "MISSING")
        anchor_msg = anchor_info.get("msg", "")

        log_message = f"✅ [Loader] {processor_type.upper()} analysis complete. Anchor Status: {anchor_status}"

        print(f"\n✅ [LOADER NODE] Complete")
        print(f"   - Processor: {processor_type}")
        print(f"   - Columns: {len(raw_metadata.get('columns', []))}")
        print(f"   - Anchor Status: {anchor_status}")
        print("="*80)

        return {
            "file_type": processor_type,
            "raw_metadata": raw_metadata,
            "logs": [log_message]
        }
    except Exception as e:
        print(f"\n❌ [LOADER NODE] Error: {str(e)}")
        print("="*80)
        return {
            "logs": [f"❌ [Loader] Critical error: {str(e)}"],
            "error_message": str(e)
        }


def analyze_semantics_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 2] Semantic Analysis (Semantic Reasoning)
    Core brain that finalizes schema based on Processor results
    [NEW] References Global Context (Project Level) to ensure Anchor consistency across files.
    [NEW] 대화 히스토리를 컨텍스트로 활용하여 더 정확한 판단
    """
    print("\n" + "="*80)
    print("🧠 [ANALYZER NODE] Starting - Semantic Analysis")
    print("="*80)
    
    metadata = state["raw_metadata"]
    local_anchor_info = metadata.get("anchor_info", {})
    human_feedback = state.get("human_feedback")
    
    # Get Global Context (initialize if not exists)
    project_context = state.get("project_context", {
        "master_anchor_name": None, 
        "known_aliases": [], 
        "example_id_values": []
    })
    
    # [NEW] 대화 히스토리 가져오기
    dataset_id = state.get("current_dataset_id", "unknown")
    conversation_history = state.get("conversation_history")
    if not conversation_history:
        conversation_history = create_empty_conversation_history(dataset_id)
    
    # 히스토리를 프롬프트용 텍스트로 변환
    history_context = format_history_for_prompt(conversation_history, max_turns=5)
    if history_context:
        print(f"   📚 대화 히스토리 컨텍스트 로드됨 ({len(conversation_history.get('turns', []))}개 턴)")
    
    finalized_anchor = state.get("finalized_anchor")
    retry_count = state.get("retry_count", 0)
    
    # Prevent infinite loop: force processing after 3+ retries
    if retry_count >= 3:
        log_msg = f"⚠️ [Analyzer] Retry count exceeded ({retry_count}). Forcing local Anchor."
        
        # Use locally found Anchor as-is
        finalized_anchor = {
            "status": "CONFIRMED",
            "column_name": local_anchor_info.get("target_column", "unknown"),
            "is_time_series": local_anchor_info.get("is_time_series", False),
            "reasoning": f"Forced confirmation after {retry_count} retries",
            "mapped_to_master": project_context.get("master_anchor_name")
        }
        
        # Skip schema analysis and complete
        return {
            "finalized_anchor": finalized_anchor,
            "finalized_schema": [],
            "project_context": project_context,
            "needs_human_review": False,
            "human_feedback": None,
            "retry_count": retry_count,
            "logs": [log_msg, "⚠️ [Analyzer] Schema analysis skipped (retry exceeded)"]
        }

    # --- Scenario A: Process user feedback (re-entry) ---
    if human_feedback:
        log_msg = f"🗣️ [Feedback] User feedback received: '{human_feedback}'"
        
        # [NEW] 사용자 피드백 시 관련 캐시 무효화
        file_path = state.get("file_path", "")
        if file_path:
            filename = os.path.basename(file_path)
            llm_cache.invalidate_for_file(filename)
        
        # ⭐ [FIX] Parse user input - distinguish column name vs description
        parsed_column = _parse_human_feedback_to_column(
            feedback=human_feedback,
            available_columns=metadata.get("columns", []),
            master_anchor=project_context.get("master_anchor_name"),
            file_path=state.get("file_path", "")
        )
        
        if parsed_column.get("action") == "skip":
            # Skip request
            log_msg += " → File skip requested"
            return {
                "finalized_anchor": None,
                "finalized_schema": [],
                "project_context": project_context,
                "needs_human_review": False,
                "human_feedback": None,
                "skip_indexing": True,
                "logs": [log_msg, "⏭️ [Analyzer] File skipped by user request"]
            }
        
        # [NEW] Handle special case: filename as ID (for .vital files)
        if parsed_column.get("action") == "use_filename_as_id":
            caseid_value = parsed_column.get("caseid_value")
            reasoning = parsed_column.get("reasoning", "Using filename as identifier")
            
            print(f"   → Using filename as ID: caseid={caseid_value}")
            print(f"   → Reasoning: {reasoning}")
            
            # Update metadata with caseid info
            if "anchor_info" not in metadata:
                metadata["anchor_info"] = {}
            
            metadata["anchor_info"]["status"] = "FOUND"
            metadata["anchor_info"]["target_column"] = "caseid"
            metadata["anchor_info"]["caseid_value"] = caseid_value
            metadata["anchor_info"]["is_time_series"] = True
            metadata["anchor_info"]["needs_human_confirmation"] = False
            
            finalized_anchor = {
                "status": "CONFIRMED",
                "column_name": "caseid",
                "caseid_value": caseid_value,
                "is_time_series": metadata.get("is_time_series", True),
                "reasoning": reasoning,
                "mapped_to_master": project_context.get("master_anchor_name")
            }
            
            # Don't return yet - continue to schema analysis
        
        determined_column = parsed_column.get("column_name", human_feedback.strip())
        reasoning = parsed_column.get("reasoning", "User manually confirmed.")
        
        print(f"   → Parsing result: '{determined_column}'")
        print(f"   → Reasoning: {reasoning}")
        
        # Force Anchor confirmation based on feedback
        finalized_anchor = {
            "status": "CONFIRMED",
            "column_name": determined_column,
            "is_time_series": local_anchor_info.get("is_time_series", False),
            "reasoning": reasoning,
            "mapped_to_master": project_context.get("master_anchor_name") 
        }
        
        # ⭐ [FIX] Reset needs_human_confirmation after feedback processing
        # Prevents re-entering review_required in check_confidence
        if "anchor_info" in metadata:
            metadata["anchor_info"]["needs_human_confirmation"] = False
            metadata["anchor_info"]["status"] = "CONFIRMED"
        
        # Consider feedback processing complete and proceed (don't return)
    
    # --- Scenario B: When Anchor is not yet finalized -> Check Global Context ---
    if not finalized_anchor:
        
        # [NEW] Signal 파일 특별 처리: LLM이 추론한 ID 정보 확인
        file_type = state.get("file_type", "tabular")
        if file_type == "signal" and local_anchor_info.get("id_value"):
            id_column = local_anchor_info.get("target_column", "file_id")
            id_value = local_anchor_info.get("id_value")
            confidence = local_anchor_info.get("confidence", 0.5)
            needs_confirmation = local_anchor_info.get("needs_human_confirmation", False)
            
            print(f"\n📡 [Signal File] LLM-inferred ID: {id_column}={id_value} (confidence: {confidence:.0%})")
            
            # 확신도가 낮으면 사용자 확인 요청
            if needs_confirmation and confidence < 0.7:
                question = _generate_natural_human_question(
                    file_path=state.get("file_path", ""),
                    context={
                        "reasoning": local_anchor_info.get("reasoning", ""),
                        "candidates": f"{id_column}={id_value}",
                        "columns": [],  # Signal 파일은 컬럼이 없음
                        "message": f"LLM inferred ID with {confidence:.0%} confidence. Please verify."
                    },
                    issue_type="anchor_uncertain",
                    conversation_history=conversation_history  # [NEW] 대화 히스토리 전달
                )
                
                return {
                    "needs_human_review": True,
                    "review_type": "anchor",  # [NEW]
                    "human_question": question,
                    "conversation_history": conversation_history,  # [NEW]
                    "logs": [f"⚠️ [Analyzer] Signal file ID uncertain ({confidence:.0%}). Needs confirmation."]
                }
            
            # 확신도가 높으면 자동 확정
            finalized_anchor = {
                "status": "CONFIRMED",
                "column_name": id_column,
                "id_value": id_value,
                "is_time_series": True,
                "reasoning": local_anchor_info.get("reasoning", "LLM inferred ID"),
                "confidence": confidence,
                "mapped_to_master": project_context.get("master_anchor_name")
            }
            
            state["logs"].append(f"📡 [Signal] Auto-confirmed: {id_column}={id_value}")
        
        # [NEW] Case 1: Project already has agreed Anchor (Leader)
        elif project_context.get("master_anchor_name"):
            master_name = project_context["master_anchor_name"]
            
            # LLM에게 비교 요청 (Global Context vs Local Data)
            comparison = _compare_with_global_context(
                local_metadata=metadata,
                local_anchor_info=local_anchor_info,
                project_context=project_context
            )
            
            # Debug: comparison result log
            comparison_status = comparison.get("status", "UNKNOWN")
            comparison_msg = comparison.get("message", "")
            print(f"\n[DEBUG] Global Anchor comparison result: {comparison_status}")
            print(f"[DEBUG] Message: {comparison_msg}")
            print(f"[DEBUG] Target Column: {comparison.get('target_column', 'N/A')}")
            
            if comparison["status"] == "MATCH":
                # Match success -> auto confirm
                target_col = comparison["target_column"]
                finalized_anchor = {
                    "status": "CONFIRMED",
                    "column_name": target_col,
                    "is_time_series": local_anchor_info.get("is_time_series", False),
                    "reasoning": f"Matched with global master anchor '{master_name}'",
                    "mapped_to_master": master_name
                }
                state["logs"].append(f"🔗 [Anchor Link] Matched with Global Anchor '{master_name}' (Local: '{target_col}')")
            
            elif comparison["status"] == "INDIRECT_LINK":
                # ⭐ [NEW] Indirect link success -> auto confirm (no human intervention needed!)
                via_col = comparison["target_column"]
                via_table = comparison.get("via_table", "unknown")
                
                finalized_anchor = {
                    "status": "INDIRECT_LINK",
                    "column_name": via_col,  # Link column (e.g., caseid)
                    "is_time_series": local_anchor_info.get("is_time_series", False),
                    "reasoning": comparison.get("message"),
                    "mapped_to_master": master_name,
                    "via_table": via_table,
                    "link_type": "indirect"  # Indirect link via FK
                }
                
                print(f"\n✅ [INDIRECT_LINK] Auto-confirmed indirect link!")
                print(f"   - Link column: {via_col}")
                print(f"   - Via table: {via_table}")
                print(f"   - Master Anchor: {master_name}")
                
                state["logs"].append(
                    f"🔗 [Indirect Link] Indirectly linked to '{master_name}' in '{via_table}' via '{via_col}'"
                )
                
            else:
                # Conflict or missing -> human intervention
                msg = comparison.get("message", "Anchor mismatch occurred")
                
                # Generate natural question with LLM
                natural_question = _generate_natural_human_question(
                    file_path=state.get("file_path", ""),
                    context={
                        "master_anchor": master_name,
                        "candidates": local_anchor_info.get("target_column"),
                        "reasoning": msg,
                        "columns": metadata.get("columns", [])
                    },
                    issue_type="anchor_conflict",
                    conversation_history=conversation_history  # [NEW] 대화 히스토리 전달
                )
                
                return {
                    "needs_human_review": True,
                    "review_type": "anchor",  # [NEW]
                    "human_question": natural_question,
                    "conversation_history": conversation_history,  # [NEW]
                    "retry_count": retry_count,  # Keep current retry count
                    "logs": [f"⚠️ [Analyzer] Global Anchor mismatch (Status: {comparison_status}). Retry: {retry_count}/3"]
                }

        # [NEW] Case 2: This is the first file (no Global Context)
        else:
            # Flexible judgment: Processor uncertainty + LLM review
            processor_confidence = local_anchor_info.get("confidence", 0.5 if local_anchor_info.get("needs_human_confirmation") else 0.9)
            
            review_decision = _should_request_human_review(
                file_path=state.get("file_path", ""),
                issue_type="anchor_detection",
                context={
                    "processor_msg": local_anchor_info.get("msg"),
                    "candidates": local_anchor_info.get("target_column"),
                    "columns": metadata.get("columns", []),
                    "processor_needs_confirmation": local_anchor_info.get("needs_human_confirmation", False)
                },
                rule_based_confidence=processor_confidence
            )
            
            if review_decision["needs_review"]:
                question = _generate_natural_human_question(
                    file_path=state.get("file_path", ""),
                    context={
                        "reasoning": local_anchor_info.get("msg"),
                        "candidates": local_anchor_info.get("target_column", "None"),
                        "columns": metadata.get("columns", [])
                    },
                    issue_type="anchor_uncertain",
                    conversation_history=conversation_history  # [NEW] 대화 히스토리 전달
                )
                
                return {
                    "needs_human_review": True,
                    "review_type": "anchor",  # [NEW]
                    "human_question": question,
                    "conversation_history": conversation_history,  # [NEW]
                    "logs": [f"⚠️ [Analyzer] Anchor uncertain (first file). {review_decision['reason']}"]
                }
            
            # Confident -> confirm
            finalized_anchor = {
                "status": "CONFIRMED",
                "column_name": local_anchor_info.get("target_column"),
                "is_time_series": local_anchor_info.get("is_time_series"),
                "reasoning": local_anchor_info.get("reasoning"),
                "mapped_to_master": None  # Will become master
            }

    # --- 3. Update Global Context (First-Come Leader Strategy) ---
    # If Anchor is confirmed and no master exists, this file's Anchor becomes master
    if finalized_anchor and not project_context.get("master_anchor_name"):
        project_context["master_anchor_name"] = finalized_anchor["column_name"]
        project_context["known_aliases"].append(finalized_anchor["column_name"])
        state["logs"].append(f"👑 [Project Context] New Master Anchor set: '{finalized_anchor['column_name']}'")

    # --- 4. Detailed schema analysis (common) ---
    schema_analysis = _analyze_columns_with_llm(
        columns=metadata.get("columns", []),
        sample_data=metadata.get("column_details", {}),
        anchor_context=finalized_anchor
    )

    print(f"\n✅ [ANALYZER NODE] Complete")
    print(f"   - Anchor: {finalized_anchor.get('column_name', 'N/A')}")
    print(f"   - Mapped to Master: {finalized_anchor.get('mapped_to_master', 'N/A')}")
    print(f"   - Schema Columns: {len(schema_analysis)}")
    print("="*80)

    result = {
        "finalized_anchor": finalized_anchor,
        "finalized_schema": schema_analysis,
        "project_context": project_context,  # Return updated context
        "raw_metadata": metadata,  # ⭐ [FIX] Return updated raw_metadata (needs_human_confirmation reset)
        "needs_human_review": False,
        "human_feedback": None, 
        "logs": ["🧠 [Analyzer] Complete schema and ontology analysis."]
    }
    
    print(f"\n[DEBUG ANALYZER] Return value:")
    print(f"   - finalized_schema: {len(result['finalized_schema'])}")
    print(f"   - needs_human_review: {result['needs_human_review']}")
    
    return result


def human_review_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 3] Human-in-the-loop waiting node
    In actual execution, LangGraph's interrupt mechanism stops here
    In test environment, increase retry count to prevent infinite loop
    
    [NEW] 대화 히스토리에 턴 기록
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


def index_data_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 4 - Phase 3] Build PostgreSQL DB (ontology-based)
    
    Expert feedback applied:
    - Chunk Processing (safe handling of large files)
    - Auto FK constraint creation (ALTER TABLE)
    - Auto index creation (Level 1-2)
    
    [NEW] Dataset-First Architecture:
    - 테이블명에 데이터셋 prefix 추가
    - 버전 관리 테이블에 인덱싱 기록
    - 온톨로지에 dataset_id 포함
    
    [NEW] Signal file handling:
    - .vital files are registered as metadata only (no raw data import)
    - caseid is extracted from filename and linked to clinical_data
    """
    import pandas as pd
    import os
    
    from src.database.connection import get_db_manager
    from src.database.schema_generator import SchemaGenerator
    from src.database.version_manager import get_version_manager
    
    print("\n" + "="*80)
    print("💾 [INDEXER NODE] Starting - PostgreSQL DB construction")
    print("="*80)
    
    schema = state.get("finalized_schema", [])
    file_path = state["file_path"]
    file_type = state.get("file_type", "tabular")  # [NEW] 파일 타입 확인
    metadata = state.get("raw_metadata", {})  # [NEW] 메타데이터 확인
    ontology = state.get("ontology_context", {})
    
    # === Dataset-First: 데이터셋 ID 및 테이블명 생성 ===
    dataset_id = state.get("current_dataset_id")
    if not dataset_id:
        # 경로에서 자동 감지
        dataset_id = detect_dataset_from_path(file_path)
        if not dataset_id:
            dataset_id = "default_dataset"
        print(f"📁 [Dataset] Auto-detected: {dataset_id}")
    
    # [NEW] Signal 파일 (.vital) 특별 처리
    if file_type == "signal" and metadata.get("is_vital_file", False):
        return _handle_vital_file_indexing(state, file_path, metadata, ontology)
    
    # Dataset-First: 테이블명에 prefix 추가
    table_name = generate_table_name(file_path, dataset_id)
    table_id = generate_table_id(dataset_id, table_name)
    
    print(f"   📋 Dataset: {dataset_id}")
    print(f"   📋 Table: {table_name}")
    
    # DB manager
    db_manager = get_db_manager()
    
    try:
        # === 1. Load data (pandas auto-creates table) ===
        print(f"\n📥 [Data] Loading data...")
        
        # Check file size
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"   - File size: {file_size_mb:.1f}MB")
        
        total_rows = 0
        
        # SQLAlchemy engine for PostgreSQL (for pandas to_sql)
        engine = db_manager.get_sqlalchemy_engine()
        
        # [TEST MODE] Row limit (check environment variable)
        test_limit = os.environ.get("TEST_ROW_LIMIT")
        limit_kwargs = {}
        if test_limit:
            limit_rows = int(test_limit)
            limit_kwargs = {"nrows": limit_rows}
            print(f"⚠️ [TEST MODE] Data load limit applied: processing top {limit_rows} rows only")

        if file_size_mb > 50:  # Chunk processing for files > 50MB
            print(f"   - Large file - Chunk Processing applied (100,000 rows per chunk)")
            
            chunk_size = 100000
            # [TEST MODE] Apply limit even with chunk processing
            # nrows works with chunksize to limit total rows read
            
            for i, chunk in enumerate(pd.read_csv(file_path, chunksize=chunk_size, **limit_kwargs)):
                chunk.to_sql(
                    table_name, 
                    engine, 
                    if_exists='append' if i > 0 else 'replace',
                    index=False,
                    method='multi'  # PostgreSQL optimization
                )
                total_rows += len(chunk)
                print(f"      • Chunk {i+1}: {len(chunk):,} rows loaded (cumulative: {total_rows:,} rows)")
        else:
            # Load small files at once
            print(f"   - Regular file - loading at once")
            df = pd.read_csv(file_path, **limit_kwargs)
            df.to_sql(
                table_name, 
                engine, 
                if_exists='replace', 
                index=False,
                method='multi'
            )
            total_rows = len(df)
            print(f"   - {total_rows:,} rows loaded")
        
        print(f"✅ Data loading successful")
        
        # === 2. Create indices (performance optimization) ===
        print(f"\n🔍 [Index] Creating indices...")
        
        indices = SchemaGenerator.generate_indices(
            table_name=table_name,
            schema=schema,
            ontology_context=ontology
        )
        
        indices_created = []
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        for idx_ddl in indices:
            try:
                cursor.execute(idx_ddl)
                # Extract index name
                idx_name = idx_ddl.split('"')[1] if '"' in idx_ddl else idx_ddl.split()[2]
                indices_created.append(idx_name)
            except Exception as e:
                print(f"⚠️  Index creation failed: {e}")
        
        conn.commit()
        
        if indices_created:
            print(f"   - {len(indices_created)} indices created: {', '.join(indices_created)}")
        else:
            print(f"   - No indices created")
        
        # === 3. Verification ===
        print(f"\n✅ [Verify] Verifying...")
        
        # Check row count (PostgreSQL)
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        actual_rows = cursor.fetchone()[0]
        
        if actual_rows == total_rows:
            print(f"   - Row count matches: {actual_rows:,} rows ✅")
        else:
            print(f"   ⚠️ Row count mismatch: expected {total_rows:,}, actual {actual_rows:,}")
        
        # === [NEW] Save Column Metadata (Neo4j) - Dataset-First ===
        if schema:
            print(f"\n📋 [Column Metadata] Saving column metadata...")
            
            if "column_metadata" not in ontology:
                ontology["column_metadata"] = {}
            
            # Dataset-First: 온톨로지에 dataset_id 설정
            ontology["dataset_id"] = dataset_id
            ontology["column_metadata"][table_name] = {}
            
            for col_schema in schema:
                col_name = col_schema.get("original_name", "unknown")
                ontology["column_metadata"][table_name][col_name] = {
                    "original_name": col_name,
                    "full_name": col_schema.get("full_name"),
                    "inferred_name": col_schema.get("inferred_name"),
                    "description": col_schema.get("description"),
                    "description_kr": col_schema.get("description_kr"),
                    "data_type": col_schema.get("data_type"),
                    "unit": col_schema.get("unit"),
                    "typical_range": col_schema.get("typical_range"),
                    "is_pii": col_schema.get("is_pii", False),
                    "confidence": col_schema.get("confidence", 0)
                }
            
            print(f"   - {len(schema)} column metadata generated")
            
            # Save to Neo4j (with dataset_id)
            from src.utils.ontology_manager import get_ontology_manager
            ontology_manager = get_ontology_manager()
            ontology_manager.save(ontology, dataset_id=dataset_id)
            print(f"   - Neo4j save complete (dataset: {dataset_id})")
        
        # === [NEW] Version Management - Dataset-First ===
        print(f"\n📝 [Version] Recording indexing history...")
        try:
            version_manager = get_version_manager(db_manager)
            schema_hash = generate_schema_hash(schema)
            
            version_info = version_manager.record_indexing(
                table_id=table_id,
                dataset_id=dataset_id,
                table_name=table_name,
                original_filename=os.path.basename(file_path),
                original_filepath=file_path,
                row_count=total_rows,
                column_count=len(schema),
                schema_hash=schema_hash
            )
            print(f"   - Version: v{version_info['version']}")
            if version_info.get('is_schema_changed'):
                print(f"   ⚠️ Schema changed from previous version!")
        except Exception as ve:
            print(f"   ⚠️ Version recording failed (non-critical): {ve}")
        
        print("="*80)
        
        return {
            "current_dataset_id": dataset_id,        # [NEW] Dataset ID
            "current_table_name": table_name,        # [NEW] Table name with prefix
            "ontology_context": ontology,            # Updated ontology
            "logs": [
                f"💾 [Indexer] {table_name} created ({total_rows:,} rows)",
                f"📁 [Indexer] Dataset: {dataset_id}",
                f"🔍 [Indexer] Indices: {len(indices_created)}",
                "✅ [Done] Indexing process complete."
            ]
        }
        
    except Exception as e:
        print(f"\n❌ [Error] DB save failed: {str(e)}")
        print("="*80)
        
        import traceback
        traceback.print_exc()
        
        return {
            "logs": [f"❌ [Indexer] DB save failed: {str(e)}"],
            "error_message": str(e)
        }

# --- Helper Functions (Private) ---

def _handle_vital_file_indexing(state: AgentState, file_path: str, metadata: Dict, ontology: Dict) -> Dict[str, Any]:
    """
    [옵션 B] Signal 파일 인덱싱 - 정규화된 테이블 구조
    
    두 개의 테이블로 정규화:
    1. signal_files: 파일 기본 정보 (1 row per file)
    2. signal_tracks: 트랙별 정보 (N rows per file, LLM이 의미 분석)
    
    Tabular 데이터와 동일한 패턴:
    - Rule: 트랙 정보 수집
    - LLM: 각 트랙의 의미/카테고리 분석
    """
    import pandas as pd
    from src.database.connection import get_db_manager
    from src.utils.ontology_manager import get_ontology_manager
    
    # anchor_info에서 ID 정보 추출 (LLM이 추론한 결과)
    anchor_info = metadata.get("anchor_info", {})
    id_column = anchor_info.get("target_column", "file_id")
    id_value = anchor_info.get("id_value") or anchor_info.get("caseid_value")
    confidence = anchor_info.get("confidence", 0.5)
    needs_confirmation = anchor_info.get("needs_human_confirmation", False)
    
    tracks = metadata.get("columns", [])
    column_details = metadata.get("column_details", {})
    
    print(f"\n📡 [Signal File] Processing signal file (Normalized Tables)...")
    print(f"   - ID Column: {id_column}")
    print(f"   - ID Value: {id_value}")
    print(f"   - Confidence: {confidence:.0%}")
    print(f"   - Tracks: {len(tracks)}")
    print(f"   - File: {os.path.basename(file_path)}")
    
    # ID가 없으면 스킵
    if id_value is None:
        print(f"   ⚠️ ID not found. Skipping indexing.")
        return {
            "logs": [f"⚠️ [Indexer] Signal file skipped: ID not found"],
            "skip_indexing": True,
            "needs_human_review": True,
            "human_question": f"Cannot determine ID for signal file '{os.path.basename(file_path)}'. Please specify the ID column and value."
        }
    
    # 확신도가 낮으면 경고
    if needs_confirmation:
        print(f"   ⚠️ Low confidence ({confidence:.0%}). ID may need verification.")
    
    try:
        db_manager = get_db_manager()
        engine = db_manager.get_sqlalchemy_engine()
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        # === 1. 테이블 생성 (정규화된 구조) ===
        create_tables_sql = """
        -- 파일 기본 정보 테이블
        CREATE TABLE IF NOT EXISTS signal_files (
            file_id SERIAL PRIMARY KEY,
            id_column VARCHAR(50) NOT NULL,
            id_value VARCHAR(100) NOT NULL,
            file_path TEXT NOT NULL,
            file_name VARCHAR(255),
            file_format VARCHAR(20),
            file_size_mb FLOAT,
            duration_seconds FLOAT,
            track_count INTEGER,
            confidence FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(file_path)
        );
        
        CREATE INDEX IF NOT EXISTS idx_signal_files_id_value ON signal_files(id_value);
        CREATE INDEX IF NOT EXISTS idx_signal_files_id_column ON signal_files(id_column);
        
        -- 트랙별 정보 테이블 (정규화)
        CREATE TABLE IF NOT EXISTS signal_tracks (
            track_id SERIAL PRIMARY KEY,
            file_id INTEGER REFERENCES signal_files(file_id) ON DELETE CASCADE,
            track_name VARCHAR(255) NOT NULL,
            sample_rate FLOAT,
            unit VARCHAR(50),
            min_value FLOAT,
            max_value FLOAT,
            track_type VARCHAR(50),
            inferred_name VARCHAR(255),
            description TEXT,
            clinical_category VARCHAR(100),
            UNIQUE(file_id, track_name)
        );
        
        CREATE INDEX IF NOT EXISTS idx_signal_tracks_file_id ON signal_tracks(file_id);
        CREATE INDEX IF NOT EXISTS idx_signal_tracks_track_name ON signal_tracks(track_name);
        CREATE INDEX IF NOT EXISTS idx_signal_tracks_category ON signal_tracks(clinical_category);
        """
        
        for stmt in create_tables_sql.strip().split(';'):
            if stmt.strip():
                try:
                    cursor.execute(stmt)
                except Exception as e:
                    pass  # Ignore duplicate errors
        
        conn.commit()
        print(f"   ✅ Tables ready (signal_files, signal_tracks)")
        
        # === 2. signal_files 레코드 삽입 ===
        ext = os.path.splitext(file_path)[1].lower()
        format_map = {".vital": "vitaldb", ".edf": "edf", ".bdf": "bdf"}
        file_format = format_map.get(ext, "unknown")
        
        insert_file_sql = """
        INSERT INTO signal_files (id_column, id_value, file_path, file_name, file_format, 
                                  file_size_mb, duration_seconds, track_count, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (file_path) 
        DO UPDATE SET 
            id_column = EXCLUDED.id_column,
            id_value = EXCLUDED.id_value,
            file_size_mb = EXCLUDED.file_size_mb,
            duration_seconds = EXCLUDED.duration_seconds,
            track_count = EXCLUDED.track_count,
            confidence = EXCLUDED.confidence
        RETURNING file_id;
        """
        
        cursor.execute(insert_file_sql, (
            id_column,
            str(id_value),
            file_path,
            os.path.basename(file_path),
            file_format,
            metadata.get("file_size_mb", 0),
            metadata.get("duration", 0),
            len(tracks),
            confidence
        ))
        
        file_id = cursor.fetchone()[0]
        conn.commit()
        print(f"   ✅ File registered: file_id={file_id}, {id_column}={id_value}")
        
        # === 3. LLM에게 트랙 의미 분석 요청 ===
        track_analyses = _analyze_tracks_with_llm(tracks, column_details)
        
        # === 4. signal_tracks 레코드 삽입 ===
        insert_track_sql = """
        INSERT INTO signal_tracks (file_id, track_name, sample_rate, unit, min_value, max_value,
                                   track_type, inferred_name, description, clinical_category)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (file_id, track_name) 
        DO UPDATE SET 
            sample_rate = EXCLUDED.sample_rate,
            unit = EXCLUDED.unit,
            min_value = EXCLUDED.min_value,
            max_value = EXCLUDED.max_value,
            track_type = EXCLUDED.track_type,
            inferred_name = EXCLUDED.inferred_name,
            description = EXCLUDED.description,
            clinical_category = EXCLUDED.clinical_category;
        """
        
        tracks_inserted = 0
        for track_name in tracks:
            details = column_details.get(track_name, {})
            analysis = track_analyses.get(track_name, {})
            
            cursor.execute(insert_track_sql, (
                file_id,
                track_name,
                details.get("sample_rate"),
                details.get("unit"),
                details.get("min_val"),
                details.get("max_val"),
                details.get("column_type", "unknown"),
                analysis.get("inferred_name", track_name),
                analysis.get("description", ""),
                analysis.get("clinical_category", "unknown")
            ))
            tracks_inserted += 1
        
        conn.commit()
        print(f"   ✅ Tracks registered: {tracks_inserted} tracks")
        
        # === 5. 온톨로지 업데이트 (정규화된 구조 반영) ===
        if ontology:
            if "file_tags" not in ontology:
                ontology["file_tags"] = {}
            
            # 트랙 분석 결과를 포함한 상세 정보 저장
            ontology["file_tags"][file_path] = {
                "type": "signal_data",
                "format": file_format,
                "file_id": file_id,
                "id_column": id_column,
                "id_value": id_value,
                "track_count": len(tracks),
                "confidence": confidence,
                "track_analyses": track_analyses  # LLM이 분석한 트랙 정보
            }
            
            # 정규화된 테이블 스키마 메타데이터
            if "column_metadata" not in ontology:
                ontology["column_metadata"] = {}
            
            # signal_files 테이블 메타데이터
            ontology["column_metadata"]["signal_files"] = {
                "file_id": {
                    "original_name": "file_id",
                    "description": "Unique file identifier (auto-generated)",
                    "description_kr": "파일 고유 ID (자동 생성)",
                    "data_type": "INT",
                    "is_pii": False
                },
                "id_column": {
                    "original_name": "id_column",
                    "description": "Type of ID (caseid, patient_id, subject_id, etc.)",
                    "description_kr": "ID 타입 (caseid, patient_id, subject_id 등)",
                    "data_type": "VARCHAR",
                    "is_pii": False
                },
                "id_value": {
                    "original_name": "id_value",
                    "description": "ID value extracted from filename",
                    "description_kr": "파일명에서 추출된 ID 값",
                    "data_type": "VARCHAR",
                    "is_pii": False
                },
                "file_path": {
                    "original_name": "file_path",
                    "description": "Full path to signal file",
                    "description_kr": "신호 파일 전체 경로",
                    "data_type": "TEXT",
                    "is_pii": False
                },
                "file_format": {
                    "original_name": "file_format",
                    "description": "Signal file format (vitaldb, edf, bdf)",
                    "description_kr": "신호 파일 포맷",
                    "data_type": "VARCHAR",
                    "is_pii": False
                }
            }
            
            # signal_tracks 테이블 메타데이터
            ontology["column_metadata"]["signal_tracks"] = {
                "track_id": {
                    "original_name": "track_id",
                    "description": "Unique track identifier",
                    "description_kr": "트랙 고유 ID",
                    "data_type": "INT",
                    "is_pii": False
                },
                "file_id": {
                    "original_name": "file_id",
                    "description": "Reference to signal_files.file_id",
                    "description_kr": "signal_files.file_id 참조",
                    "data_type": "INT",
                    "is_pii": False
                },
                "track_name": {
                    "original_name": "track_name",
                    "description": "Original track name from signal file",
                    "description_kr": "신호 파일의 원본 트랙명",
                    "data_type": "VARCHAR",
                    "is_pii": False
                },
                "sample_rate": {
                    "original_name": "sample_rate",
                    "description": "Sampling rate in Hz",
                    "description_kr": "샘플링 레이트 (Hz)",
                    "data_type": "FLOAT",
                    "unit": "Hz",
                    "is_pii": False
                },
                "unit": {
                    "original_name": "unit",
                    "description": "Measurement unit (mV, mmHg, %, etc.)",
                    "description_kr": "측정 단위",
                    "data_type": "VARCHAR",
                    "is_pii": False
                },
                "inferred_name": {
                    "original_name": "inferred_name",
                    "description": "LLM-inferred human-readable track name",
                    "description_kr": "LLM이 추론한 트랙 이름",
                    "data_type": "VARCHAR",
                    "is_pii": False
                },
                "clinical_category": {
                    "original_name": "clinical_category",
                    "description": "Clinical category (cardiac, respiratory, etc.)",
                    "description_kr": "임상 카테고리",
                    "data_type": "VARCHAR",
                    "is_pii": False
                }
            }
            
            # Neo4j에 저장
            ontology_manager = get_ontology_manager()
            ontology_manager.save(ontology)
            print(f"   ✅ Ontology updated")
        
        print("="*80)
        
        return {
            "ontology_context": ontology,
            "logs": [
                f"📡 [Indexer] Signal file registered: file_id={file_id}, {id_column}={id_value}",
                f"💾 [Indexer] Stored in normalized tables (signal_files + signal_tracks)",
                f"🔍 [Indexer] {tracks_inserted} tracks analyzed by LLM",
                "✅ [Done] Signal file indexing complete."
            ]
        }
        
    except Exception as e:
        import traceback
        print(f"\n❌ [Error] Vital file indexing failed: {str(e)}")
        traceback.print_exc()
        print("="*80)
        
        return {
            "logs": [f"❌ [Indexer] Vital file indexing failed: {str(e)}"],
            "error_message": str(e)
        }


def _analyze_tracks_with_llm(tracks: List[str], column_details: Dict) -> Dict[str, Dict]:
    """
    [LLM Decides] Signal 트랙의 의미를 LLM이 분석
    
    TabularProcessor의 _analyze_columns_with_llm과 동일한 패턴:
    - Rule이 수집한 트랙 정보 (이름, 단위, 샘플레이트)를 LLM에게 전달
    - LLM이 각 트랙의 의미, 카테고리, 설명을 추론
    
    Args:
        tracks: 트랙명 리스트
        column_details: 트랙별 상세 정보 {track_name: {unit, sample_rate, ...}}
    
    Returns:
        {track_name: {inferred_name, description, clinical_category, ...}}
    """
    if not tracks:
        return {}
    
    # 트랙 정보 요약 (LLM 프롬프트용)
    tracks_summary = ""
    for track_name in tracks[:20]:  # 최대 20개만 분석 (토큰 절약)
        details = column_details.get(track_name, {})
        unit = details.get("unit", "N/A")
        sr = details.get("sample_rate", 0)
        col_type = details.get("column_type", "unknown")
        
        tracks_summary += f"- Track: '{track_name}' | Unit: {unit} | Sample Rate: {sr}Hz | Type: {col_type}\n"
    
    if len(tracks) > 20:
        tracks_summary += f"  ... and {len(tracks) - 20} more tracks\n"
    
    prompt = f"""You are a Medical Signal Processing Expert.
Analyze the following signal tracks and provide detailed metadata for each.

[SIGNAL TRACKS - Pre-processed by Rules]
{tracks_summary}

[TASK]
For each track, determine:
1. **inferred_name**: Human-readable name (e.g., 'SNUADC/ECG_II' → 'Lead II ECG')
2. **description**: Brief medical description
3. **clinical_category**: One of the following categories:
   - cardiac_waveform: ECG, ABP waveforms
   - cardiac_vital: HR, BP values
   - respiratory: SpO2, RR, EtCO2
   - neurological: EEG, BIS, EMG
   - temperature: Body temperature
   - anesthesia: MAC, Agent concentration
   - other: Unknown or miscellaneous

[CLINICAL HINTS]
- 'ECG', 'EKG' → cardiac_waveform (Electrocardiogram)
- 'ART', 'ABP', 'IBP' → cardiac_waveform (Arterial Blood Pressure)
- 'NIBP', 'SBP', 'DBP', 'MBP' → cardiac_vital (Non-invasive BP)
- 'SpO2', 'SaO2' → respiratory (Oxygen Saturation)
- 'RR', 'RESP' → respiratory (Respiratory Rate)
- 'EtCO2', 'ETCO2' → respiratory (End-tidal CO2)
- 'BIS', 'SEF' → neurological (Brain monitoring)
- 'MAC', 'FiO2', 'Agent' → anesthesia

[RESPONSE FORMAT - JSON]
{{
    "tracks": {{
        "SNUADC/ECG_II": {{
            "inferred_name": "Lead II ECG",
            "description": "Standard limb lead II electrocardiogram waveform",
            "clinical_category": "cardiac_waveform"
        }},
        "Solar8000/SpO2": {{
            "inferred_name": "Oxygen Saturation",
            "description": "Peripheral oxygen saturation measured by pulse oximetry",
            "clinical_category": "respiratory"
        }}
    }}
}}

Analyze ALL tracks provided. Be concise but accurate.
"""
    
    try:
        result = llm_client.ask_json(prompt)
        
        # 결과 파싱
        tracks_analysis = result.get("tracks", {})
        
        # 분석되지 않은 트랙에 대해 기본값 설정
        for track_name in tracks:
            if track_name not in tracks_analysis:
                tracks_analysis[track_name] = {
                    "inferred_name": track_name,
                    "description": "",
                    "clinical_category": "other"
                }
        
        print(f"   🧠 [LLM] Analyzed {len(tracks_analysis)} tracks")
        return tracks_analysis
        
    except Exception as e:
        print(f"   ⚠️ [LLM] Track analysis failed: {e}")
        # LLM 실패 시 기본값 반환
        return {track_name: {
            "inferred_name": track_name,
            "description": "",
            "clinical_category": "other"
        } for track_name in tracks}


def _analyze_columns_with_llm(columns: List[str], sample_data: Any, anchor_context: Dict) -> List[ColumnSchema]:
    """
    [Helper] Analyze column meaning, data type, PII status, units, etc. using LLM
    
    [Enhancements] Column metadata enrichment:
    - full_name: Abbreviation expansion (e.g., sbp → Systolic Blood Pressure)
    - unit: Measurement unit (e.g., mmHg, kg, cm)
    - typical_range: Medical normal range
    - sample_values: Actual sample values
    """
    # Context summary for LLM
    prompt = f"""
    You are a Medical Data Ontologist specializing in clinical database design.
    Analyze the columns of a medical dataset and provide DETAILED metadata.
    
    [Context]
    - Patient Identifier (Anchor): {anchor_context.get('column_name')}
    - Is Time Series: {anchor_context.get('is_time_series')}
    
    [Columns to Analyze]
    """
    
    # If sample_data is a list (from TabularProcessor)
    if isinstance(sample_data, list):
        for col_detail in sample_data:
            col_name = col_detail.get('column_name', 'unknown')
            col_type = col_detail.get('column_type', 'unknown')
            samples = col_detail.get('samples', [])
            
            if col_type == 'categorical':
                unique_vals = col_detail.get('unique_values', [])
                prompt += f"- Column: '{col_name}' | Type: CATEGORICAL | Unique Values: {unique_vals}\n"
            else:
                min_val = col_detail.get('min', 'N/A')
                max_val = col_detail.get('max', 'N/A')
                prompt += f"- Column: '{col_name}' | Type: CONTINUOUS | Range: [{min_val}, {max_val}] | Samples: {samples}\n"
    # If sample_data is a dictionary (backward compatibility)
    elif isinstance(sample_data, dict):
        for col in columns:
            details = sample_data.get(col, {})
            samples = details.get("sample_values", [])
            prompt += f"- Column: '{col}', Samples: {samples}\n"
    else:
        # If neither, provide column names only
        for col in columns:
            prompt += f"- Column: '{col}'\n"

    prompt += """
    [Task]
    For EACH column, provide a JSON object with DETAILED metadata:
    
    1. original_name: The exact column name as provided (REQUIRED)
    2. inferred_name: Human-readable name (e.g., 'sbp' → 'Systolic Blood Pressure')
    3. full_name: Full medical term without abbreviation (e.g., 'Systolic Blood Pressure')
    4. description: Brief medical description (what does this column measure?)
    5. description_kr: Korean description for Korean users (한글 설명)
    6. data_type: SQL compatible type (VARCHAR, INT, FLOAT, TIMESTAMP, BOOLEAN)
    7. unit: Measurement unit if applicable (e.g., "mmHg", "kg", "mg/dL", "bpm", "°C", null if N/A)
    8. typical_range: Normal/typical value range in medical context (e.g., "90-140" for systolic BP, null if N/A)
    9. is_pii: Boolean (true if it contains name, phone, address, social security number)
    10. confidence: 0.0 to 1.0 (how confident are you about this analysis?)
    
    [Examples]
    - 'sbp' → {"original_name": "sbp", "inferred_name": "Systolic BP", "full_name": "Systolic Blood Pressure", 
               "description": "Peak arterial pressure during heart contraction", "description_kr": "심장 수축시 최고 동맥압 (수축기 혈압)",
               "data_type": "FLOAT", "unit": "mmHg", "typical_range": "90-140", "is_pii": false, "confidence": 0.95}
    - 'hr' → {"original_name": "hr", "inferred_name": "Heart Rate", "full_name": "Heart Rate",
              "description": "Number of heartbeats per minute", "description_kr": "분당 심박수",
              "data_type": "INT", "unit": "bpm", "typical_range": "60-100", "is_pii": false, "confidence": 0.95}
    - 'age' → {"original_name": "age", "inferred_name": "Patient Age", "full_name": "Patient Age",
               "description": "Age of the patient", "description_kr": "환자 나이",
               "data_type": "INT", "unit": "years", "typical_range": "0-120", "is_pii": false, "confidence": 0.90}

    Respond with a JSON object: {"columns": [list of column objects]}
    """
    
    # LLM call
    response = llm_client.ask_json(prompt)
    
    # Check if response is list or dict (wrapping list) and parse
    if isinstance(response, dict) and "columns" in response:
        result_list = response["columns"]
    elif isinstance(response, list):
        result_list = response
    else:
        result_list = []  # Error handling needed

    # Map results
    final_schema = []
    for idx, item in enumerate(result_list):
        # Use original_name if available, otherwise match by index
        original = item.get("original_name") or (columns[idx] if idx < len(columns) else "unknown")
        
        final_schema.append({
            "original_name": original,
            "inferred_name": item.get("inferred_name", original),
            "full_name": item.get("full_name", item.get("inferred_name", original)),
            "description": item.get("description", ""),
            "description_kr": item.get("description_kr", ""),
            "data_type": item.get("data_type", "VARCHAR"),
            "unit": item.get("unit"),  # None if not applicable
            "typical_range": item.get("typical_range"),  # None if not applicable
            "standard_concept_id": None, 
            "is_pii": item.get("is_pii", False),
            "confidence": item.get("confidence", 0.5)
        })
        
    return final_schema


def _compare_with_global_context(local_metadata: Dict, local_anchor_info: Dict, project_context: Dict) -> Dict[str, Any]:
    """
    [Helper] Compare current file data with project Global Anchor info (using LLM)
    
    ⭐ [NEW] Check ontology relationships for indirect connections
    e.g., lab_data without subjectid can link to clinical_data.subjectid via caseid
    """
    master_name = project_context["master_anchor_name"]
    local_cols = local_metadata.get("columns", [])
    local_candidate = local_anchor_info.get("target_column")
    
    # Extract table name from current filename
    file_path = local_metadata.get("file_path", "")
    current_table = os.path.basename(file_path).replace(".csv", "").replace(".CSV", "")
    
    # 1. 이름이 완전히 같은 경우 (Fast Path)
    if master_name in local_cols:
        return {"status": "MATCH", "target_column": master_name, "message": "Exact name match"}

    # ⭐ [NEW] 2. 온톨로지 기반 간접 연결 확인
    indirect_link = _check_indirect_link_via_ontology(
        current_table=current_table,
        local_cols=local_cols,
        master_anchor=master_name
    )
    
    if indirect_link:
        return {
            "status": "INDIRECT_LINK",
            "target_column": indirect_link["via_column"],
            "via_table": indirect_link["via_table"],
            "master_anchor": master_name,
            "message": indirect_link["message"]
        }

    # 3. 로컬 후보가 없는 경우 (Processor가 못 찾음)
    if not local_candidate:
        return {
            "status": "MISSING",
            "target_column": None,
            "message": f"No anchor candidate found in local file. Master anchor '{master_name}' not found in columns: {local_cols}"
        }

    # 3. LLM을 통한 의미론적 비교
    prompt = f"""
    You are a Medical Data Integration Agent.
    Check if the new file contains the Project's Master Anchor (Patient ID).

    [Project Context / Global Master]
    - Master Anchor Name: '{master_name}'
    - Known Aliases: {project_context.get('known_aliases')}
    
    [New File Info]
    - Candidate Column found by AI: '{local_candidate}'
    - All Columns in file: {local_cols}
    
    [Task]
    Determine if any column in the new file represents the same 'Patient ID' entity as the Global Master.
    - If the candidate '{local_candidate}' is a synonym for '{master_name}' (e.g. 'pid' vs 'subject_id'), return MATCH.
    - If another column in 'All Columns' looks like the ID, return MATCH with that column.
    - If you cannot find a matching column, return MISSING.
    - If you are unsure, return CONFLICT.

    Respond with JSON:
    {{
        "status": "MATCH" or "MISSING" or "CONFLICT",
        "target_column": "name_of_column_in_new_file" (or null if missing),
        "message": "Reasoning for the decision"
    }}
    """
    
    try:
        result = llm_client.ask_json(prompt)
        
        # LLM 응답 검증 및 정규화
        if not isinstance(result, dict):
            return {"status": "CONFLICT", "target_column": None, "message": "LLM returned invalid format"}
        
        status = result.get("status", "CONFLICT").upper()
        if status not in ["MATCH", "MISSING", "CONFLICT"]:
            status = "CONFLICT"
        
        return {
            "status": status,
            "target_column": result.get("target_column"),
            "message": result.get("message", "No explanation provided")
        }
        
    except Exception as e:
        return {"status": "CONFLICT", "target_column": None, "message": f"Error during anchor comparison: {str(e)}"}


# ============================================================================
# Indirect Link Check (Ontology-based)
# ============================================================================

def _check_indirect_link_via_ontology(current_table: str, local_cols: list, master_anchor: str) -> Optional[Dict]:
    """
    ⭐ [NEW] Check ontology relationships for indirect connections
    
    Example:
    - lab_data does not have subjectid
    - But ontology has "lab_data.caseid → clinical_data.caseid" relationship
    - clinical_data has subjectid
    - Therefore lab_data is indirectly connected to subjectid via caseid
    
    Returns:
        Indirect link info dict or None
    """
    try:
        # Load ontology
        ontology = ontology_manager.load()
        if not ontology:
            return None
        
        relationships = ontology.get("relationships", [])
        file_tags = ontology.get("file_tags", {})
        
        print(f"\n🔗 [Indirect Link Check] {current_table}")
        print(f"   - Ontology relationships: {len(relationships)}")
        
        # Find relationships where current table is source
        for rel in relationships:
            source_table = rel.get("source_table", "")
            target_table = rel.get("target_table", "")
            source_column = rel.get("source_column", "")
            target_column = rel.get("target_column", "")
            
            # If current_table is source
            if current_table.lower() in source_table.lower() or source_table.lower() in current_table.lower():
                # Check if link column exists in current file
                if source_column in local_cols:
                    # Check if target_table has master_anchor
                    target_has_master = _check_table_has_column(file_tags, target_table, master_anchor)
                    
                    if target_has_master:
                        message = (
                            f"✅ Indirect link found! "
                            f"'{current_table}.{source_column}' → '{target_table}.{target_column}' relation "
                            f"connects to '{master_anchor}'"
                        )
                        print(f"   {message}")
                        
                        return {
                            "via_column": source_column,
                            "via_table": target_table,
                            "via_relation": f"{source_table}.{source_column} → {target_table}.{target_column}",
                            "message": message
                        }
        
        print(f"   - No indirect link found")
        return None
        
    except Exception as e:
        print(f"   ⚠️ Indirect link check error: {e}")
        return None


def _check_table_has_column(file_tags: Dict, table_name: str, column_name: str) -> bool:
    """
    Check if a specific table has a specific column in file_tags
    """
    for file_path, tag_info in file_tags.items():
        # Extract table name from filename
        file_table = os.path.basename(file_path).replace(".csv", "").replace(".CSV", "")
        
        if table_name.lower() in file_table.lower() or file_table.lower() in table_name.lower():
            columns = tag_info.get("columns", [])
            if column_name in columns:
                return True
    
    return False


# ============================================================================
# Ontology Builder Functions (Phase 0-1)
# ============================================================================

def _collect_negative_evidence(col_name: str, samples: list, unique_vals: list) -> dict:
    """
    [Rule] Collect negative evidence (detect data quality issues)
    
    Args:
        col_name: Column name
        samples: Sample values list
        unique_vals: Unique values list
    
    Returns:
        Negative evidence dictionary
    """
    import numpy as np
    
    total = len(samples)
    unique = len(unique_vals)
    
    # Calculate nulls
    null_count = sum(
        1 for s in samples 
        if s is None or s == '' or (isinstance(s, float) and np.isnan(s))
    )
    
    negative_evidence = []
    
    # 1. Near unique but has duplicates (possible data error)
    if total > 0 and unique / total > 0.95 and unique != total:
        dup_rate = (total - unique) / total
        negative_evidence.append({
            "type": "near_unique_with_duplicates",
            "detail": f"{unique/total:.1%} unique BUT {dup_rate:.1%} duplicates - possible data error",
            "severity": "medium"
        })
    
    # 2. ID-like but has nulls (cannot be PK)
    if 'id' in col_name.lower() and null_count > 0:
        null_rate = null_count / total
        negative_evidence.append({
            "type": "identifier_with_nulls",
            "detail": f"Column name suggests ID BUT {null_rate:.1%} null values",
            "severity": "high" if null_rate > 0.1 else "low"
        })
    
    # 3. Cardinality too high (possible free text)
    if unique > 100:
        negative_evidence.append({
            "type": "high_cardinality",
            "detail": f"{unique} unique values - might be free text, not categorical",
            "severity": "low"
        })
    
    return {
        "has_issues": len(negative_evidence) > 0,
        "issues": negative_evidence,
        "null_ratio": null_count / total if total > 0 else 0.0
    }


def _summarize_long_values(values: list, max_length: int = 50) -> list:
    """
    [Rule] Summarize long text (Context Window management)
    
    Args:
        values: Values list
        max_length: Maximum length (summarize if exceeded)
    
    Returns:
        Summarized values list
    """
    summarized = []
    
    for val in values:
        val_str = str(val)
        
        if len(val_str) > max_length:
            # Replace with meta info (save tokens)
            preview = val_str[:20].replace('\n', ' ')
            summarized.append(f"[Text: {len(val_str)} chars, starts='{preview}...']")
        else:
            summarized.append(val_str)
    
    return summarized


def _parse_metadata_content(file_path: str) -> dict:
    """
    [Rule] Parse metadata file (CSV → Dictionary)
    
    Args:
        file_path: Metadata file path
    
    Returns:
        definitions dictionary {parameter: description}
    """
    import pandas as pd
    
    definitions = {}
    
    try:
        df = pd.read_csv(file_path)
        
        # Common metadata structure: [Parameter/Name, Description, ...]
        if len(df.columns) >= 2:
            key_col = df.columns[0]
            desc_col = df.columns[1]
            
            for _, row in df.iterrows():
                key = str(row[key_col]).strip()
                desc = str(row[desc_col]).strip()
                
                # Combine additional info (Unit, Type, etc.)
                extra_info = []
                for col in df.columns[2:]:
                    val = row[col]
                    if pd.notna(val) and str(val).strip():
                        extra_info.append(f"{col}={val}")
                
                if extra_info:
                    desc += " | " + " | ".join(extra_info)
                
                definitions[key] = desc
        
        return definitions
        
    except Exception as e:
        print(f"❌ [Parse Error] {file_path}: {e}")
        return {}


def _build_metadata_detection_context(file_path: str, metadata: dict) -> dict:
    """
    [Rule] Build context for metadata detection (preprocessing)
    
    Args:
        file_path: File path
        metadata: raw_metadata extracted by Processor
    
    Returns:
        Context to provide to LLM
    """
    basename = os.path.basename(file_path)
    name_without_ext = os.path.splitext(basename)[0]
    extension = os.path.splitext(basename)[1]
    
    # Rule: Parse filename
    parts = name_without_ext.split('_')
    base_name = parts[0] if parts else name_without_ext
    
    columns = metadata.get("columns", [])
    column_details = metadata.get("column_details", [])
    
    # Rule: Organize sample data
    sample_summary = []
    total_text_length = 0
    
    # [FIX] column_details가 dict인 경우 (Signal 파일) vs list인 경우 (Tabular 파일) 처리
    if isinstance(column_details, dict):
        # dict인 경우: values를 list로 변환
        column_details_list = list(column_details.values())[:5]
    elif isinstance(column_details, list):
        column_details_list = column_details[:5]
    else:
        column_details_list = []
    
    for col_info in column_details_list:  # First 5 columns only
        # col_info가 dict가 아닌 경우 스킵
        if not isinstance(col_info, dict):
            continue
        col_name = col_info.get('column_name', 'unknown')
        samples = col_info.get('samples', [])
        col_type = col_info.get('column_type', 'unknown')
        
        # If categorical, also provide unique values
        if col_type == 'categorical':
            unique_vals = col_info.get('unique_values', [])[:20]
            # Summarize long text (Rule)
            unique_vals_summarized = _summarize_long_values(unique_vals, max_length=50)
        else:
            unique_vals = samples[:10]
            unique_vals_summarized = _summarize_long_values(unique_vals, max_length=50)
        
        # Rule: Calculate average text length
        avg_length = 0.0
        if samples:
            text_lengths = [len(str(s)) for s in samples]
            avg_length = sum(text_lengths) / len(text_lengths)
            total_text_length += avg_length
        
        # [NEW] Collect negative evidence (Rule)
        negative_evidence = _collect_negative_evidence(col_name, samples, unique_vals if unique_vals else [])
        
        # Summarize samples too
        samples_summarized = _summarize_long_values(samples[:3], max_length=50)
        
        sample_summary.append({
            "column": col_name,
            "type": col_type,
            "samples": samples_summarized,
            "unique_values": unique_vals_summarized,
            "avg_text_length": round(avg_length, 1),
            "null_ratio": negative_evidence.get("null_ratio", 0.0),  # [NEW]
            "negative_evidence": negative_evidence.get("issues", [])  # [NEW]
        })
    
    # Estimate context size
    context_size = len(json.dumps(sample_summary))
    
    # If too large, reduce samples (Rule)
    if context_size > 3000:
        sample_summary = sample_summary[:3]
        context_size = len(json.dumps(sample_summary))
    
    return {
        "filename": basename,
        "name_parts": parts,
        "base_name": base_name,
        "extension": extension,
        "columns": columns,
        "num_columns": len(columns),
        "sample_data": sample_summary,
        "avg_text_length_overall": round(total_text_length / max(len(sample_summary), 1), 1),
        "context_size_bytes": context_size
    }


def _ask_llm_is_metadata(context: dict) -> dict:
    """
    [LLM] Determine if file is metadata
    
    Args:
        context: Pre-processed context by Rules
    
    Returns:
        Judgment result {is_metadata, confidence, reasoning, indicators}
    """
    # Use global cache
    # Check cache
    cached = llm_cache.get("metadata_detection", context)
    if cached:
        return cached
    
    # LLM prompt
    prompt = f"""
You are a Data Classification Expert.

I have pre-processed file information using rules. Based on these facts, determine if this is METADATA or TRANSACTIONAL DATA.

[PRE-PROCESSED FILE INFORMATION - Extracted by Rules]
Filename: {context['filename']}
Parsed Name Parts: {context['name_parts']}  (parsed by Rule)
Base Name: {context['base_name']}
Extension: {context['extension']}
Number of Columns: {context['num_columns']}
Columns: {context['columns']}

[PRE-PROCESSED SAMPLE DATA - Extracted by Rules]
{json.dumps(context['sample_data'], indent=2)}
(Note: avg_text_length, unique_values, null_ratio, and negative_evidence were calculated by rules)

[IMPORTANT - Check Negative Evidence]
Each column has "negative_evidence" field showing data quality issues if any:
- near_unique_with_duplicates: Almost unique but has some duplicates
- identifier_with_nulls: Column name suggests ID but has null values
- high_cardinality: Too many unique values for categorical

Use this information to improve your judgment.

[DEFINITION]
- METADATA file: Describes OTHER data (e.g., column definitions, parameter lists, codebooks)
  * Contains descriptive text about columns/variables
  * Usually has structure like: [Name/ID, Description, Unit, Type]
  * Content is documentation, not measurements/transactions
  
- TRANSACTIONAL DATA: Actual records/measurements
  * Contains patient records, lab results, events, etc.
  * Values are data points, not descriptions

[YOUR TASK - Interpret Pre-processed Information]
Using the parsed filename and pre-calculated statistics, classify this file:

1. **Filename Analysis**:
   - Look at name_parts: if contains "parameters", "dict", "definition" → likely metadata
   - Look at base_name: what domain does it represent?

2. **Column Structure**:
   - Is it Key-Value format? (e.g., [Parameter, Description, Unit])
   - Or wide transactional format? (many columns with diverse types)

3. **Sample Content Analysis**:
   - Check avg_text_length: Long text (>30 chars) → likely descriptions
   - Check unique_values: Are they codes/IDs or explanatory text?

IMPORTANT: I already did the heavy lifting (parsing, statistics). 
You interpret the MEANING of these pre-processed facts.

[OUTPUT FORMAT - JSON ONLY]
{{
    "is_metadata": true or false,
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation based on filename, structure, and content",
    "indicators": {{
        "filename_hint": "strong/weak/none",
        "structure_hint": "dictionary-like/tabular/unclear",
        "content_type": "descriptive/transactional/mixed"
    }}
}}
"""
    
    try:
        result = llm_client.ask_json(prompt)
        
        # Save to cache
        llm_cache.set("metadata_detection", context, result)
        
        # Validate confidence
        confidence = result.get("confidence", 0.0)
        if confidence < HumanReviewConfig.METADATA_DETECTION_CONFIDENCE_THRESHOLD:
            print(f"⚠️  [Metadata Detection] Low confidence ({confidence:.2%})")
            print(f"    Reasoning: {result.get('reasoning', 'N/A')[:100]}...")
        
        return result
        
    except Exception as e:
        print(f"❌ [Metadata Detection] LLM Error: {e}")
        # Fallback
        return {
            "is_metadata": False,  # Conservative default
            "confidence": 0.0,
            "reasoning": f"LLM error: {str(e)}",
            "indicators": {},
            "needs_human_review": True
        }


def _find_common_columns(current_cols: List[str], existing_tables: dict) -> List[dict]:
    """
    [Rule] Find common columns between current table and existing tables (FK candidate search)
    
    Args:
        current_cols: Column list of current table
        existing_tables: Existing tables info {table_name: {columns: [...], ...}}
    
    Returns:
        FK candidate list
    """
    candidates = []
    
    for table_name, table_info in existing_tables.items():
        existing_cols = table_info.get("columns", [])
        
        # Find exact matching columns (Rule - exact match)
        common_cols = set(current_cols) & set(existing_cols)
        
        for common_col in common_cols:
            candidates.append({
                "column_name": common_col,
                "current_table": "new_table",
                "existing_table": table_name,
                "match_type": "exact_name",
                "confidence_hint": 0.9  # Same name = high probability of FK
            })
    
    # Find similar names (Rule - simple string normalization)
    # e.g., patient_id vs patientid, subjectid vs subject_id
    for table_name, table_info in existing_tables.items():
        existing_cols = table_info.get("columns", [])
        
        for curr_col in current_cols:
            for exist_col in existing_cols:
                # Compare after removing underscores (Rule)
                curr_normalized = curr_col.replace('_', '').lower()
                exist_normalized = exist_col.replace('_', '').lower()
                
                if curr_normalized == exist_normalized and curr_col != exist_col:
                    candidates.append({
                        "current_col": curr_col,
                        "existing_col": exist_col,
                        "existing_table": table_name,
                        "match_type": "similar_name",
                        "confidence_hint": 0.7  # Similar = medium probability
                    })
    
    return candidates


def _extract_filename_hints(filename: str) -> dict:
    """
    [Rule + LLM] Extract semantic hints from filename
    
    Step 1 (Rule): Analyze filename structure
    Step 2 (LLM): Infer meaning (Entity Type, Level)
    
    Args:
        filename: Filename or file path
    
    Returns:
        Filename hints dictionary
    """
    # Use global cache
    
    # === Step 1: Rule-based filename parsing ===
    basename = os.path.basename(filename)
    name_without_ext = os.path.splitext(basename)[0]
    extension = os.path.splitext(basename)[1]
    
    # Split by underscore (Rule)
    parts = name_without_ext.split('_')
    base_name = parts[0] if parts else name_without_ext
    
    # Extract prefix/suffix (Rule)
    prefix = parts[0] if len(parts) >= 2 else None
    suffix = parts[-1] if len(parts) >= 2 else None
    
    # Structure info extracted by Rule
    parsed_structure = {
        "original_filename": basename,
        "name_without_ext": name_without_ext,
        "extension": extension,
        "parts": parts,
        "base_name": base_name,
        "prefix": prefix,
        "suffix": suffix,
        "has_underscore": '_' in name_without_ext,
        "num_parts": len(parts)
    }
    
    # === Step 2: LLM-based semantic inference ===
    
    # Check cache
    cached = llm_cache.get("filename_hints", parsed_structure)
    if cached:
        return cached
    
    # LLM prompt
    prompt = f"""
You are a Data Architecture Analyst.

I have parsed the filename structure using rules. Based on this, infer the semantic meaning.

[PARSED FILENAME STRUCTURE - Extracted by Rules]
{json.dumps(parsed_structure, indent=2)}

[YOUR TASK - Semantic Interpretation]
Using the PARSED STRUCTURE, infer:

1. **Entity Type**: What domain entity does base_name represent?
   - Examples: "lab" → Laboratory, "patient" → Patient, "clinical" → Case/Clinical
   - Use domain knowledge (medical, financial, etc.)

2. **Scope**: What is the data scope?
   - individual: Patient, Subject
   - event: Case, Admission, Visit, Stay
   - measurement: Lab, Vital, Sensor
   - treatment: Medication, Procedure

3. **Suggested Hierarchy Level**: (1=highest, 5=lowest)
   - Level 1: Patient, Subject
   - Level 2: Case, Admission, Visit
   - Level 3: Sub-event (ICU Stay)
   - Level 4: Measurement (Lab, Vital)
   - Level 5: Detail

4. **Data Type Indicator**: Based on suffix
   - "data", "records", "events" → transactional
   - "parameters", "dict", "info" → metadata
   - "master", "dim" → reference

5. **Related File Patterns**: Predict related files
   - If "lab_data", likely has "lab_parameters" or "lab_dict"

[OUTPUT FORMAT - JSON]
{{
    "entity_type": "Laboratory" or null,
    "scope": "measurement" or null,
    "suggested_level": 4 or null,
    "data_type_indicator": "transactional" or "metadata",
    "related_file_patterns": ["lab_parameters", "lab_dict"],
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation"
}}
"""
    
    try:
        # Use global llm_client
        hints = llm_client.ask_json(prompt)
        
        # Add default fields
        hints["filename"] = basename
        hints["base_name"] = base_name
        hints["parts"] = parts
        
        # Save to cache
        llm_cache.set("filename_hints", parsed_structure, hints)
        
        # Validate confidence
        if hints.get("confidence", 1.0) < HumanReviewConfig.FILENAME_ANALYSIS_CONFIDENCE_THRESHOLD:
            print(f"⚠️  [Filename Analysis] Low confidence ({hints.get('confidence'):.2%}) for {basename}")
        
        return hints
        
    except Exception as e:
        # On LLM failure, return minimal info
        print(f"❌ [Filename Analysis] LLM Error: {e}")
        return {
            "filename": basename,
            "base_name": base_name,
            "parts": parts,
            "entity_type": None,
            "scope": None,
            "suggested_level": None,
            "data_type_indicator": None,
            "related_file_patterns": [],
            "confidence": 0.0,
            "error": str(e)
        }


def _summarize_existing_tables(ontology_context: dict, processed_files_data: dict = None) -> dict:
    """
    [Rule] Summarize existing table info (for LLM)
    
    Args:
        ontology_context: Current ontology context
        processed_files_data: Column info of processed files (optional)
    
    Returns:
        Table summary dictionary
    """
    tables = {}
    
    # file_tags에서 데이터 파일들만 추출
    for file_path, tag_info in ontology_context.get("file_tags", {}).items():
        if tag_info.get("type") == "transactional_data":
            table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_")
            
            # 컬럼 정보 (저장된 것이 있으면 사용)
            columns = tag_info.get("columns", [])
            
            # 또는 processed_files_data에서 가져오기
            if not columns and processed_files_data:
                columns = processed_files_data.get(file_path, {}).get("columns", [])
            
            tables[table_name] = {
                "file_path": file_path,
                "type": tag_info.get("type"),
                "columns": columns
            }
    
    return tables


def _infer_relationships_with_llm(
    current_table_name: str,
    current_cols: List[str],
    ontology_context: dict,
    current_metadata: dict
) -> dict:
    """
    [Rule 전처리 + LLM 판단] 테이블 간 관계 추론
    
    Args:
        current_table_name: 현재 테이블 이름
        current_cols: 현재 테이블 컬럼 리스트
        ontology_context: 온톨로지 컨텍스트
        current_metadata: 현재 파일의 raw_metadata (카디널리티 분석용)
    
    Returns:
        {relationships: [...], hierarchy: [...], reasoning: "..."}
    """
    # 전역 캐시 및 llm_client 사용
    
    # === 1단계: Rule Prepares ===
    
    # 파일명 힌트 (Rule + LLM)
    filename_hints = _extract_filename_hints(current_table_name)
    
    # 기존 테이블 요약
    existing_tables = _summarize_existing_tables(ontology_context)
    
    # FK 후보 찾기 (Rule)
    fk_candidates = _find_common_columns(current_cols, existing_tables)
    
    # 카디널리티 분석 (현재는 기본 통계만)
    cardinality_hints = {}
    column_details = current_metadata.get("column_details", [])
    
    for col_info in column_details:
        col_name = col_info.get('column_name')
        samples = col_info.get('samples', [])
        
        if samples:
            unique_count = len(set(samples))
            total_count = len(samples)
            ratio = unique_count / total_count if total_count > 0 else 0
            
            cardinality_hints[col_name] = {
                "uniqueness_ratio": round(ratio, 2),
                "pattern": "UNIQUE" if ratio > 0.95 else "REPEATED"
            }
    
    # === 2단계: LLM Decides ===
    
    # 컨텍스트 구성
    llm_context = {
        "current_table": current_table_name,
        "current_cols": current_cols,
        "filename_hints": filename_hints,
        "fk_candidates": fk_candidates,
        "cardinality": cardinality_hints,
        "existing_tables": existing_tables,
        "definitions": ontology_context.get("definitions", {})
    }
    
    # 캐시 확인
    cached = llm_cache.get("relationship_inference", llm_context)
    if cached:
        print(f"✅ [Cache Hit] 관계 추론 캐시 사용")
        return cached
    
    # LLM 프롬프트
    prompt = f"""
You are a Database Schema Architect for Medical Data Integration.

I have pre-processed data using rules. Infer table relationships.

[PRE-PROCESSED INFORMATION]

1. NEW TABLE:
Name: {current_table_name}
Columns: {current_cols}

2. FILENAME HINTS (Parsed by Rule + LLM):
{json.dumps(filename_hints, indent=2)}

3. FK CANDIDATES (Found by Rules - Common Columns):
{json.dumps(fk_candidates, indent=2)}

4. CARDINALITY (Calculated by Rules):
{json.dumps(cardinality_hints, indent=2)}

5. EXISTING TABLES:
{json.dumps(existing_tables, indent=2)}

6. ONTOLOGY DEFINITIONS (Medical Terms):
Available terms: {len(llm_context['definitions'])} definitions
Example: caseid, subjectid, alb, wbc, etc.

[YOUR TASK]

1. **Validate FK Candidates**:
   - Check if common columns are truly Foreign Keys
   - Use CARDINALITY: if REPEATED → likely FK
   - Use FILENAME: if base_names related → likely FK

2. **Determine Relationship Type**:
   - 1:1, 1:N, N:1, or M:N based on cardinality

3. **Infer Hierarchy**:
   - Which entity is parent? (more abstract)
   - Which is child? (more specific)
   - Use domain knowledge

[OUTPUT FORMAT - JSON]
{{
  "relationships": [
    {{
      "source_table": "{current_table_name}",
      "target_table": "existing_table_name",
      "source_column": "column_name",
      "target_column": "column_name",
      "relation_type": "N:1",
      "confidence": 0.95,
      "description": "Brief explanation",
      "llm_inferred": true
    }}
  ],
  "hierarchy": [
    {{
      "level": 1,
      "entity_name": "Patient",
      "anchor_column": "subjectid",
      "mapping_table": null,
      "confidence": 0.9
    }}
  ],
  "reasoning": "Overall explanation"
}}

If no relationships found, return empty lists.
Be conservative: confidence < 0.8 if unsure.
"""
    
    try:
        result = llm_client.ask_json(prompt)
        
        # 캐시 저장
        llm_cache.set("relationship_inference", llm_context, result)
        
        # Confidence 검증
        rels = result.get("relationships", [])
        low_conf_rels = [r for r in rels if r.get("confidence", 0) < HumanReviewConfig.RELATIONSHIP_CONFIDENCE_THRESHOLD]
        
        if low_conf_rels:
            print(f"⚠️  [Relationship] Low confidence for {len(low_conf_rels)} relationships")
        
        return result
        
    except Exception as e:
        print(f"❌ [Relationship Inference] LLM Error: {e}")
        return {
            "relationships": [],
            "hierarchy": [],
            "reasoning": f"Error: {str(e)}",
            "error": True
        }


# ============================================================================
# LLM 기반 Human Review 판단 (유연한 조건)
# ============================================================================

def _should_request_human_review(
    file_path: str,
    issue_type: str,
    context: Dict[str, Any],
    rule_based_confidence: float = 1.0
) -> Dict[str, Any]:
    """
    [Helper] Human Review가 필요한지 판단 (Rule + LLM Hybrid)
    
    Args:
        file_path: 처리 중인 파일 경로
        issue_type: 이슈 유형 ("metadata_classification", "anchor_detection", "anchor_conflict", etc.)
        context: 판단에 필요한 컨텍스트 정보
        rule_based_confidence: Rule-based 분석에서 얻은 confidence (0~1)
    
    Returns:
        {
            "needs_review": bool,
            "reason": str,
            "confidence": float,
            "suggested_question": str (optional)
        }
    """
    filename = os.path.basename(file_path)
    
    # === 1단계: Rule-based 판단 (빠르고 저렴) ===
    threshold = _get_threshold_for_issue(issue_type)
    
    rule_decision = {
        "needs_review": rule_based_confidence < threshold,
        "reason": f"Confidence {rule_based_confidence:.1%} < Threshold {threshold:.1%}",
        "confidence": rule_based_confidence
    }
    
    # LLM 판단이 비활성화되어 있으면 Rule 결과만 반환
    if not HumanReviewConfig.USE_LLM_FOR_REVIEW_DECISION:
        print(f"   [Rule-only] {issue_type}: needs_review={rule_decision['needs_review']}")
        return rule_decision
    
    # === 2단계: LLM 기반 판단 (더 유연) ===
    # Rule에서 이미 "확실히 필요"하다고 판단한 경우 LLM 호출 생략 (비용 절감)
    if rule_based_confidence < HumanReviewConfig.LLM_SKIP_CONFIDENCE_THRESHOLD:
        print(f"   [Rule] Low confidence ({rule_based_confidence:.1%}), skipping LLM check")
        return rule_decision
    
    # LLM에게 판단 요청
    llm_decision = _ask_llm_for_review_decision(
        filename=filename,
        issue_type=issue_type,
        context=context,
        rule_confidence=rule_based_confidence
    )
    
    # === 3단계: Rule과 LLM 결과 종합 ===
    # 둘 중 하나라도 "필요하다"고 하면 Human Review 요청
    final_needs_review = rule_decision["needs_review"] or llm_decision.get("needs_review", False)
    
    combined_reason = []
    if rule_decision["needs_review"]:
        combined_reason.append(f"Rule: {rule_decision['reason']}")
    if llm_decision.get("needs_review"):
        combined_reason.append(f"LLM: {llm_decision.get('reason', 'LLM recommended review')}")
    
    result = {
        "needs_review": final_needs_review,
        "reason": " | ".join(combined_reason) if combined_reason else "No issues detected",
        "confidence": rule_based_confidence,
        "llm_opinion": llm_decision.get("reason", "N/A")
    }
    
    print(f"   [Hybrid] {issue_type}: needs_review={final_needs_review}")
    print(f"            Rule={rule_decision['needs_review']}, LLM={llm_decision.get('needs_review', 'N/A')}")
    
    return result


def _get_threshold_for_issue(issue_type: str) -> float:
    """이슈 유형별 Threshold 반환"""
    thresholds = {
        "metadata_classification": HumanReviewConfig.METADATA_CONFIDENCE_THRESHOLD,
        "anchor_detection": HumanReviewConfig.ANCHOR_CONFIDENCE_THRESHOLD,
        "anchor_conflict": HumanReviewConfig.ANCHOR_CONFIDENCE_THRESHOLD,
        "general": HumanReviewConfig.FILENAME_ANALYSIS_CONFIDENCE_THRESHOLD
    }
    return thresholds.get(issue_type, HumanReviewConfig.DEFAULT_CONFIDENCE_THRESHOLD)


def _ask_llm_for_review_decision(
    filename: str,
    issue_type: str,
    context: Dict[str, Any],
    rule_confidence: float
) -> Dict[str, Any]:
    """LLM에게 Human Review 필요 여부 판단 요청"""
    
    prompt = f"""
    You are an AI assistant helping with medical data processing.
    Based on the following situation, decide if human intervention is needed.

    [Situation]
    - File: {filename}
    - Issue Type: {issue_type}
    - Rule-based Confidence: {rule_confidence:.1%}
    - Context: {json.dumps(context, ensure_ascii=False, default=str)[:500]}...

    [Issue Type Descriptions]
    - metadata_classification: Determining if file is metadata (dictionary) or actual data
    - anchor_detection: Finding the primary identifier column (e.g., patient_id)
    - anchor_conflict: Mismatch between local and global anchor columns

    [Decision Criteria]
    Return "needs_review": true if:
    1. The context shows ambiguous or conflicting information
    2. Critical decisions might affect data integrity
    3. Domain expertise is clearly needed (medical terminology, etc.)
    4. Multiple valid interpretations exist

    Return "needs_review": false if:
    1. The situation is straightforward despite low confidence
    2. Safe defaults can be applied
    3. The issue can be auto-corrected later

    Respond with JSON only:
    {{
        "needs_review": true or false,
        "reason": "Brief explanation in Korean (한국어)"
    }}
    """
    
    try:
        result = llm_client.ask_json(prompt)
        return {
            "needs_review": result.get("needs_review", False),
            "reason": result.get("reason", "LLM did not provide reason")
        }
    except Exception as e:
        print(f"   ⚠️ [LLM Review Decision] Error: {e}")
        # LLM 실패 시 Rule 결과에 의존
        return {"needs_review": False, "reason": f"LLM error: {str(e)}"}


def _parse_human_feedback_to_column(
    feedback: str,
    available_columns: List[str],
    master_anchor: Optional[str],
    file_path: str
) -> Dict[str, Any]:
    """
    [Helper] 사용자 피드백을 파싱하여 실제 컬럼명 추출
    
    입력 유형:
    1. 실제 컬럼명 (예: "caseid", "subjectid") → 그대로 반환
    2. "skip" → 스킵 액션 반환
    3. 설명 (예: "subjectID는 환자ID이고 caseID는 수술 ID야") → LLM으로 해석
    4. [NEW] 파일 타입 설명 (예: "it's actual file", "vitaldb 패키지로 열어야 함") → 특수 처리
    
    Returns:
        {"action": "use_column", "column_name": "caseid", "reasoning": "..."}
        {"action": "skip", "reasoning": "사용자가 스킵 요청"}
        {"action": "use_filename_as_id", ...}  [NEW]
    """
    feedback_lower = feedback.strip().lower()
    
    # Case 1: 스킵 요청
    if feedback_lower in ["skip", "스킵", "건너뛰기", "pass"]:
        return {"action": "skip", "reasoning": "사용자가 스킵 요청"}
    
    # [NEW] Case 1.5: .vital 파일 관련 피드백 감지
    vital_keywords = ["vital", "vitaldb", "file name is the caseid", "filename is caseid", 
                      "actual file", "actual data", "binary", "signal file"]
    if any(kw in feedback_lower for kw in vital_keywords):
        # 파일명에서 caseid 추출 시도
        basename = os.path.basename(file_path)
        name_without_ext = os.path.splitext(basename)[0]
        
        import re
        numbers = re.findall(r'\d+', name_without_ext)
        if numbers:
            caseid = int(numbers[-1])
            return {
                "action": "use_filename_as_id",
                "column_name": "caseid",
                "caseid_value": caseid,
                "reasoning": f"User indicated this is a vital file. Caseid={caseid} extracted from filename '{basename}'.",
                "user_intent": "Use filename as caseid for vital file"
            }
        else:
            return {
                "action": "use_filename_as_id",
                "column_name": "caseid",
                "caseid_value": name_without_ext,
                "reasoning": f"User indicated this is a vital file. Using filename '{name_without_ext}' as identifier.",
                "user_intent": "Use filename as identifier for vital file"
            }
    
    # [NEW] Case 2: 컬럼이 없는 경우 (signal 파일 등)
    if not available_columns:
        print(f"   → No columns available. Processing as special file type...")
        
        # 파일명에서 ID 추출 시도
        basename = os.path.basename(file_path)
        name_without_ext = os.path.splitext(basename)[0]
        
        import re
        numbers = re.findall(r'\d+', name_without_ext)
        
        if numbers:
            # 숫자가 있으면 caseid로 사용
            caseid = int(numbers[-1])
            return {
                "action": "use_filename_as_id",
                "column_name": "caseid",
                "caseid_value": caseid,
                "reasoning": f"No columns detected. Caseid={caseid} extracted from filename '{basename}'.",
                "user_intent": feedback
            }
        else:
            # 숫자가 없으면 파일명 자체를 ID로 사용
            return {
                "action": "use_filename_as_id",
                "column_name": "file_id",
                "caseid_value": name_without_ext,
                "reasoning": f"No columns detected. Using filename '{name_without_ext}' as identifier.",
                "user_intent": feedback
            }
    
    # Case 3: 실제 컬럼명과 정확히 일치
    columns_lower = [c.lower() for c in available_columns]
    if feedback_lower in columns_lower:
        # 원래 대소문자 유지
        idx = columns_lower.index(feedback_lower)
        return {
            "action": "use_column",
            "column_name": available_columns[idx],
            "reasoning": "User specified column name directly"
        }
    
    # Case 4: Description or complex input → Interpret with LLM
    print(f"   → User input is not a column name. Interpreting with LLM...")
    
    from src.utils.llm_client import get_llm_client
    
    try:
        llm_client = get_llm_client()
        
        prompt = f"""The user has provided feedback about the identifier (Anchor) column of a data file.
Interpret this feedback and determine which column should be used.

[File Information]
- Filename: {os.path.basename(file_path)}
- Available Columns: {available_columns}
- Project Master Anchor: {master_anchor or 'None'}

[User Feedback]
"{feedback}"

[Analysis Request]
1. Identify which column should be used as the Anchor based on the user's feedback.
2. If the feedback describes relationships (e.g., "A is patient ID and B is surgery ID"),
   select the most appropriate column from the file's columns.
3. Prioritize columns that can link to the Master Anchor.

[Response Format - JSON only]
{{
    "column_name": "Selected column name (from available columns list)",
    "reasoning": "Reason for selection",
    "user_intent": "Summary of user's intent"
}}"""
        
        result = llm_client.ask_json(prompt)
        
        if "error" not in result and result.get("column_name"):
            selected = result["column_name"]
            
            # 선택된 컬럼이 실제로 존재하는지 확인
            if selected.lower() in columns_lower:
                idx = columns_lower.index(selected.lower())
                return {
                    "action": "use_column",
                    "column_name": available_columns[idx],
                    "reasoning": result.get("reasoning", "LLM interpretation result"),
                    "user_intent": result.get("user_intent", feedback)
                }
        
        # LLM failed to return valid column → Use first column (safely)
        if available_columns:
            print(f"   ⚠️ LLM failed to return valid column. Using first column: {available_columns[0]}")
            return {
                "action": "use_column",
                "column_name": available_columns[0],
                "reasoning": f"LLM interpretation failed. Using default. User input: {feedback}"
            }
        else:
            # [NEW] 컬럼이 없을 때 안전 처리
            print(f"   ⚠️ No columns available. Using user feedback as-is.")
            return {
                "action": "use_filename_as_id",
                "column_name": "unknown",
                "reasoning": f"No columns available. User feedback: {feedback}"
            }
        
    except Exception as e:
        print(f"   ⚠️ LLM call failed: {e}")
        # [NEW] 안전한 에러 처리
        if available_columns:
            return {
                "action": "use_column",
                "column_name": available_columns[0],
                "reasoning": f"LLM failed. Using default. Error: {str(e)}"
            }
        else:
            # 컬럼이 없으면 파일명에서 ID 추출
            basename = os.path.basename(file_path)
            name_without_ext = os.path.splitext(basename)[0]
            
            import re
            numbers = re.findall(r'\d+', name_without_ext)
            caseid = int(numbers[-1]) if numbers else name_without_ext
            
            return {
                "action": "use_filename_as_id",
                "column_name": "caseid" if numbers else "file_id",
                "caseid_value": caseid,
                "reasoning": f"LLM failed, no columns. Using filename. Error: {str(e)}"
            }


def _generate_natural_human_question(
    file_path: str,
    context: Dict[str, Any],
    issue_type: str = "general_uncertainty",
    conversation_history: Optional[ConversationHistory] = None
) -> str:
    """
    [Helper] Generate natural questions for users using LLM (Human-in-the-Loop)
    
    [NEW] 대화 히스토리를 참조하여 더 맥락에 맞는 질문 생성
    
    Args:
        file_path: 현재 파일 경로
        context: 컨텍스트 정보 (columns, candidates, reasoning 등)
        issue_type: 이슈 유형
        conversation_history: 이전 대화 히스토리 (옵션)
    
    Returns:
        Question string to show to the user (English)
    """
    from src.utils.llm_client import get_llm_client
    
    filename = os.path.basename(file_path)
    
    # [NEW] 대화 히스토리 컨텍스트
    history_context = ""
    if conversation_history and conversation_history.get("turns"):
        history_context = format_history_for_prompt(conversation_history, max_turns=3)
    
    # Extract context
    columns = context.get("columns", [])
    candidates = context.get("candidates", "None")
    reasoning = context.get("reasoning", "No information")
    ai_msg = context.get("message", "")
    global_master = context.get("master_anchor", "None")
    
    # Format column list
    column_list = columns[:10] if len(columns) > 10 else columns
    columns_str = ", ".join(column_list)
    if len(columns) > 10:
        columns_str += f" ... (and {len(columns) - 10} more)"
    
    # === Fallback messages (used when LLM fails) ===
    fallback_messages = {
        "anchor_conflict": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  🔗 Anchor Column Mismatch - Confirmation Required                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     The project's Master Anchor is '{global_master}'.
│     However, this file appears to use '{candidates}' as the identifier.
│  
│  💡 AI Analysis:
│     {reasoning[:200]}{'...' if len(str(reasoning)) > 200 else ''}
│  
│  📋 Columns in file:
│     {columns_str}
│  
│  🎯 Action Required:
│     1. Is '{candidates}' the same as '{global_master}'? (e.g., both are Patient ID)
│     2. If not, which column corresponds to '{global_master}'?
│     3. If none exists, type 'skip'.
└─────────────────────────────────────────────────────────────────────────────┘
""",
        "anchor_uncertain": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  🔍 Anchor Column Identification Required                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     AI could not identify a Patient/Case identifier (Anchor) column.
│     Candidate: '{candidates}' (low confidence)
│  
│  💡 AI Analysis:
│     {reasoning[:200]}{'...' if len(str(reasoning)) > 200 else ''}
│  
│  📋 Columns in file:
│     {columns_str}
│  
│  🎯 Action Required:
│     Please enter the column name that serves as the unique identifier
│     (Patient ID, Subject ID, Case ID, etc.).
│     Type 'skip' if none exists.
└─────────────────────────────────────────────────────────────────────────────┘
""",
        "metadata_uncertain": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  📖 File Type Confirmation Required                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     AI cannot determine if this file is 'metadata (description/dictionary)'
│     or 'actual data'.
│  
│  💡 AI Analysis:
│     {reasoning[:200]}{'...' if len(str(reasoning)) > 200 else ''}
│  
│  📋 Columns in file:
│     {columns_str}
│  
│  🎯 Action Required:
│     - If metadata (column descriptions, code definitions): type 'metadata'
│     - If actual patient/measurement data: type 'data'
└─────────────────────────────────────────────────────────────────────────────┘
""",
        "general_uncertainty": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⚠️ Confirmation Required                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     {ai_msg or 'Uncertainty occurred during data processing.'}
│  
│  📋 Columns in file:
│     {columns_str}
│  
│  🎯 User confirmation is required.
└─────────────────────────────────────────────────────────────────────────────┘
"""
    }
    
    # === LLM prompt ===
    task_descriptions = {
        "anchor_conflict": f"""
In the current file '{filename}', the column '{candidates}' is presumed to be the identifier.
However, the project's Master Anchor is '{global_master}'.
Ask the user if these two columns have the same meaning, or if a different column should be selected.
""",
        "anchor_uncertain": f"""
No clear identifier column was found in the current file '{filename}'.
AI's candidate is '{candidates}' but with low confidence.
Ask the user which column is the patient/case identifier.
""",
        "metadata_uncertain": f"""
It is unclear whether the current file '{filename}' is metadata (description file) or actual data.
Ask the user to confirm the type of file.
""",
        "general_uncertainty": f"Issue during data processing: {ai_msg}"
    }
    
    task_desc = task_descriptions.get(issue_type, task_descriptions["general_uncertainty"])
    
    # [NEW] 대화 히스토리 섹션 추가
    history_section = ""
    if history_context:
        history_section = f"""
{history_context}

[IMPORTANT - Use Previous Interactions]
- Reference previous user decisions when formulating your question
- If user has shown a pattern (e.g., always approving AI decisions), adjust your question accordingly
- Avoid asking the same question if already answered for similar files
"""
    
    prompt = f"""You are an AI assistant helping a medical data engineer.
An uncertainty occurred during data processing, and you need to ask the user a question.

[Context]
- Filename: {filename}
- Columns in file: {columns_str}
- AI Analysis: {reasoning}
- Additional info: {ai_msg}
{history_section}
[Issue to Resolve]
{task_desc}

[Question Guidelines]
1. Write in clear, professional English.
2. Be polite and specific in your question.
3. Briefly explain why you're asking this question.
4. Provide options or examples for the user to choose from.
5. Reference specific column names from the column list.
6. Keep it within 3-5 sentences.
7. Do not use code or JSON format.
8. If there's conversation history, reference previous user decisions to provide better context.

Question:"""
    
    try:
        llm_client = get_llm_client()
        llm_response = llm_client.ask_text(prompt)
        
        # LLM 응답이 너무 짧으면 fallback 사용
        if len(llm_response.strip()) < 20:
            return fallback_messages.get(issue_type, fallback_messages["general_uncertainty"])
        
        # LLM 응답 포맷팅
        formatted_response = f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  📁 파일: {filename}
│  📋 컬럼: {columns_str}
├─────────────────────────────────────────────────────────────────────────────┤

{llm_response.strip()}

└─────────────────────────────────────────────────────────────────────────────┘
"""
        return formatted_response
        
    except Exception as e:
        print(f"⚠️ [Question Gen] LLM 호출 실패: {e}")
        return fallback_messages.get(issue_type, fallback_messages["general_uncertainty"])



def ontology_builder_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node] 온톨로지 구축 - Rule Prepares, LLM Decides
    
    파일이 메타데이터인지 판단하고, 메타데이터면 파싱하여 온톨로지에 추가
    [NEW] 대화 히스토리를 컨텍스트로 활용
    """
    print("\n" + "="*80)
    print("📚 [ONTOLOGY BUILDER NODE] 시작")
    print("="*80)
    
    file_path = state["file_path"]
    metadata = state["raw_metadata"]
    
    # [NEW] 대화 히스토리 가져오기
    dataset_id = state.get("current_dataset_id", "unknown")
    conversation_history = state.get("conversation_history")
    if not conversation_history:
        conversation_history = create_empty_conversation_history(dataset_id)
    
    # 기존 온톨로지 가져오기 (State에서 또는 디스크에서)
    ontology = state.get("ontology_context")
    
    # 첫 파일이거나 ontology가 비어있으면 디스크에서 로드
    if not ontology or not ontology.get("definitions"):
        print(f"   - 온톨로지 로드 시도...")
        ontology = ontology_manager.load()
    
    # 여전히 없으면 빈 구조
    if not ontology:
        ontology = {
            "definitions": {},
            "relationships": [],
            "hierarchy": [],
            "file_tags": {}
        }
    
    # === Step 1: Rule Prepares (데이터 전처리) ===
    print("\n🔧 [Rule] 데이터 전처리 중...")
    context = _build_metadata_detection_context(file_path, metadata)
    
    print(f"   - 파일명 파싱: {context.get('name_parts')}")
    print(f"   - Base Name: {context.get('base_name')}")
    print(f"   - 컬럼 수: {context.get('num_columns')}개")
    print(f"   - 컨텍스트 크기: {context.get('context_size_bytes', 0)} bytes")
    
    # === Step 2: LLM Decides (메타데이터 여부 판단) ===
    print("\n🧠 [LLM] 메타데이터 여부 판단 중...")
    
    meta_result = _ask_llm_is_metadata(context)
    
    confidence = meta_result.get("confidence", 0.0)
    is_metadata = meta_result.get("is_metadata", False)
    
    print(f"   - 판단: {'메타데이터' if is_metadata else '일반 데이터'}")
    print(f"   - 확신도: {confidence:.2%}")
    print(f"   - Reasoning: {meta_result.get('reasoning', 'N/A')[:80]}...")
    
    # === Step 3: Confidence Check (유연한 판단) ===
    review_decision = _should_request_human_review(
        file_path=file_path,
        issue_type="metadata_classification",
        context={
            "is_metadata": is_metadata,
            "reasoning": meta_result.get("reasoning"),
            "columns": context.get("columns", []),
            "indicators": meta_result.get("indicators", {})
        },
        rule_based_confidence=confidence
    )
    
    if review_decision["needs_review"]:
        print(f"\n⚠️  [Low Confidence] Human Review 요청")
        print(f"   Reason: {review_decision['reason']}")
        
        # 구체적 질문 생성 (LLM) - [NEW] 대화 히스토리 포함
        specific_question = _generate_natural_human_question(
            file_path=file_path,
            context={
                "reasoning": meta_result.get("reasoning"),
                "message": f"Confidence {confidence:.1%}",
                "columns": context.get("columns", [])
            },
            issue_type="metadata_uncertain",
            conversation_history=conversation_history  # [NEW] 대화 히스토리 전달
        )
        
        print("="*80)
        
        return {
            "needs_human_review": True,
            "review_type": "classification",  # [NEW] 리뷰 타입 명시
            "human_question": specific_question,
            "ontology_context": ontology,  # 현재 상태 유지
            "conversation_history": conversation_history,  # [NEW] 히스토리 전달
            "logs": [f"⚠️ [Ontology] 메타데이터 판단 불확실 ({confidence:.2%}). {review_decision['reason']}"]
        }
    
    # === Step 4: Branching (확신도 높음) ===
    
    # [Branch A] 메타데이터 파일
    if is_metadata:
        print(f"\n📖 [Metadata] 메타데이터 파일로 확정")
        
        # 파일 태그 저장
        ontology["file_tags"][file_path] = {
            "type": "metadata",
            "role": "dictionary",
            "confidence": confidence,
            "detected_at": datetime.now().isoformat()
        }
        
        # 내용 파싱 (Rule)
        print(f"   - 메타데이터 파싱 중...")
        new_definitions = _parse_metadata_content(file_path)
        ontology["definitions"].update(new_definitions)
        
        print(f"   - 용어 {len(new_definitions)}개 추가")
        print(f"   - 총 용어: {len(ontology['definitions'])}개")
        
        # 온톨로지 저장 (영구 보존)
        print(f"   - 온톨로지 저장 중...")
        ontology_manager.save(ontology)
        
        print("="*80)
        
        return {
            "ontology_context": ontology,
            "skip_indexing": True,  # 중요! 메타데이터는 인덱싱 스킵
            "logs": [f"📚 [Ontology] 메타데이터 등록: {len(new_definitions)}개 용어 추가 (저장 완료)"]
        }
    
    # [Branch B] 일반 데이터 파일
    else:
        print(f"\n📊 [Data] 일반 데이터 파일로 확정")
        
        # 컬럼 정보 저장 (관계 추론에 필요)
        columns = metadata.get("columns", [])
        
        ontology["file_tags"][file_path] = {
            "type": "transactional_data",
            "confidence": confidence,
            "detected_at": datetime.now().isoformat(),
            "columns": columns  # [NEW] 컬럼 저장
        }
        
        # Note: Column Metadata는 index_data_node에서 finalized_schema 확정 후 저장됨
        
        # === Phase 2: 관계 추론 (기존 테이블이 있을 때만) ===
        existing_data_files = [
            fp for fp, tag in ontology.get("file_tags", {}).items()
            if tag.get("type") == "transactional_data" and fp != file_path
        ]
        
        if existing_data_files:
            print(f"\n🔗 [Relationship] 관계 추론 시작...")
            print(f"   - 기존 데이터 파일: {len(existing_data_files)}개")
            
            # 관계 추론 (LLM)
            table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_")
            
            relationship_result = _infer_relationships_with_llm(
                current_table_name=table_name,
                current_cols=columns,
                ontology_context=ontology,
                current_metadata=metadata
            )
            
            # 관계 추가
            new_relationships = relationship_result.get("relationships", [])
            if new_relationships:
                print(f"   - 관계 {len(new_relationships)}개 발견")
                
                # 기존 관계와 병합
                existing_rels = ontology.get("relationships", [])
                
                # 중복 체크
                existing_keys = {
                    (r["source_table"], r["target_table"], r["source_column"], r["target_column"])
                    for r in existing_rels
                }
                
                for new_rel in new_relationships:
                    key = (new_rel["source_table"], new_rel["target_table"], 
                           new_rel["source_column"], new_rel["target_column"])
                    if key not in existing_keys:
                        ontology["relationships"].append(new_rel)
                        print(f"      • {new_rel['source_table']}.{new_rel['source_column']} "
                              f"→ {new_rel['target_table']}.{new_rel['target_column']} "
                              f"({new_rel['relation_type']}, conf: {new_rel.get('confidence', 0):.2%})")
            
            # 계층 업데이트 (중복 제거 강화)
            new_hierarchy = relationship_result.get("hierarchy", [])
            if new_hierarchy:
                print(f"   - 계층 정보 업데이트")
                
                # 기존 계층
                existing_hier = ontology.get("hierarchy", [])
                
                # 중복 제거 전략: (level, anchor_column) 조합으로 판단
                merged_hierarchy = {}  # key: (level, anchor), value: hierarchy_dict
                
                # 기존 계층 먼저 추가
                for h in existing_hier:
                    key = (h.get("level"), h.get("anchor_column"))
                    merged_hierarchy[key] = h
                
                # 새 계층 병합 (confidence 높은 것 우선)
                for new_h in new_hierarchy:
                    key = (new_h.get("level"), new_h.get("anchor_column"))
                    
                    if key not in merged_hierarchy:
                        # 새로운 (level, anchor) 조합
                        merged_hierarchy[key] = new_h
                        print(f"      • L{new_h['level']}: {new_h['entity_name']} ({new_h['anchor_column']}) [NEW]")
                    else:
                        # 이미 있는 조합 - confidence 비교
                        existing_conf = merged_hierarchy[key].get("confidence", 0)
                        new_conf = new_h.get("confidence", 0)
                        
                        if new_conf > existing_conf:
                            merged_hierarchy[key] = new_h
                            print(f"      • L{new_h['level']}: {new_h['entity_name']} ({new_h['anchor_column']}) [UPDATED, conf: {new_conf:.2%}]")
                        else:
                            print(f"      • L{new_h['level']}: (중복 스킵, 기존 confidence {existing_conf:.2%} 유지)")
                
                # 리스트로 변환 후 레벨 정렬
                ontology["hierarchy"] = sorted(merged_hierarchy.values(), key=lambda x: x.get("level", 99))
        else:
            print(f"\n   - 기존 데이터 파일 없음. 관계 추론 스킵.")
        
        # 온톨로지 저장
        print(f"   - 온톨로지 저장 중...")
        ontology_manager.save(ontology)
        
        print("="*80)
        
        return {
            "ontology_context": ontology,
            "skip_indexing": False,  # 일반 데이터는 인덱싱 계속
            "logs": ["🔍 [Ontology] 일반 데이터 확인. 관계 추론 완료."]
        }


# =============================================================================
# 2-Phase Workflow Nodes (NEW)
# =============================================================================

def batch_classifier_node(state: AgentState) -> Dict[str, Any]:
    """
    [Phase 1] 전체 파일 분류 노드
    
    모든 입력 파일을 한 번에 분류하여 메타데이터/데이터로 구분합니다.
    불확실한 파일은 classification_review_node로 보냅니다.
    """
    print("\n" + "="*80)
    print("📋 [BATCH CLASSIFIER] Phase 1 시작 - 전체 파일 분류")
    print("="*80)
    
    input_files = state.get("input_files", [])
    
    if not input_files:
        return {
            "logs": ["❌ Error: 입력 파일이 없습니다."],
            "error_message": "No input files provided"
        }
    
    print(f"   📂 처리할 파일: {len(input_files)}개")
    
    classifications: Dict[str, FileClassification] = {}
    metadata_files: List[str] = []
    data_files: List[str] = []
    uncertain_files: List[str] = []
    
    # 각 파일에 대해 분류 수행
    for idx, file_path in enumerate(input_files):
        filename = os.path.basename(file_path)
        print(f"\n   [{idx+1}/{len(input_files)}] {filename}")
        
        try:
            # 1. Processor로 기본 메타데이터 추출
            selected_processor = next((p for p in processors if p.can_handle(file_path)), None)
            
            if not selected_processor:
                print(f"      ⚠️ 지원되지 않는 파일 형식")
                classifications[file_path] = {
                    "file_path": file_path,
                    "filename": filename,
                    "classification": "unknown",
                    "confidence": 0.0,
                    "reasoning": "Unsupported file format",
                    "indicators": {},
                    "needs_review": True,
                    "human_confirmed": False
                }
                uncertain_files.append(file_path)
                continue
            
            raw_metadata = selected_processor.extract_metadata(file_path)
            
            # 2. 분류 컨텍스트 구축 (Rule)
            context = _build_metadata_detection_context(file_path, raw_metadata)
            
            # 3. LLM으로 분류 판단
            meta_result = _ask_llm_is_metadata(context)
            
            confidence = meta_result.get("confidence", 0.0)
            is_metadata = meta_result.get("is_metadata", False)
            reasoning = meta_result.get("reasoning", "")
            indicators = meta_result.get("indicators", {})
            
            # 4. 분류 결과 저장
            classification_type = "metadata" if is_metadata else "data"
            needs_review = confidence < HumanReviewConfig.CLASSIFICATION_CONFIDENCE_THRESHOLD
            
            classifications[file_path] = {
                "file_path": file_path,
                "filename": filename,
                "classification": classification_type,
                "confidence": confidence,
                "reasoning": reasoning,
                "indicators": indicators,
                "needs_review": needs_review,
                "human_confirmed": False
            }
            
            # 5. 분류별 리스트에 추가
            if needs_review:
                uncertain_files.append(file_path)
                print(f"      ⚠️ 불확실: {classification_type} ({confidence:.1%})")
            elif is_metadata:
                metadata_files.append(file_path)
                print(f"      📖 메타데이터 ({confidence:.1%})")
            else:
                data_files.append(file_path)
                print(f"      📊 데이터 ({confidence:.1%})")
                
        except Exception as e:
            print(f"      ❌ 분류 실패: {e}")
            classifications[file_path] = {
                "file_path": file_path,
                "filename": filename,
                "classification": "unknown",
                "confidence": 0.0,
                "reasoning": f"Error: {str(e)}",
                "indicators": {},
                "needs_review": True,
                "human_confirmed": False
            }
            uncertain_files.append(file_path)
    
    # 분류 결과 요약
    classification_result: ClassificationResult = {
        "total_files": len(input_files),
        "metadata_files": metadata_files,
        "data_files": data_files,
        "uncertain_files": uncertain_files,
        "classifications": classifications
    }
    
    # 처리 진행 상황 초기화
    processing_progress: ProcessingProgress = {
        "phase": "classification",
        "metadata_processed": [],
        "data_processed": [],
        "current_file": None,
        "current_file_index": 0,
        "total_files": len(input_files)
    }
    
    print(f"\n" + "-"*40)
    print(f"📊 분류 완료:")
    print(f"   - 메타데이터: {len(metadata_files)}개 (확정)")
    print(f"   - 데이터: {len(data_files)}개 (확정)")
    print(f"   - 불확실: {len(uncertain_files)}개 (리뷰 필요)")
    print("="*80)
    
    return {
        "classification_result": classification_result,
        "processing_progress": processing_progress,
        "logs": [
            f"📋 [Phase1] 분류 완료: 메타데이터 {len(metadata_files)}개, "
            f"데이터 {len(data_files)}개, 불확실 {len(uncertain_files)}개"
        ]
    }


def classification_review_node(state: AgentState) -> Dict[str, Any]:
    """
    [Phase 1-2] 분류 확인 노드 (Human-in-the-Loop)
    
    불확실한 파일들에 대해 사용자에게 확인을 요청합니다.
    """
    print("\n" + "="*80)
    print("🧑 [CLASSIFICATION REVIEW] Human-in-the-Loop")
    print("="*80)
    
    classification_result = state.get("classification_result", {})
    uncertain_files = classification_result.get("uncertain_files", [])
    classifications = classification_result.get("classifications", {})
    human_feedback = state.get("human_feedback")
    
    # 피드백 처리 (재진입)
    if human_feedback:
        print(f"   💬 사용자 피드백 수신: '{human_feedback}'")
        
        # 피드백 파싱
        updated_classifications = _parse_classification_feedback(
            feedback=human_feedback,
            classifications=classifications,
            uncertain_files=uncertain_files
        )
        
        # 분류 결과 업데이트
        new_metadata_files = []
        new_data_files = []
        remaining_uncertain = []
        
        for file_path, clf in updated_classifications.items():
            if clf.get("human_confirmed"):
                if clf["classification"] == "metadata":
                    new_metadata_files.append(file_path)
                elif clf["classification"] == "data":
                    new_data_files.append(file_path)
                else:
                    remaining_uncertain.append(file_path)
            elif clf["needs_review"]:
                remaining_uncertain.append(file_path)
            elif clf["classification"] == "metadata":
                new_metadata_files.append(file_path)
            else:
                new_data_files.append(file_path)
        
        # 기존 확정 파일 + 새로 확정된 파일
        all_metadata = classification_result.get("metadata_files", []) + [
            f for f in new_metadata_files if f not in classification_result.get("metadata_files", [])
        ]
        all_data = classification_result.get("data_files", []) + [
            f for f in new_data_files if f not in classification_result.get("data_files", [])
        ]
        
        updated_result: ClassificationResult = {
            "total_files": classification_result["total_files"],
            "metadata_files": all_metadata,
            "data_files": all_data,
            "uncertain_files": remaining_uncertain,
            "classifications": updated_classifications
        }
        
        print(f"   ✅ 분류 업데이트 완료")
        print(f"      - 메타데이터: {len(all_metadata)}개")
        print(f"      - 데이터: {len(all_data)}개")
        print(f"      - 남은 불확실: {len(remaining_uncertain)}개")
        
        # 아직 불확실한 파일이 있으면 계속 질문
        if remaining_uncertain:
            question = _generate_classification_question(remaining_uncertain, updated_classifications)
            return {
                "classification_result": updated_result,
                "needs_human_review": True,
                "review_type": "classification",
                "human_question": question,
                "human_feedback": None,  # 리셋
                "logs": [f"🔄 [Review] 추가 확인 필요: {len(remaining_uncertain)}개 파일"]
            }
        
        # 모두 확정됨
        progress = state.get("processing_progress", {})
        progress["phase"] = "classification_review"
        
        print("="*80)
        
        return {
            "classification_result": updated_result,
            "processing_progress": progress,
            "needs_human_review": False,
            "human_feedback": None,
            "logs": [f"✅ [Review] 분류 확정 완료"]
        }
    
    # 첫 진입: 질문 생성
    if not uncertain_files:
        print("   ✅ 불확실한 파일 없음 - 리뷰 스킵")
        return {
            "needs_human_review": False,
            "logs": ["✅ [Review] 모든 파일 분류 확정"]
        }
    
    # 사용자에게 질문 생성
    question = _generate_classification_question(uncertain_files, classifications)
    
    print(f"   ❓ {len(uncertain_files)}개 파일에 대해 사용자 확인 요청")
    print("="*80)
    
    return {
        "needs_human_review": True,
        "review_type": "classification",
        "human_question": question,
        "logs": [f"❓ [Review] {len(uncertain_files)}개 파일 분류 확인 요청"]
    }


def _generate_classification_question(uncertain_files: List[str], classifications: Dict[str, FileClassification]) -> str:
    """불확실한 파일들에 대한 질문 생성"""
    
    question_parts = [
        "📋 **파일 분류 확인이 필요합니다**\n",
        "아래 파일들의 분류를 확인해주세요:\n"
    ]
    
    for idx, file_path in enumerate(uncertain_files[:5], 1):  # 최대 5개씩
        clf = classifications.get(file_path, {})
        filename = clf.get("filename", os.path.basename(file_path))
        predicted = clf.get("classification", "unknown")
        confidence = clf.get("confidence", 0.0)
        reasoning = clf.get("reasoning", "")[:100]
        
        pred_emoji = "📖" if predicted == "metadata" else "📊" if predicted == "data" else "❓"
        pred_text = "메타데이터" if predicted == "metadata" else "데이터" if predicted == "data" else "알 수 없음"
        
        question_parts.append(
            f"\n**{idx}. {filename}**\n"
            f"   - AI 예측: {pred_emoji} {pred_text} (확신도: {confidence:.0%})\n"
            f"   - 판단 근거: {reasoning}...\n"
        )
    
    if len(uncertain_files) > 5:
        question_parts.append(f"\n... 외 {len(uncertain_files) - 5}개 파일\n")
    
    question_parts.append(
        "\n**응답 방법:**\n"
        "- 모두 맞으면: `확인` 또는 `ok`\n"
        "- 수정이 필요하면: `1:데이터, 2:메타데이터` 형식으로 번호와 분류를 입력\n"
        "- 파일 제외: `1:제외` 또는 `1:skip`\n"
    )
    
    return "".join(question_parts)


def _parse_classification_feedback(
    feedback: str, 
    classifications: Dict[str, FileClassification],
    uncertain_files: List[str]
) -> Dict[str, FileClassification]:
    """사용자 피드백을 파싱하여 분류 결과 업데이트"""
    
    updated = classifications.copy()
    feedback_lower = feedback.lower().strip()
    
    # "확인" 또는 "ok" - 모든 예측 승인
    if feedback_lower in ["확인", "ok", "yes", "y", "approve", "승인"]:
        for file_path in uncertain_files:
            if file_path in updated:
                updated[file_path]["human_confirmed"] = True
                updated[file_path]["needs_review"] = False
        return updated
    
    # 개별 수정: "1:데이터, 2:메타데이터" 형식
    import re
    corrections = re.findall(r'(\d+)\s*[:：]\s*(메타데이터|데이터|metadata|data|제외|skip)', feedback_lower)
    
    for idx_str, new_type in corrections:
        idx = int(idx_str) - 1  # 1-based to 0-based
        
        if 0 <= idx < len(uncertain_files):
            file_path = uncertain_files[idx]
            
            if new_type in ["제외", "skip"]:
                # 파일 제외 (unknown으로 변경, 처리 대상에서 제외됨)
                updated[file_path]["classification"] = "unknown"
                updated[file_path]["human_confirmed"] = True
                updated[file_path]["needs_review"] = False
            elif new_type in ["메타데이터", "metadata"]:
                updated[file_path]["classification"] = "metadata"
                updated[file_path]["human_confirmed"] = True
                updated[file_path]["needs_review"] = False
            elif new_type in ["데이터", "data"]:
                updated[file_path]["classification"] = "data"
                updated[file_path]["human_confirmed"] = True
                updated[file_path]["needs_review"] = False
    
    return updated


def process_metadata_batch_node(state: AgentState) -> Dict[str, Any]:
    """
    [Phase 2-1] 메타데이터 일괄 처리 노드
    
    분류된 메타데이터 파일들을 먼저 처리하여 온톨로지를 구축합니다.
    """
    print("\n" + "="*80)
    print("📖 [METADATA PROCESSOR] Phase 2-1 - 메타데이터 일괄 처리")
    print("="*80)
    
    classification_result = state.get("classification_result", {})
    metadata_files = classification_result.get("metadata_files", [])
    progress = state.get("processing_progress", {})
    
    # 온톨로지 로드
    ontology = state.get("ontology_context")
    if not ontology or not ontology.get("definitions"):
        ontology = ontology_manager.load() or {
            "definitions": {},
            "relationships": [],
            "hierarchy": [],
            "file_tags": {}
        }
    
    if not metadata_files:
        print("   ℹ️ 처리할 메타데이터 파일 없음")
        progress["phase"] = "metadata_processing"
        progress["metadata_processed"] = []
        
        return {
            "ontology_context": ontology,
            "processing_progress": progress,
            "logs": ["ℹ️ [Metadata] 메타데이터 파일 없음 - 스킵"]
        }
    
    print(f"   📂 메타데이터 파일: {len(metadata_files)}개")
    
    processed_metadata = []
    total_definitions = 0
    
    for idx, file_path in enumerate(metadata_files):
        filename = os.path.basename(file_path)
        print(f"\n   [{idx+1}/{len(metadata_files)}] {filename}")
        
        try:
            # 파일 태그 저장
            ontology["file_tags"][file_path] = {
                "type": "metadata",
                "role": "dictionary",
                "confidence": classification_result["classifications"].get(file_path, {}).get("confidence", 0.8),
                "detected_at": datetime.now().isoformat()
            }
            
            # 메타데이터 파싱
            new_definitions = _parse_metadata_content(file_path)
            ontology["definitions"].update(new_definitions)
            
            total_definitions += len(new_definitions)
            processed_metadata.append(file_path)
            
            print(f"      ✅ 용어 {len(new_definitions)}개 추가")
            
        except Exception as e:
            print(f"      ❌ 처리 실패: {e}")
    
    # 온톨로지 저장
    ontology_manager.save(ontology)
    
    # 진행 상황 업데이트
    progress["phase"] = "metadata_processing"
    progress["metadata_processed"] = processed_metadata
    
    print(f"\n" + "-"*40)
    print(f"📊 메타데이터 처리 완료:")
    print(f"   - 처리된 파일: {len(processed_metadata)}개")
    print(f"   - 추가된 용어: {total_definitions}개")
    print(f"   - 총 용어 수: {len(ontology.get('definitions', {}))}개")
    print("="*80)
    
    return {
        "ontology_context": ontology,
        "processing_progress": progress,
        "logs": [f"📖 [Metadata] {len(processed_metadata)}개 파일 처리, {total_definitions}개 용어 추가"]
    }


def process_data_batch_node(state: AgentState) -> Dict[str, Any]:
    """
    [Phase 2-2] 데이터 일괄 처리 준비 노드
    
    데이터 파일 처리를 시작하고, 첫 번째 파일로 전환합니다.
    (각 데이터 파일은 기존 워크플로우(analyzer → human_review → indexer)를 따름)
    """
    print("\n" + "="*80)
    print("📊 [DATA PROCESSOR] Phase 2-2 - 데이터 처리 시작")
    print("="*80)
    
    classification_result = state.get("classification_result", {})
    data_files = classification_result.get("data_files", [])
    progress = state.get("processing_progress", {})
    
    if not data_files:
        print("   ℹ️ 처리할 데이터 파일 없음")
        progress["phase"] = "complete"
        
        return {
            "processing_progress": progress,
            "logs": ["ℹ️ [Data] 데이터 파일 없음 - 완료"]
        }
    
    print(f"   📂 데이터 파일: {len(data_files)}개")
    print(f"   🚀 첫 번째 파일부터 처리 시작")
    
    # 첫 번째 파일 설정
    first_file = data_files[0]
    
    progress["phase"] = "data_processing"
    progress["current_file"] = first_file
    progress["current_file_index"] = 0
    progress["total_files"] = len(data_files)
    
    print(f"\n   → 처리 파일: {os.path.basename(first_file)}")
    print("="*80)
    
    # 첫 파일 경로 설정 (다음 노드에서 사용)
    return {
        "file_path": first_file,
        "processing_progress": progress,
        "skip_indexing": False,
        "logs": [f"📊 [Data] {len(data_files)}개 파일 처리 시작"]
    }


def advance_to_next_file_node(state: AgentState) -> Dict[str, Any]:
    """
    [Helper] 다음 데이터 파일로 진행
    
    현재 파일 인덱싱 완료 후 다음 파일로 이동합니다.
    """
    print("\n" + "-"*40)
    print("➡️ [ADVANCE] 다음 파일로 이동")
    print("-"*40)
    
    classification_result = state.get("classification_result", {})
    data_files = classification_result.get("data_files", [])
    progress = state.get("processing_progress", {})
    
    current_idx = progress.get("current_file_index", 0)
    current_file = progress.get("current_file", "")
    
    # 현재 파일을 처리 완료 목록에 추가
    if current_file and current_file not in progress.get("data_processed", []):
        if "data_processed" not in progress:
            progress["data_processed"] = []
        progress["data_processed"].append(current_file)
    
    # 다음 인덱스
    next_idx = current_idx + 1
    
    if next_idx >= len(data_files):
        # 모든 파일 처리 완료
        print(f"   ✅ 모든 데이터 파일 처리 완료 ({len(data_files)}개)")
        progress["phase"] = "complete"
        progress["current_file"] = None
        
        return {
            "processing_progress": progress,
            "logs": [f"✅ [Complete] 모든 데이터 파일 처리 완료 ({len(data_files)}개)"]
        }
    
    # 다음 파일로 이동
    next_file = data_files[next_idx]
    progress["current_file"] = next_file
    progress["current_file_index"] = next_idx
    
    print(f"   📂 다음 파일: [{next_idx + 1}/{len(data_files)}] {os.path.basename(next_file)}")
    
    # 상태 리셋 (새 파일 처리를 위해)
    return {
        "file_path": next_file,
        "processing_progress": progress,
        "raw_metadata": {},  # 리셋
        "finalized_anchor": None,  # 리셋
        "finalized_schema": [],  # 리셋
        "needs_human_review": False,  # 리셋
        "human_feedback": None,  # 리셋
        "skip_indexing": False,  # 리셋
        "retry_count": 0,  # 리셋
        "logs": [f"➡️ [Advance] 다음 파일: {os.path.basename(next_file)}"]
    }


# =============================================================================
# Routing Functions for 2-Phase Workflow
# =============================================================================

def check_classification_needs_review(state: AgentState) -> str:
    """분류 결과 중 불확실한 것이 있는지 확인"""
    classification_result = state.get("classification_result", {})
    uncertain_files = classification_result.get("uncertain_files", [])
    
    if uncertain_files:
        return "needs_review"
    return "all_confident"


def check_has_more_files(state: AgentState) -> str:
    """더 처리할 데이터 파일이 있는지 확인"""
    classification_result = state.get("classification_result", {})
    data_files = classification_result.get("data_files", [])
    progress = state.get("processing_progress", {})
    
    current_idx = progress.get("current_file_index", 0)
    
    # 아직 처리할 파일이 남아있으면
    if current_idx + 1 < len(data_files):
        return "has_more"
    return "all_done"


def check_data_needs_review(state: AgentState) -> str:
    """데이터 분석 후 Human Review 필요 여부 확인"""
    
    # 기존 check_confidence 로직 활용
    needs_human = state.get("needs_human_review", False)
    finalized_anchor = state.get("finalized_anchor", {})
    anchor_status = finalized_anchor.get("status") if finalized_anchor else None
    
    # Anchor가 확정된 경우
    if anchor_status in ["CONFIRMED", "INDIRECT_LINK"]:
        return "approved"
    
    # Processor가 확인 요청
    if state.get("raw_metadata", {}).get("anchor_info", {}).get("needs_human_confirmation"):
        return "review_required"
    
    # needs_human_review 플래그
    if needs_human:
        return "review_required"
    
    return "approved"