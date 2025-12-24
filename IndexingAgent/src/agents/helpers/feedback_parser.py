# src/agents/helpers/feedback_parser.py
"""
Human Feedback 파싱 및 질문 생성 헬퍼
"""

import os
import re
from typing import Dict, Any, List, Optional

from src.agents.state import ConversationHistory
from src.utils.llm_client import get_llm_client

# Lazy initialization
_llm_client = None

def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        _llm_client = get_llm_client()
    return _llm_client


def format_history_for_prompt(history, max_turns: int = 5) -> str:
    """대화 히스토리를 LLM 프롬프트용 텍스트로 변환"""
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
    
    if history.get("user_preferences"):
        lines.append("[LEARNED USER PREFERENCES]")
        for key, value in history["user_preferences"].items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    
    if history.get("classification_decisions"):
        lines.append("[PREVIOUS CLASSIFICATION DECISIONS]")
        for dec in history["classification_decisions"][-3:]:
            lines.append(f"- {dec['file']}: {dec['response']}")
        lines.append("")
    
    if history.get("anchor_decisions"):
        lines.append("[PREVIOUS ANCHOR DECISIONS]")
        for dec in history["anchor_decisions"][-3:]:
            lines.append(f"- {dec['file']}: {dec['response']}")
        lines.append("")
    
    return "\n".join(lines)


def parse_human_feedback_to_column(
    feedback: str,
    available_columns: List[str],
    master_anchor: Optional[str],
    file_path: str
) -> Dict[str, Any]:
    """
    사용자 피드백을 파싱하여 실제 컬럼명 추출
    """
    feedback_lower = feedback.strip().lower()
    
    # Case 1: 스킵 요청
    if feedback_lower in ["skip", "스킵", "건너뛰기", "pass"]:
        return {"action": "skip", "reasoning": "사용자가 스킵 요청"}
    
    # Case 1.5: .vital 파일 관련 피드백 감지
    vital_keywords = ["vital", "vitaldb", "file name is the caseid", "filename is caseid", 
                      "actual file", "actual data", "binary", "signal file"]
    if any(kw in feedback_lower for kw in vital_keywords):
        basename = os.path.basename(file_path)
        name_without_ext = os.path.splitext(basename)[0]
        
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
    
    # Case 2: 컬럼이 없는 경우 (signal 파일 등)
    if not available_columns:
        print(f"   → No columns available. Processing as special file type...")
        
        basename = os.path.basename(file_path)
        name_without_ext = os.path.splitext(basename)[0]
        
        numbers = re.findall(r'\d+', name_without_ext)
        
        if numbers:
            caseid = int(numbers[-1])
            return {
                "action": "use_filename_as_id",
                "column_name": "caseid",
                "caseid_value": caseid,
                "reasoning": f"No columns detected. Caseid={caseid} extracted from filename.",
                "user_intent": feedback
            }
        else:
            return {
                "action": "use_filename_as_id",
                "column_name": "file_id",
                "caseid_value": name_without_ext,
                "reasoning": f"No columns detected. Using filename as identifier.",
                "user_intent": feedback
            }
    
    # Case 3: 실제 컬럼명과 정확히 일치
    columns_lower = [c.lower() for c in available_columns]
    if feedback_lower in columns_lower:
        idx = columns_lower.index(feedback_lower)
        return {
            "action": "use_column",
            "column_name": available_columns[idx],
            "reasoning": "User specified column name directly"
        }
    
    # Case 4: LLM으로 해석
    print(f"   → User input is not a column name. Interpreting with LLM...")
    
    try:
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
2. If the feedback describes relationships, select the most appropriate column.
3. Prioritize columns that can link to the Master Anchor.

[Response Format - JSON only]
{{
    "column_name": "Selected column name",
    "reasoning": "Reason for selection",
    "user_intent": "Summary of user's intent"
}}"""
        
        result = _get_llm_client().ask_json(prompt)
        
        if "error" not in result and result.get("column_name"):
            selected = result["column_name"]
            
            if selected.lower() in columns_lower:
                idx = columns_lower.index(selected.lower())
                return {
                    "action": "use_column",
                    "column_name": available_columns[idx],
                    "reasoning": result.get("reasoning", "LLM interpretation result"),
                    "user_intent": result.get("user_intent", feedback)
                }
        
        if available_columns:
            print(f"   ⚠️ LLM failed. Using first column: {available_columns[0]}")
            return {
                "action": "use_column",
                "column_name": available_columns[0],
                "reasoning": f"LLM interpretation failed. Using default."
            }
        else:
            return {
                "action": "use_filename_as_id",
                "column_name": "unknown",
                "reasoning": f"No columns available. User feedback: {feedback}"
            }
        
    except Exception as e:
        print(f"   ⚠️ LLM call failed: {e}")
        if available_columns:
            return {
                "action": "use_column",
                "column_name": available_columns[0],
                "reasoning": f"LLM failed. Using default."
            }
        else:
            basename = os.path.basename(file_path)
            name_without_ext = os.path.splitext(basename)[0]
            numbers = re.findall(r'\d+', name_without_ext)
            caseid = int(numbers[-1]) if numbers else name_without_ext
            
            return {
                "action": "use_filename_as_id",
                "column_name": "caseid" if numbers else "file_id",
                "caseid_value": caseid,
                "reasoning": f"LLM failed, no columns. Using filename."
            }


def generate_natural_human_question(
    file_path: str,
    context: Dict[str, Any],
    issue_type: str = "general_uncertainty",
    conversation_history: Optional[ConversationHistory] = None
) -> str:
    """
    Generate natural questions for users using LLM (Human-in-the-Loop)
    """
    filename = os.path.basename(file_path)
    
    # 대화 히스토리 컨텍스트
    history_context = ""
    if conversation_history and conversation_history.get("turns"):
        history_context = format_history_for_prompt(conversation_history, max_turns=3)
    
    # Extract context (with None safety)
    columns = context.get("columns", []) or []
    candidates = context.get("candidates") or "None"
    reasoning = context.get("reasoning") or "No information available"
    ai_msg = context.get("message") or ""
    global_master = context.get("master_anchor") or "None"
    
    # Ensure reasoning is a string
    if reasoning is None:
        reasoning = "No information available"
    reasoning = str(reasoning)
    
    column_list = columns[:10] if len(columns) > 10 else columns
    columns_str = ", ".join(column_list)
    if len(columns) > 10:
        columns_str += f" ... (and {len(columns) - 10} more)"
    
    # Fallback messages
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
│     1. Is '{candidates}' the same as '{global_master}'?
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
│     Please enter the column name that serves as the unique identifier.
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
│     AI cannot determine if this file is 'metadata' or 'actual data'.
│  
│  💡 AI Analysis:
│     {reasoning[:200]}{'...' if len(str(reasoning)) > 200 else ''}
│  
│  📋 Columns in file:
│     {columns_str}
│  
│  🎯 Action Required:
│     - If metadata (column descriptions): type 'metadata'
│     - If actual patient data: type 'data'
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
    
    # LLM prompt
    task_descriptions = {
        "anchor_conflict": f"Column '{candidates}' vs Master Anchor '{global_master}'. Ask user to clarify.",
        "anchor_uncertain": f"No clear identifier found. Candidate is '{candidates}' with low confidence.",
        "metadata_uncertain": f"Cannot determine if file is metadata or data.",
        "general_uncertainty": f"Issue: {ai_msg}"
    }
    
    task_desc = task_descriptions.get(issue_type, task_descriptions["general_uncertainty"])
    
    history_section = ""
    if history_context:
        history_section = f"\n{history_context}\n[Use previous interactions to formulate your question]"
    
    prompt = f"""You are an AI assistant helping a medical data engineer.
An uncertainty occurred, and you need to ask the user a question.

[Context]
- Filename: {filename}
- Columns: {columns_str}
- AI Analysis: {reasoning}
{history_section}

[Issue to Resolve]
{task_desc}

[Guidelines]
1. Write in clear English
2. Be polite and specific
3. Explain why you're asking
4. Provide options/examples
5. Keep it within 3-5 sentences

Question:"""
    
    try:
        llm_response = _get_llm_client().ask_text(prompt)
        
        if len(llm_response.strip()) < 20:
            return fallback_messages.get(issue_type, fallback_messages["general_uncertainty"])
        
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

