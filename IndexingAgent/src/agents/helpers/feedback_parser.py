# src/agents/helpers/feedback_parser.py
"""
Human Feedback 파싱 및 질문 생성 헬퍼

FeedbackAction (단순화):
- SKIP: 파일 제외
- ACCEPT: entity identifier 지정 (컬럼, 파일명, FK 등)
- CLARIFY: 추가 정보 제공
"""

import os
import re
from typing import Dict, Any, List, Optional

from src.agents.state import ConversationHistory
from src.agents.models import (
    FeedbackParseResult, FeedbackAction, IdentifierSource,
    EntityAnalysisResult, LinkableColumnInfo, EntityRelationType
)
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
    
    if history.get("entity_decisions"):
        lines.append("[PREVIOUS ENTITY IDENTIFIER DECISIONS]")
        for dec in history["entity_decisions"][-3:]:
            lines.append(f"- {dec['file']}: {dec['response']}")
        lines.append("")
    
    return "\n".join(lines)


def parse_human_feedback_to_column(
    feedback: str,
    available_columns: List[str],
    master_identifier: Optional[str],
    file_path: str,
    file_context: Optional[Dict[str, Any]] = None
) -> FeedbackParseResult:
    """
    LLM 기반으로 사용자 피드백 의도를 파악하고 액션 결정 (단순화 버전)
    
    Actions:
    - SKIP: 파일 제외
    - ACCEPT: entity identifier 지정 (컬럼/파일명/FK 등 - LLM이 통합 판단)
    - CLARIFY: 추가 정보 제공
    
    Returns:
        FeedbackParseResult: 통합된 피드백 결과
    """
    feedback_stripped = feedback.strip()
    if not feedback_stripped:
        return FeedbackParseResult(action=FeedbackAction.CLARIFY, reasoning="Empty feedback")
    
    basename = os.path.basename(file_path)
    name_without_ext = os.path.splitext(basename)[0]
    file_ext = os.path.splitext(basename)[1].lower()
    
    # 파일 컨텍스트 구성
    if file_context is None:
        file_context = {}
    
    file_type = file_context.get("file_type", "unknown")
    column_details = file_context.get("column_details", [])
    is_signal = file_ext in [".vital", ".vitaldb", ".edf", ".bdf"] or file_type == "signal"
    has_columns = len(available_columns) > 0
    
    # 파일명에서 숫자 추출 (ID 후보)
    numbers_in_filename = re.findall(r'\d+', name_without_ext)
    potential_id = int(numbers_in_filename[-1]) if numbers_in_filename else None
    
    # column_details에서 샘플 정보 추출
    column_samples_str = ""
    if column_details and isinstance(column_details, list):
        for col_info in column_details[:5]:
            col_name = col_info.get('column_name', '')
            col_type = col_info.get('column_type', 'unknown')
            samples = col_info.get('samples', [])[:3]
            column_samples_str += f"    - '{col_name}' ({col_type}): {samples}\n"
    
    print(f"   🧠 [LLM] Parsing feedback: '{feedback_stripped[:50]}...'")
    
    try:
        prompt = f"""You are parsing user feedback for a medical data indexing system.
Determine the user's intent and how to identify records in this file.

[FILE CONTEXT]
- Filename: {basename}
- File type: {file_type} ({'signal/binary' if is_signal else 'tabular'})
- Available columns: {available_columns[:15] if available_columns else 'None (signal file)'}
- Potential ID from filename: {potential_id}
- Project Master Entity Identifier: {master_identifier or 'Not set'}
{f'[COLUMN SAMPLES]{chr(10)}{column_samples_str}' if column_samples_str else ''}

[USER FEEDBACK]
"{feedback_stripped}"

[TASK]
Determine what the user wants:

1. "skip" - User wants to EXCLUDE this file from processing
   Keywords: skip, pass, 제외, 건너뛰기, don't process

2. "accept" - User is SPECIFYING the entity identifier for this file
   This includes:
   - Confirming AI suggestion ("ok", "yes", "맞아")
   - Specifying a column ("use caseid", "subjectid")
   - Indicating filename is the ID ("filename is ID", "이건 vital 파일")
   - Any indication of how to link this file to the master identifier

3. "clarify" - User is providing ADDITIONAL INFO without specifying identifier
   - Questions ("어떤 컬럼이 있어?")
   - Context info ("이건 수술 데이터야")

[OUTPUT FORMAT - JSON]
{{
    "action": "skip|accept|clarify",
    "identifier_column": "column name to use as identifier (null if N/A)",
    "identifier_source": "column|filename|inferred" (where the identifier value comes from),
    "identifier_value": "specific value if from filename, else null",
    "reasoning": "How you interpreted the feedback",
    "user_intent": "사용자 의도 한글 요약"
}}

Rules:
- If user says "ok/yes/맞아" → action="accept" with previous suggestion
- If user names a column → action="accept", identifier_source="column"
- If no columns & user confirms → action="accept", identifier_source="filename"
- identifier_column can be "caseid" even if not in columns (virtual column from filename)
"""
        
        result = _get_llm_client().ask_json(prompt)
        
        if "error" in result:
            print(f"   ⚠️ LLM error: {result.get('error')}")
            return _parse_feedback_fallback(feedback_stripped, available_columns, file_path)
        
        # Action 파싱
        raw_action = result.get("action", "clarify").lower()
        
        if raw_action == "skip":
            return FeedbackParseResult(
                action=FeedbackAction.SKIP,
                reasoning=result.get("reasoning", "User requested skip"),
                user_intent=result.get("user_intent", "파일 제외")
            )
        
        elif raw_action == "accept":
            # Identifier source 결정
            identifier_source_str = result.get("identifier_source", "column")
            try:
                identifier_source = IdentifierSource(identifier_source_str)
            except ValueError:
                identifier_source = IdentifierSource.COLUMN if has_columns else IdentifierSource.FILENAME
            
            # Identifier column 결정
            identifier_column = result.get("identifier_column")
            if identifier_column and available_columns:
                # 컬럼 이름 매칭
                columns_lower = [c.lower() for c in available_columns]
                if identifier_column.lower() in columns_lower:
                    idx = columns_lower.index(identifier_column.lower())
                    identifier_column = available_columns[idx]
                    identifier_source = IdentifierSource.COLUMN
            
            # filename에서 추출하는 경우
            identifier_value = result.get("identifier_value")
            if identifier_source == IdentifierSource.FILENAME:
                identifier_column = identifier_column or "caseid"
                identifier_value = identifier_value or potential_id or name_without_ext
            
            return FeedbackParseResult(
                action=FeedbackAction.ACCEPT,
                identifier_column=identifier_column,
                identifier_source=identifier_source,
                identifier_value=identifier_value,
                reasoning=result.get("reasoning", "User specified identifier"),
                user_intent=result.get("user_intent", "Entity Identifier 지정")
            )
        
        else:  # clarify
            return FeedbackParseResult(
                action=FeedbackAction.CLARIFY,
                reasoning=result.get("reasoning", feedback_stripped),
                user_intent=result.get("user_intent", "추가 정보 제공"),
                clarification=feedback_stripped
            )
        
    except Exception as e:
        print(f"   ⚠️ LLM call failed: {e}")
        return _parse_feedback_fallback(feedback_stripped, available_columns, file_path)


def _parse_feedback_fallback(
    feedback: str,
    available_columns: List[str],
    file_path: str
) -> FeedbackParseResult:
    """
    LLM 실패 시 규칙 기반 폴백 파싱 (단순화)
    """
    feedback_lower = feedback.lower().strip()
    basename = os.path.basename(file_path)
    name_without_ext = os.path.splitext(basename)[0]
    
    # 스킵 키워드
    if feedback_lower in ["skip", "스킵", "건너뛰기", "pass", "제외"]:
        return FeedbackParseResult(
            action=FeedbackAction.SKIP, 
            reasoning="Skip keyword (fallback)"
        )
    
    # 확인 키워드 → ACCEPT
    if feedback_lower in ["ok", "yes", "y", "확인", "맞아", "네", "그래", "agree"]:
        return FeedbackParseResult(
            action=FeedbackAction.ACCEPT,
            identifier_source=IdentifierSource.INFERRED,
            reasoning="Confirmation keyword (fallback)"
        )
    
    # 컬럼명 직접 매칭 → ACCEPT
    if available_columns:
        columns_lower = [c.lower() for c in available_columns]
        if feedback_lower in columns_lower:
            idx = columns_lower.index(feedback_lower)
            return FeedbackParseResult(
                action=FeedbackAction.ACCEPT,
                identifier_column=available_columns[idx],
                identifier_source=IdentifierSource.COLUMN,
                reasoning="Direct column match (fallback)"
            )
    
    # 컬럼 없으면 파일명 사용 → ACCEPT
    if not available_columns:
        numbers = re.findall(r'\d+', name_without_ext)
        caseid = int(numbers[-1]) if numbers else name_without_ext
        return FeedbackParseResult(
            action=FeedbackAction.ACCEPT,
            identifier_column="caseid" if numbers else "file_id",
            identifier_source=IdentifierSource.FILENAME,
            identifier_value=caseid,
            reasoning="No columns, using filename (fallback)"
        )
    
    # 기본: CLARIFY
    return FeedbackParseResult(
        action=FeedbackAction.CLARIFY,
        reasoning=f"Could not parse: {feedback}",
        clarification=feedback
    )


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
    global_master = context.get("master_identifier") or "None"
    
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
        "entity_conflict": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  🔗 Entity Identifier Mismatch - Confirmation Required                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     The project's Master Entity Identifier is '{global_master}'.
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
        "entity_uncertain": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  🔍 Entity Identifier Column Required                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     AI could not identify a Patient/Case identifier column.
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
""",
        "entity_uncertain": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  📁 파일: {filename}
│  📋 컬럼: {columns_str}
├─────────────────────────────────────────────────────────────────────────────┤

{reasoning}

└─────────────────────────────────────────────────────────────────────────────┘
"""
    }
    
    # LLM prompt
    task_descriptions = {
        "entity_conflict": f"Column '{candidates}' vs Master Identifier '{global_master}'. Ask user to clarify.",
        "entity_uncertain": f"No clear identifier found. Candidate is '{candidates}' with low confidence.",
        "metadata_uncertain": f"Cannot determine if file is metadata or data.",
        "general_uncertainty": f"Issue: {ai_msg}",
        "entity_uncertain": f"Entity identification uncertain. Candidate: '{candidates}'. Ask user to confirm the identifier for this file."
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


# =============================================================================
# Entity Feedback Parsing (NEW - Entity Understanding 지원)
# =============================================================================

def parse_entity_feedback(
    feedback: str,
    available_columns: List[str],
    current_entity: Optional[Dict[str, Any]] = None,
    file_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    사용자 피드백에서 Entity 정보를 추출합니다.
    
    예시 피드백:
    - "둘다 primary key여야해. subjectID는 환자ID가 맞고 caseid는 수술ID야. 한명의 환자가 여러번의 수술을 받았을수 있어"
    - "caseid로 연결해"
    - "이 테이블은 수술 기록이야"
    
    Returns:
        Dict with:
        - action: "update_entity" | "confirm" | "skip" | "clarify"
        - entity_updates: Entity 정보 업데이트 (있는 경우)
        - clarification: 추가 정보 (있는 경우)
    """
    feedback_stripped = feedback.strip()
    if not feedback_stripped:
        return {"action": "clarify", "clarification": "Empty feedback"}
    
    if file_context is None:
        file_context = {}
    
    basename = file_context.get("filename", "unknown.csv")
    
    print(f"   🧠 [LLM] Parsing entity feedback: '{feedback_stripped[:60]}...'")
    
    # 현재 Entity 정보 요약
    current_entity_str = ""
    if current_entity:
        current_entity_str = f"""
[CURRENT ENTITY UNDERSTANDING]
- Row represents: {current_entity.get('row_represents', 'unknown')}
- Entity identifier: {current_entity.get('entity_identifier', 'unknown')}
- Linkable columns: {[c.get('column_name') for c in current_entity.get('linkable_columns', [])]}
"""
    
    try:
        prompt = f"""You are parsing user feedback about table structure and entity relationships.
The user is explaining what this table represents and how columns relate to each other.

[FILE CONTEXT]
- Filename: {basename}
- Available columns: {available_columns[:20]}
{current_entity_str}

[USER FEEDBACK]
"{feedback_stripped}"

[TASK]
Extract entity information from the user's feedback:

1. What does each row represent? (e.g., "surgery", "patient", "lab_result")
2. Which column(s) are identifiers and what entities do they represent?
3. What are the relationships between entities? (e.g., patient → surgery is 1:N)

[OUTPUT FORMAT - JSON]
{{
    "action": "update_entity|confirm|skip|clarify",
    "row_represents": "what each row represents (or null if not specified)",
    "row_represents_kr": "한글 설명",
    "entity_identifier": "main identifier column for this table",
    "linkable_columns": [
        {{
            "column_name": "column name",
            "represents_entity": "what entity this column refers to",
            "represents_entity_kr": "한글",
            "relation_type": "self|parent|child|reference",
            "description": "user's description of this column"
        }}
    ],
    "hierarchy_explanation": "Natural language summary of relationships from user feedback",
    "user_intent": "사용자 의도 요약 (한글)",
    "confidence": 0.0-1.0
}}

[IMPORTANT RULES]
1. "self" relation_type = column that identifies rows in THIS table (the row's primary key)
2. "parent" relation_type = column that links to a HIGHER-level entity (e.g., patient for surgery table)
3. If user says "A는 B야" (A is B), extract the column-entity mapping
4. If user mentions "1:N", "여러개", "여러번" → the N side is "self", the 1 side is "parent"
5. If user says "둘다 primary key" or mentions two IDs, determine which one represents the ROW (self) vs which links to parent
6. Preserve user's Korean explanations in Korean fields
7. ALWAYS set action="update_entity" when user provides entity information

[CRITICAL - DETERMINING SELF vs PARENT]
- If user says "한명의 환자가 여러번의 수술" → rows are surgeries (caseid=self), patient is parent (subjectid=parent)
- The column representing what EACH ROW IS should be "self"
- The column linking to a HIGHER entity (fewer unique values, 1 side of 1:N) should be "parent"

[EXAMPLE 1]
User: "둘다 primary key여야해. subjectID는 환자ID가 맞고 caseid는 수술ID야. 한명의 환자가 여러번의 수술을 받았을수 있어"
Analysis:
- "한명의 환자가 여러번의 수술" → patient:surgery = 1:N
- Each ROW represents a SURGERY (caseid is unique per row) → caseid is "self"
- subjectid links to patient (can repeat) → subjectid is "parent"
Output:
→ action: "update_entity"
→ row_represents: "surgery"
→ row_represents_kr: "수술"
→ entity_identifier: "caseid"
→ linkable_columns: [
    {{"column_name": "caseid", "represents_entity": "surgery", "represents_entity_kr": "수술", "relation_type": "self"}},
    {{"column_name": "subjectid", "represents_entity": "patient", "represents_entity_kr": "환자", "relation_type": "parent"}}
]
→ hierarchy_explanation: "한 환자(subjectid)가 여러 수술(caseid)을 받을 수 있음 (1:N)"

[EXAMPLE 2]
User: "caseid로 연결해"
Output:
→ action: "update_entity"
→ entity_identifier: "caseid"
→ linkable_columns: [{{"column_name": "caseid", "relation_type": "self"}}]
"""

        result = _get_llm_client().ask_json(prompt)
        
        if "error" in result:
            print(f"   ⚠️ LLM error in entity parsing: {result.get('error')}")
            return _parse_entity_feedback_fallback(feedback_stripped, available_columns)
        
        action = result.get("action", "clarify")
        
        if action == "skip":
            return {"action": "skip", "user_intent": result.get("user_intent", "파일 제외")}
        
        if action == "confirm":
            return {"action": "confirm", "user_intent": result.get("user_intent", "확인")}
        
        # Entity 정보 추출
        linkable_cols = []
        for col_info in result.get("linkable_columns", []):
            if not col_info.get("column_name"):
                continue
            
            relation_type_str = col_info.get("relation_type", "reference")
            try:
                relation_type = EntityRelationType(relation_type_str)
            except ValueError:
                relation_type = EntityRelationType.REFERENCE
            
            linkable_cols.append(LinkableColumnInfo(
                column_name=col_info.get("column_name"),
                represents_entity=col_info.get("represents_entity", "unknown"),
                represents_entity_kr=col_info.get("represents_entity_kr", ""),
                relation_type=relation_type,
                cardinality=col_info.get("cardinality", "N:1"),
                is_primary_identifier=(relation_type == EntityRelationType.SELF)
            ))
        
        return {
            "action": "update_entity",
            "entity_updates": {
                "row_represents": result.get("row_represents"),
                "row_represents_kr": result.get("row_represents_kr"),
                "entity_identifier": result.get("entity_identifier"),
                "linkable_columns": linkable_cols,
                "hierarchy_explanation": result.get("hierarchy_explanation", ""),
                "user_feedback_applied": feedback_stripped
            },
            "user_intent": result.get("user_intent", "Entity 정보 제공"),
            "confidence": result.get("confidence", 0.8)
        }
        
    except Exception as e:
        print(f"   ⚠️ Entity feedback parsing failed: {e}")
        return _parse_entity_feedback_fallback(feedback_stripped, available_columns)


def _parse_entity_feedback_fallback(
    feedback: str,
    available_columns: List[str]
) -> Dict[str, Any]:
    """Entity 피드백 파싱 폴백 (규칙 기반)"""
    feedback_lower = feedback.lower()
    
    # 스킵 키워드
    skip_keywords = ['skip', 'pass', '제외', '건너뛰기', '스킵', '패스']
    if any(kw in feedback_lower for kw in skip_keywords):
        return {"action": "skip", "user_intent": "파일 제외"}
    
    # 확인 키워드
    confirm_keywords = ['ok', 'yes', '맞아', '확인', '좋아', 'correct', '네']
    if any(kw in feedback_lower for kw in confirm_keywords):
        return {"action": "confirm", "user_intent": "확인"}
    
    # 컬럼 언급 찾기
    linkable_cols = []
    for col in available_columns:
        if col.lower() in feedback_lower:
            # 이 컬럼이 무엇을 나타내는지 추측
            entity = "unknown"
            relation = EntityRelationType.REFERENCE
            
            if 'id' in col.lower():
                if 'patient' in col.lower() or 'subject' in col.lower() or '환자' in feedback_lower:
                    entity = "patient"
                    relation = EntityRelationType.PARENT
                elif 'case' in col.lower() or '수술' in feedback_lower:
                    entity = "surgery"
                    relation = EntityRelationType.SELF
                else:
                    relation = EntityRelationType.REFERENCE
            
            linkable_cols.append(LinkableColumnInfo(
                column_name=col,
                represents_entity=entity,
                represents_entity_kr="",
                relation_type=relation,
                is_primary_identifier=(relation == EntityRelationType.SELF)
            ))
    
    if linkable_cols:
        # 첫 번째 SELF 컬럼을 entity_identifier로
        identifier = None
        for lc in linkable_cols:
            if lc.relation_type == EntityRelationType.SELF:
                identifier = lc.column_name
                break
        if not identifier and linkable_cols:
            identifier = linkable_cols[0].column_name
        
        return {
            "action": "update_entity",
            "entity_updates": {
                "entity_identifier": identifier,
                "linkable_columns": linkable_cols,
                "user_feedback_applied": feedback
            },
            "user_intent": "컬럼 정보 제공 (폴백)",
            "confidence": 0.5
        }
    
    # 기본: clarify
    return {
        "action": "clarify",
        "clarification": feedback,
        "user_intent": "추가 정보 (폴백)"
    }

