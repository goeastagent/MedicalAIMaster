# src/agents/nodes/batch.py
"""
Batch Processing Nodes - 2-Phase Workflow
"""

import os
from datetime import datetime
from typing import Dict, Any, List

from src.agents.state import (
    AgentState, FileClassification, ClassificationResult, ProcessingProgress
)
from src.agents.nodes.common import processors, ontology_manager
from src.agents.helpers.llm_helpers import ask_llm_is_metadata
from src.agents.helpers.metadata_helpers import (
    build_lightweight_classification_context,  # NEW: 경량 분류용
    parse_metadata_content,
    # NEW: Hybrid Approach - LLM Enrichment
    extract_relevant_context,
    enrich_definitions_with_llm,
    infer_concept_relationships,
)
from src.config import HumanReviewConfig, ProcessingConfig, MetadataEnrichmentConfig


def batch_classifier_node(state: AgentState) -> Dict[str, Any]:
    """
    [Phase 1] 전체 파일 분류 노드
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
    
    for idx, file_path in enumerate(input_files):
        filename = os.path.basename(file_path)
        file_ext = os.path.splitext(filename)[1].lower()
        print(f"\n   [{idx+1}/{len(input_files)}] {filename}")
        
        try:
            # Rule-based: Signal files are always data
            if file_ext.lstrip('.') in ProcessingConfig.SIGNAL_EXTENSIONS:
                classifications[file_path] = {
                    "file_path": file_path,
                    "filename": filename,
                    "classification": "data",
                    "confidence": 1.0,
                    "reasoning": f"Signal file ({file_ext}) - always transactional data",
                    "indicators": {"file_type": "signal"},
                    "needs_review": False,
                    "human_confirmed": False
                }
                data_files.append(file_path)
                print(f"      📈 Signal 데이터 (100% - rule-based)")
                continue
            
            # Check if file extension is supported (without full extraction)
            if not any(p.can_handle(file_path) for p in processors):
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
            
            # NEW: 경량 context 생성 (extract_metadata 없이 직접 파일에서 샘플 읽기)
            # 이로써 metadata/data 분류에만 집중하고, 전체 메타데이터 추출은 loader에서 수행
            context = build_lightweight_classification_context(file_path)
            meta_result = ask_llm_is_metadata(context)
            
            confidence = meta_result.get("confidence", 0.0)
            is_metadata = meta_result.get("is_metadata", False)
            reasoning = meta_result.get("reasoning", "")
            indicators = meta_result.get("indicators", {})
            
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
    
    classification_result: ClassificationResult = {
        "total_files": len(input_files),
        "metadata_files": metadata_files,
        "data_files": data_files,
        "uncertain_files": uncertain_files,
        "classifications": classifications
    }
    
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
    print(f"   - 메타데이터: {len(metadata_files)}개")
    print(f"   - 데이터: {len(data_files)}개")
    print(f"   - 불확실: {len(uncertain_files)}개")
    print("="*80)
    
    # NOTE: 불확실한 파일이 있어도 여기서는 human_question을 설정하지 않음
    # classification_review_node에서 interrupt()를 통해 직접 처리함
    
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
    [Phase 1-2] 분류 확인 노드 (Human-in-the-Loop with interrupt())
    
    interrupt()를 사용하여 노드 내부에서 직접 human input을 받습니다.
    - 질문 생성 → interrupt() 호출 → 사용자 응답 수신 → 처리
    - 대화 히스토리 자동 저장
    """
    from langgraph.types import interrupt
    from src.agents.nodes.common import (
        add_conversation_turn, 
        create_empty_conversation_history
    )
    
    print("\n" + "="*80)
    print("🧑 [CLASSIFICATION REVIEW] Human-in-the-Loop")
    print("="*80)
    
    classification_result = state.get("classification_result", {})
    uncertain_files = classification_result.get("uncertain_files", [])
    classifications = classification_result.get("classifications", {})
    
    # 대화 히스토리 가져오기 (없으면 생성)
    dataset_id = state.get("current_dataset_id", "unknown")
    conversation_history = state.get("conversation_history")
    if not conversation_history:
        conversation_history = create_empty_conversation_history(dataset_id)
    
    # 불확실한 파일이 없으면 스킵
    if not uncertain_files:
        print("   ✅ 불확실한 파일 없음 - 리뷰 스킵")
        return {
            "needs_human_review": False,
            "logs": ["✅ [Review] 모든 파일 분류 확정"]
        }
    
    # =========================================================================
    # Human-in-the-Loop: 불확실한 파일이 있으면 interrupt로 사용자에게 질문
    # =========================================================================
    
    # 반복 처리 (여러 라운드 가능)
    remaining_uncertain = uncertain_files.copy()
    current_classifications = classifications.copy()
    
    while remaining_uncertain:
        # 1. 질문 생성
        question = _generate_classification_question(remaining_uncertain, current_classifications)
        
        # 2. 컨텍스트 스냅샷 생성 (Knowledge Graph용)
        context_snapshot = {
            "uncertain_files": remaining_uncertain.copy(),
            "classifications": {
                fp: {
                    "classification": clf.get("classification"),
                    "confidence": clf.get("confidence"),
                    "reasoning": clf.get("reasoning", "")[:200]
                }
                for fp, clf in current_classifications.items()
                if fp in remaining_uncertain
            },
            "total_metadata": len(classification_result.get("metadata_files", [])),
            "total_data": len(classification_result.get("data_files", []))
        }
        
        print(f"\n   ❓ {len(remaining_uncertain)}개 파일에 대해 사용자 확인 요청")
        print("="*80)
        
        # 3. interrupt() 호출 - 여기서 그래프 실행이 중단되고 사용자 응답을 기다림
        # 사용자가 자연어로 자유롭게 응답하면 LLM이 파싱함
        human_response = interrupt({
            "type": "classification_review",
            "question": question,
            "uncertain_files": remaining_uncertain,
            "context": context_snapshot
        })
        
        # 4. 사용자 응답 처리
        print(f"\n   💬 사용자 피드백 수신: '{human_response}'")
        
        # 5. 피드백 파싱 및 분류 업데이트
        current_classifications = _parse_classification_feedback(
            feedback=human_response,
            classifications=current_classifications,
            uncertain_files=remaining_uncertain
        )
        
        # 6. 결과에 따른 분류
        new_metadata_files = []
        new_data_files = []
        new_remaining_uncertain = []
        
        for file_path in remaining_uncertain:
            clf = current_classifications.get(file_path, {})
            if clf.get("human_confirmed"):
                if clf["classification"] == "metadata":
                    new_metadata_files.append(file_path)
                elif clf["classification"] == "data":
                    new_data_files.append(file_path)
                # unknown은 제외됨 (skip)
            elif clf.get("needs_review"):
                new_remaining_uncertain.append(file_path)
            elif clf["classification"] == "metadata":
                new_metadata_files.append(file_path)
            elif clf["classification"] == "data":
                new_data_files.append(file_path)
        
        # 7. 에이전트 액션 결정
        action_parts = []
        if new_metadata_files:
            action_parts.append(f"메타데이터로 분류: {len(new_metadata_files)}개")
        if new_data_files:
            action_parts.append(f"데이터로 분류: {len(new_data_files)}개")
        skipped = len(remaining_uncertain) - len(new_metadata_files) - len(new_data_files) - len(new_remaining_uncertain)
        if skipped > 0:
            action_parts.append(f"제외: {skipped}개")
        agent_action = ", ".join(action_parts) if action_parts else "변경 없음"
        
        # 8. 대화 히스토리에 기록 + 자동 저장
        conversation_history = add_conversation_turn(
            history=conversation_history,
            review_type="classification",
            agent_question=question,
            human_response=human_response,
            agent_action=agent_action,
            file_path=", ".join([os.path.basename(f) for f in remaining_uncertain[:3]]),
            context_summary=f"불확실한 파일 {len(remaining_uncertain)}개 분류 확인",
            context_snapshot=context_snapshot,
            auto_save=True
        )
        
        print(f"   ✅ 분류 업데이트: {agent_action}")
        
        # 다음 라운드 준비
        remaining_uncertain = new_remaining_uncertain
        
        # 추가 확인이 필요 없으면 루프 종료
        if not remaining_uncertain:
            break
    
    # =========================================================================
    # 최종 결과 생성
    # =========================================================================
    
    # 최종 분류 결과 집계
    final_metadata = classification_result.get("metadata_files", []).copy()
    final_data = classification_result.get("data_files", []).copy()
    
    for file_path, clf in current_classifications.items():
        if clf.get("human_confirmed") or not clf.get("needs_review"):
            if clf["classification"] == "metadata" and file_path not in final_metadata:
                final_metadata.append(file_path)
            elif clf["classification"] == "data" and file_path not in final_data:
                final_data.append(file_path)
    
    updated_result: ClassificationResult = {
        "total_files": classification_result["total_files"],
        "metadata_files": final_metadata,
        "data_files": final_data,
        "uncertain_files": [],  # 모두 처리됨
        "classifications": current_classifications
    }
    
    progress = state.get("processing_progress", {})
    progress["phase"] = "classification_review"
    
    print(f"\n   ✅ 분류 확정 완료")
    print(f"      - 메타데이터: {len(final_metadata)}개")
    print(f"      - 데이터: {len(final_data)}개")
    print("="*80)
    
    return {
        "classification_result": updated_result,
        "processing_progress": progress,
        "conversation_history": conversation_history,
        "needs_human_review": False,
        "human_feedback": None,
        "logs": [f"✅ [Review] 분류 확정 완료 - 메타데이터: {len(final_metadata)}개, 데이터: {len(final_data)}개"]
    }


def _generate_classification_question(
    uncertain_files: List[str], 
    classifications: Dict[str, FileClassification]
) -> str:
    """
    Generate user-friendly classification review question using LLM.
    Only asks about uncertain files with low confidence.
    """
    from src.utils.llm_client import get_llm_client
    
    # Prepare file summaries for uncertain files only
    file_summaries = []
    for idx, file_path in enumerate(uncertain_files[:10], 1):
        clf = classifications.get(file_path, {})
        filename = clf.get("filename", os.path.basename(file_path))
        predicted = clf.get("classification", "unknown")
        confidence = clf.get("confidence", 0.0)
        reasoning = clf.get("reasoning", "")[:150]
        
        file_summaries.append({
            "index": idx,
            "filename": filename,
            "predicted": predicted,
            "confidence": f"{confidence:.0%}",
            "reasoning": reasoning
        })
    
    # LLM prompt for question generation
    prompt = f"""You are a UI assistant for a medical data classification system.
Generate a concise, user-friendly question asking the user to verify file classifications.

[UNCERTAIN FILES - Need Review]
{_format_file_summaries_for_prompt(file_summaries)}

[TASK]
Create a clear question in Korean that:
1. Lists each file with: number, filename, AI prediction (📖=metadata, 📊=data), confidence, and brief reason
2. Explains response options: "ok" to approve all, or specify changes like "1번 데이터" or "2번 제외"

Keep it concise. Output plain text only (no JSON):"""

    try:
        llm = get_llm_client()
        generated_question = llm.ask_text(prompt)
        return generated_question.strip()
    except Exception as e:
        print(f"   ⚠️ LLM question generation failed, using fallback: {e}")
        return _generate_fallback_question(uncertain_files, classifications)


def _format_file_summaries_for_prompt(file_summaries: List[Dict]) -> str:
    """Format file summaries for LLM prompt"""
    lines = []
    for fs in file_summaries:
        lines.append(
            f"File {fs['index']}: {fs['filename']}\n"
            f"  - Prediction: {fs['predicted']} ({fs['confidence']})\n"
            f"  - Reason: {fs['reasoning'] or 'N/A'}"
        )
    return "\n".join(lines)


def _generate_fallback_question(
    uncertain_files: List[str], 
    classifications: Dict[str, FileClassification]
) -> str:
    """LLM 실패시 사용하는 기본 템플릿 질문"""
    question_parts = [
        "📋 **파일 분류 확인이 필요합니다**\n",
        "아래 파일들의 분류를 확인해주세요:\n"
    ]
    
    for idx, file_path in enumerate(uncertain_files[:5], 1):
        clf = classifications.get(file_path, {})
        filename = clf.get("filename", os.path.basename(file_path))
        predicted = clf.get("classification", "unknown")
        confidence = clf.get("confidence", 0.0)
        reasoning = clf.get("reasoning", "")[:100]
        
        pred_emoji = "📖" if predicted == "metadata" else "📊" if predicted == "data" else "❓"
        pred_text = "메타데이터" if predicted == "metadata" else "데이터" if predicted == "data" else "알 수 없음"
        
        question_parts.append(
            f"\n**{idx}. {filename}**\n"
            f"   - AI 예측: {pred_emoji} {pred_text} ({confidence:.0%})\n"
            f"   - 판단 근거: {reasoning}...\n"
        )
    
    if len(uncertain_files) > 5:
        question_parts.append(f"\n... 외 {len(uncertain_files) - 5}개 파일\n")
    
    question_parts.append(
        "\n**응답 방법:**\n"
        "- 모두 맞으면: `확인`, `ok`, `모두 맞아` 등\n"
        "- 수정 필요: `1번 데이터`, `2번 메타데이터로 변경` 등 자연어로\n"
        "- 파일 제외: `3번 제외`, `3번 스킵` 등\n"
    )
    
    return "".join(question_parts)

def _parse_classification_feedback(
    feedback: str, 
    classifications: Dict[str, FileClassification],
    uncertain_files: List[str]
) -> Dict[str, FileClassification]:
    """
    Parse user's natural language feedback using LLM and update classifications.
    
    Handles various response formats:
    - Simple approval: "ok", "확인", "맞아"
    - Index-based: "1번 데이터", "2번은 메타데이터야"
    - Filename-based: "clinical_info는 데이터고 parameters는 메타데이터야"
    - Descriptive: "컬럼 설명이 있는 파일은 메타데이터야", "실제 환자 기록이 있는건 데이터"
    - Mixed explanations with classification hints
    """
    from src.utils.llm_client import get_llm_client
    import json
    
    updated = classifications.copy()
    feedback_stripped = feedback.strip()
    
    if not feedback_stripped:
        return updated
    
    # Prepare detailed file context for LLM
    file_context = []
    for idx, file_path in enumerate(uncertain_files, 1):
        clf = classifications.get(file_path, {})
        filename = clf.get("filename", os.path.basename(file_path))
        current_type = clf.get("classification", "unknown")
        confidence = clf.get("confidence", 0.0)
        reasoning = clf.get("reasoning", "")[:100]
        
        file_context.append({
            "index": idx,
            "filename": filename,
            "file_path": file_path,
            "ai_prediction": current_type,
            "confidence": f"{confidence:.0%}",
            "ai_reasoning": reasoning
        })
    
    # Enhanced LLM prompt for flexible natural language parsing
    prompt = f"""You are parsing user feedback about file classification for a medical data indexing system.

[CONTEXT - FILES UNDER REVIEW]
{json.dumps(file_context, indent=2)}

[USER'S RESPONSE]
"{feedback_stripped}"

[YOUR TASK]
Analyze the user's natural language response and extract classification decisions.
The user may:
1. Approve all AI predictions ("ok", "확인", "맞아", "그대로 해")
2. Refer to files by index number ("1번은 데이터", "2번 메타데이터로")
3. Refer to files by filename ("clinical_info는 데이터야", "parameters 파일은 메타데이터")
4. Give descriptive explanations ("컬럼 설명이 있는 파일은 메타데이터", "실제 환자 데이터가 있는건 data")
5. Provide mixed responses with partial approvals and corrections

[CLASSIFICATION DEFINITIONS]
- METADATA: Files that DESCRIBE other data (column definitions, parameter lists, codebooks, data dictionaries)
- DATA: Files containing actual records/measurements (patient records, clinical data, transactions)
- SKIP: Files to exclude from processing

[OUTPUT FORMAT - JSON ONLY]
{{
    "action": "approve_all" | "modify" | "partial_approve",
    "changes": [
        {{
            "index": <1-based index>,
            "filename": "<filename for reference>",
            "new_type": "metadata" | "data" | "skip",
            "reason": "<brief reason extracted from user feedback>"
        }}
    ],
    "unmentioned_files": "approve" | "keep_uncertain",
    "summary": "<brief summary of what you understood>"
}}

RULES:
- If user approves everything: {{"action": "approve_all", "changes": [], "summary": "..."}}
- If user mentions specific files: extract each file's new classification
- If user gives general rules (e.g., "files with column descriptions are metadata"): apply to matching files
- Match filenames flexibly (partial match OK, case-insensitive)
- "unmentioned_files": "approve" if user seems satisfied with AI predictions for unmentioned files
- "unmentioned_files": "keep_uncertain" if only mentioned files should be updated
"""

    try:
        llm = get_llm_client()
        parsed_result = llm.ask_json(prompt)
        
        action = parsed_result.get("action", "unclear")
        summary = parsed_result.get("summary", "")
        
        print(f"   🧠 [Parser] LLM 분석 결과: {summary}")
        
        if action == "approve_all":
            # 전체 승인
            print("   ✅ [Parser] 전체 승인")
            for file_path in uncertain_files:
                if file_path in updated:
                    updated[file_path]["human_confirmed"] = True
                    updated[file_path]["needs_review"] = False
            return updated
        
        elif action in ["modify", "partial_approve"]:
            changes = parsed_result.get("changes", [])
            unmentioned = parsed_result.get("unmentioned_files", "keep_uncertain")
            
            print(f"   ✏️ [Parser] {len(changes)}개 파일 분류 결정 감지")
            
            # 변경된 파일 인덱스 추적
            modified_indices = set()
            
            for change in changes:
                idx = change.get("index", 0) - 1  # 1-indexed → 0-indexed
                new_type = change.get("new_type", "").lower()
                reason = change.get("reason", "")
                filename = change.get("filename", "")
                
                if 0 <= idx < len(uncertain_files):
                    file_path = uncertain_files[idx]
                    modified_indices.add(idx)
                    
                    if new_type == "skip":
                        updated[file_path]["classification"] = "unknown"
                        updated[file_path]["human_confirmed"] = True
                        updated[file_path]["needs_review"] = False
                        print(f"      - [{idx+1}] {filename}: 제외 ({reason})")
                    elif new_type == "metadata":
                        updated[file_path]["classification"] = "metadata"
                        updated[file_path]["human_confirmed"] = True
                        updated[file_path]["needs_review"] = False
                        print(f"      - [{idx+1}] {filename}: 메타데이터 ({reason})")
                    elif new_type == "data":
                        updated[file_path]["classification"] = "data"
                        updated[file_path]["human_confirmed"] = True
                        updated[file_path]["needs_review"] = False
                        print(f"      - [{idx+1}] {filename}: 데이터 ({reason})")
            
            # 언급되지 않은 파일 처리
            if unmentioned == "approve":
                for idx, file_path in enumerate(uncertain_files):
                    if idx not in modified_indices and file_path in updated:
                        updated[file_path]["human_confirmed"] = True
                        updated[file_path]["needs_review"] = False
                print(f"   ✅ [Parser] 언급되지 않은 파일들은 AI 예측 승인")
            else:
                remaining = len(uncertain_files) - len(modified_indices)
                if remaining > 0:
                    print(f"   ⏳ [Parser] {remaining}개 파일은 여전히 확인 필요")
            
            return updated
        
        else:
            # 이해 불가 - 폴백
            print(f"   ⚠️ [Parser] 응답 해석 어려움, 정규식 폴백 시도")
            return _parse_feedback_regex_fallback(feedback, classifications, uncertain_files)
            
    except Exception as e:
        print(f"   ⚠️ [Parser] LLM 파싱 실패: {e}")
        print("   🔄 [Parser] 정규식 폴백 파싱 시도...")
        return _parse_feedback_regex_fallback(feedback, classifications, uncertain_files)


def _parse_feedback_regex_fallback(
    feedback: str,
    classifications: Dict[str, FileClassification],
    uncertain_files: List[str]
) -> Dict[str, FileClassification]:
    """LLM 실패시 정규식 기반 폴백 파싱"""
    import re
    
    updated = classifications.copy()
    feedback_lower = feedback.lower().strip()
    
    # 전체 승인 키워드 체크
    approve_keywords = ["확인", "ok", "yes", "y", "approve", "승인", "모두 맞아", "그대로", "맞아"]
    if feedback_lower in approve_keywords or any(kw in feedback_lower for kw in approve_keywords):
        # 수정 지시가 없는 순수 승인인지 확인
        if not re.search(r'\d+', feedback_lower):
            for file_path in uncertain_files:
                if file_path in updated:
                    updated[file_path]["human_confirmed"] = True
                    updated[file_path]["needs_review"] = False
            return updated
    
    # 개별 수정 패턴 매칭 (더 유연한 패턴)
    # 패턴1: "1:데이터", "1：메타데이터"
    corrections = re.findall(r'(\d+)\s*[:：]\s*(메타데이터|데이터|metadata|data|제외|skip)', feedback_lower)
    
    # 패턴2: "1번 데이터", "1번은 메타데이터", "첫번째 data"
    corrections += re.findall(r'(\d+)\s*번?\s*(?:은|는)?\s*(메타데이터|데이터|metadata|data|제외|skip)', feedback_lower)
    
    for idx_str, new_type in corrections:
        idx = int(idx_str) - 1
        
        if 0 <= idx < len(uncertain_files):
            file_path = uncertain_files[idx]
            
            if new_type in ["제외", "skip"]:
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
    [Phase 2-1] 메타데이터 일괄 처리 노드 (Hybrid Approach)
    
    Hybrid 워크플로우:
    1. Rule-based 파싱: parse_metadata_content()로 기본 definitions 추출
    2. 대화 컨텍스트 추출: 사용자와의 이전 대화에서 핵심 정보만 추출
    3. LLM Enrichment: 파싱된 definitions를 의료 도메인 관점에서 풍부하게
    4. 관계 추론: 개념 간의 계층/의미 관계 추론
    5. Neo4j 저장: enriched definitions + relationships를 온톨로지에 저장
    
    이 접근법의 장점:
    - 비용 효율: 규칙 기반 파싱으로 기본 추출 (LLM 비용 0)
    - 환각 최소화: 파싱된 데이터 기반으로만 LLM이 분석
    - 재현성: 규칙 기반 파싱은 결정적
    - 대화 활용: 이전 사용자 피드백을 컨텍스트로 활용
    """
    print("\n" + "="*80)
    print("📖 [METADATA PROCESSOR] Phase 2-1 - 메타데이터 일괄 처리 (Hybrid)")
    print("="*80)
    
    classification_result = state.get("classification_result", {})
    metadata_files = classification_result.get("metadata_files", [])
    progress = state.get("processing_progress", {})
    conversation_history = state.get("conversation_history", {})
    
    # 온톨로지 로드
    ontology = state.get("ontology_context")
    if not ontology or not ontology.get("definitions"):
        ontology = ontology_manager.load() or {
            "definitions": {},
            "relationships": [],
            "hierarchy": [],
            "file_tags": {},
            "column_hierarchy": []  # NEW: 컬럼 계층 정보
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
    
    # =========================================================================
    # Step 1: 대화 컨텍스트 추출 (한 번만)
    # =========================================================================
    conversation_context = ""
    if conversation_history:
        conversation_context = extract_relevant_context(conversation_history)
        if conversation_context:
            print(f"\n   💬 대화 컨텍스트 추출됨 ({len(conversation_context)} chars)")
            print(f"   ├─ 이전 대화 정보가 LLM 분석에 활용됩니다")
    
    # =========================================================================
    # Step 2: 파일별 처리 (Processor 기반 파싱)
    # =========================================================================
    processed_metadata = []
    skipped_metadata = []  # NEW: 스킵된 파일 추적
    total_definitions = 0
    all_definitions = {}  # 모든 파일의 definitions 합침
    
    print(f"\n   ───────── Processor 기반 파싱 ─────────")
    
    for idx, file_path in enumerate(metadata_files):
        filename = os.path.basename(file_path)
        print(f"\n   [{idx+1}/{len(metadata_files)}] {filename}")
        
        try:
            # 파일 태깅
            ontology["file_tags"][file_path] = {
                "type": "metadata",
                "role": "dictionary",
                "confidence": classification_result["classifications"].get(file_path, {}).get("confidence", 0.8),
                "detected_at": datetime.now().isoformat()
            }
            
            # Processor 기반 파싱 (수정됨)
            new_definitions = parse_metadata_content(file_path)
            
            if new_definitions:
                ontology["definitions"].update(new_definitions)
                all_definitions.update(new_definitions)
                total_definitions += len(new_definitions)
                processed_metadata.append(file_path)
                print(f"      ✅ Processor: {len(new_definitions)}개 용어 파싱됨")
            else:
                print(f"      ⚠️ 파싱된 용어 없음 - 스킵")
                skipped_metadata.append({
                    "file": file_path,
                    "filename": filename,
                    "reason": "파싱된 용어 없음"
                })
                
        except Exception as e:
            print(f"      ❌ 파싱 실패: {e} - 스킵")
            skipped_metadata.append({
                "file": file_path,
                "filename": filename,
                "reason": str(e)
            })
    
    # =========================================================================
    # Step 3: LLM Enrichment (모든 definitions 한번에)
    # =========================================================================
    enrichments = []
    relationships_result = {}
    
    if all_definitions:
        print(f"\n   ───────── LLM Enrichment ─────────")
        
        try:
            # LLM으로 definitions 풍부하게 만들기
            # max_chunks 설정: 빠른 테스트 모드면 1개만, 아니면 전체
            max_chunks = None
            if MetadataEnrichmentConfig.FAST_TEST_MODE:
                max_chunks = MetadataEnrichmentConfig.FAST_TEST_MAX_CHUNKS
                print(f"      ⚡ 빠른 테스트 모드: 최대 {max_chunks}개 청크만 처리")
            
            enrichments = enrich_definitions_with_llm(
                definitions=all_definitions,
                conversation_context=conversation_context,
                max_chunks=max_chunks
            )
            
            if enrichments:
                print(f"\n   ✅ LLM Enrichment 완료: {len(enrichments)}개 용어 분석됨")
                
                # Neo4j에 enriched definitions 저장
                try:
                    ontology_manager.enrich_concepts_batch([
                        {
                            "name": e["name"],
                            "enriched_definition": e.get("enriched_definition", ""),
                            "analysis_context": e.get("analysis_context", "")
                        }
                        for e in enrichments
                    ])
                    print(f"   ✅ Neo4j에 enriched definitions 저장됨")
                except Exception as e:
                    print(f"   ⚠️ Neo4j enrichment 저장 실패: {e}")
            
        except Exception as e:
            print(f"   ⚠️ LLM Enrichment 실패: {e}")
        
        # =========================================================================
        # Step 4: 관계 추론
        # =========================================================================
        print(f"\n   ───────── 관계 추론 ─────────")
        
        try:
            relationships_result = infer_concept_relationships(
                definitions=all_definitions,
                enrichments=enrichments,
                conversation_context=conversation_context
            )
            
            # 계층 힌트를 온톨로지에 반영
            hierarchy_hints = relationships_result.get("hierarchy_hints", [])
            if hierarchy_hints:
                for hint in hierarchy_hints:
                    # 기존 hierarchy에 추가 (중복 체크)
                    existing_entities = {h.get("entity_name") for h in ontology.get("hierarchy", [])}
                    if hint.get("concept") not in existing_entities:
                        ontology["hierarchy"].append({
                            "entity_name": hint.get("concept"),
                            "level": hint.get("level", 99),
                            "identifier_column": hint.get("concept"),
                            "confidence": 0.7,
                            "inferred_from": "metadata_analysis"
                        })
                
                # 레벨 정렬
                ontology["hierarchy"].sort(key=lambda x: x.get("level", 99))
                print(f"   ✅ {len(hierarchy_hints)}개 계층 힌트 반영됨")
            
            # 개념 관계를 온톨로지에 반영
            concept_rels = relationships_result.get("concept_relationships", [])
            if concept_rels:
                for rel in concept_rels:
                    # column_hierarchy에 추가
                    if "column_hierarchy" not in ontology:
                        ontology["column_hierarchy"] = []
                    
                    ontology["column_hierarchy"].append({
                        "child_column": rel.get("source"),
                        "parent_column": rel.get("target"),
                        "cardinality": rel.get("cardinality", "N:1"),
                        "hierarchy_type": rel.get("relation_type", "PARENT_OF"),
                        "reasoning": rel.get("reasoning", ""),
                        "table_name": "metadata_inferred"
                    })
                
                print(f"   ✅ {len(concept_rels)}개 개념 관계 반영됨")
                
        except Exception as e:
            print(f"   ⚠️ 관계 추론 실패: {e}")
    
    # =========================================================================
    # Step 5: 온톨로지 저장
    # =========================================================================
    ontology_manager.save(ontology)
    
    progress["phase"] = "metadata_processing"
    progress["metadata_processed"] = processed_metadata
    progress["skipped_metadata_files"] = skipped_metadata  # NEW: 스킵된 파일 기록
    
    # 통계 요약
    enriched_count = len(enrichments)
    rel_count = len(relationships_result.get("concept_relationships", []))
    hierarchy_count = len(relationships_result.get("hierarchy_hints", []))
    skipped_count = len(skipped_metadata)
    
    print(f"\n" + "-"*40)
    print(f"📊 메타데이터 처리 완료 (Processor-based Hybrid):")
    print(f"   - 처리된 파일: {len(processed_metadata)}개")
    if skipped_count > 0:
        print(f"   - 스킵된 파일: {skipped_count}개")
        for skip in skipped_metadata:
            print(f"      └─ {skip['filename']}: {skip['reason']}")
    print(f"   - 파싱된 용어: {total_definitions}개 (Processor)")
    print(f"   - Enriched 용어: {enriched_count}개 (LLM)")
    print(f"   - 추론된 관계: {rel_count}개")
    print(f"   - 계층 힌트: {hierarchy_count}개")
    if conversation_context:
        print(f"   - 대화 컨텍스트: 활용됨 ✓")
    print("="*80)
    
    log_msg = (
        f"📖 [Metadata] Hybrid 처리 완료: "
        f"{len(processed_metadata)}개 파일, "
        f"{total_definitions}개 파싱, "
        f"{enriched_count}개 enriched, "
        f"{rel_count}개 관계 추론"
    )
    if skipped_count > 0:
        log_msg += f", {skipped_count}개 스킵"
    
    return {
        "ontology_context": ontology,
        "processing_progress": progress,
        "logs": [log_msg]
    }


def process_data_batch_node(state: AgentState) -> Dict[str, Any]:
    """
    [Phase 2-2] 데이터 일괄 처리 준비 노드
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
    
    first_file = data_files[0]
    
    progress["phase"] = "data_processing"
    progress["current_file"] = first_file
    progress["current_file_index"] = 0
    progress["total_files"] = len(data_files)
    
    print(f"\n   → 처리 파일: {os.path.basename(first_file)}")
    print("="*80)
    
    return {
        "file_path": first_file,
        "processing_progress": progress,
        "skip_indexing": False,
        "logs": [f"📊 [Data] {len(data_files)}개 파일 처리 시작"]
    }


def advance_to_next_file_node(state: AgentState) -> Dict[str, Any]:
    """
    [Helper] 다음 데이터 파일로 진행
    
    스킵된 파일도 추적하여 progress에 기록합니다.
    """
    print("\n" + "-"*40)
    print("➡️ [ADVANCE] 다음 파일로 이동")
    print("-"*40)
    
    classification_result = state.get("classification_result", {})
    data_files = classification_result.get("data_files", [])
    progress = state.get("processing_progress", {})
    
    current_idx = progress.get("current_file_index", 0)
    current_file = progress.get("current_file", "")
    
    # 스킵 여부 확인
    was_skipped = state.get("skip_indexing", False)
    skip_reason = state.get("skip_reason", "")
    
    if current_file:
        if was_skipped:
            # 스킵된 파일 기록
            if "skipped_data_files" not in progress:
                progress["skipped_data_files"] = []
            progress["skipped_data_files"].append({
                "file": current_file,
                "filename": os.path.basename(current_file),
                "reason": skip_reason
            })
            print(f"   ⏭️ 스킵됨: {os.path.basename(current_file)} ({skip_reason})")
        elif current_file not in progress.get("data_processed", []):
            # 정상 처리된 파일 기록
            if "data_processed" not in progress:
                progress["data_processed"] = []
            progress["data_processed"].append(current_file)
    
    next_idx = current_idx + 1
    
    if next_idx >= len(data_files):
        processed_count = len(progress.get("data_processed", []))
        skipped_count = len(progress.get("skipped_data_files", []))
        
        print(f"   ✅ 모든 데이터 파일 처리 완료")
        print(f"      - 처리됨: {processed_count}개")
        if skipped_count > 0:
            print(f"      - 스킵됨: {skipped_count}개")
            for skip in progress.get("skipped_data_files", []):
                print(f"        └─ {skip['filename']}: {skip['reason']}")
        
        progress["phase"] = "complete"
        progress["current_file"] = None
        progress["all_files_processed"] = True  # 명확한 종료 플래그
        
        log_msg = f"✅ [Complete] 데이터 파일 처리 완료 (처리: {processed_count}개"
        if skipped_count > 0:
            log_msg += f", 스킵: {skipped_count}개"
        log_msg += ")"
        
        return {
            "processing_progress": progress,
            "logs": [log_msg]
        }
    
    next_file = data_files[next_idx]
    progress["current_file"] = next_file
    progress["current_file_index"] = next_idx
    
    print(f"   📂 다음 파일: [{next_idx + 1}/{len(data_files)}] {os.path.basename(next_file)}")
    
    return {
        "file_path": next_file,
        "processing_progress": progress,
        "raw_metadata": {},
        "entity_identification": None,
        "finalized_schema": [],
        "needs_human_review": False,
        "human_feedback": None,
        "skip_indexing": False,
        "retry_count": 0,
        "logs": [f"➡️ [Advance] 다음 파일: {os.path.basename(next_file)}"]
    }

