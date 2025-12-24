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
    build_metadata_detection_context, 
    parse_metadata_content
)
from src.config import HumanReviewConfig


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
    
    # Signal file extensions that are always data (not metadata)
    SIGNAL_EXTENSIONS = {'.vital', '.edf', '.bdf'}
    
    for idx, file_path in enumerate(input_files):
        filename = os.path.basename(file_path)
        file_ext = os.path.splitext(filename)[1].lower()
        print(f"\n   [{idx+1}/{len(input_files)}] {filename}")
        
        try:
            # Rule-based: Signal files are always data
            if file_ext in SIGNAL_EXTENSIONS:
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
            context = build_metadata_detection_context(file_path, raw_metadata)
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
    """
    print("\n" + "="*80)
    print("🧑 [CLASSIFICATION REVIEW] Human-in-the-Loop")
    print("="*80)
    
    classification_result = state.get("classification_result", {})
    uncertain_files = classification_result.get("uncertain_files", [])
    classifications = classification_result.get("classifications", {})
    human_feedback = state.get("human_feedback")
    
    if human_feedback:
        print(f"   💬 사용자 피드백 수신: '{human_feedback}'")
        
        updated_classifications = _parse_classification_feedback(
            feedback=human_feedback,
            classifications=classifications,
            uncertain_files=uncertain_files
        )
        
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
        
        if remaining_uncertain:
            question = _generate_classification_question(remaining_uncertain, updated_classifications)
            return {
                "classification_result": updated_result,
                "needs_human_review": True,
                "review_type": "classification",
                "human_question": question,
                "human_feedback": None,
                "logs": [f"🔄 [Review] 추가 확인 필요: {len(remaining_uncertain)}개 파일"]
            }
        
        progress = state.get("processing_progress", {})
        progress["phase"] = "classification_review"
        
        return {
            "classification_result": updated_result,
            "processing_progress": progress,
            "needs_human_review": False,
            "human_feedback": None,
            "logs": [f"✅ [Review] 분류 확정 완료"]
        }
    
    if not uncertain_files:
        print("   ✅ 불확실한 파일 없음 - 리뷰 스킵")
        return {
            "needs_human_review": False,
            "logs": ["✅ [Review] 모든 파일 분류 확정"]
        }
    
    question = _generate_classification_question(uncertain_files, classifications)
    
    print(f"   ❓ {len(uncertain_files)}개 파일에 대해 사용자 확인 요청")
    print("="*80)
    
    return {
        "needs_human_review": True,
        "review_type": "classification",
        "human_question": question,
        "logs": [f"❓ [Review] {len(uncertain_files)}개 파일 분류 확인 요청"]
    }


def _generate_classification_question(
    uncertain_files: List[str], 
    classifications: Dict[str, FileClassification]
) -> str:
    """불확실한 파일들에 대한 질문 생성"""
    
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
        "- 모두 맞으면: `확인` 또는 `ok`\n"
        "- 수정 필요: `1:데이터, 2:메타데이터` 형식\n"
        "- 파일 제외: `1:skip`\n"
    )
    
    return "".join(question_parts)


def _parse_classification_feedback(
    feedback: str, 
    classifications: Dict[str, FileClassification],
    uncertain_files: List[str]
) -> Dict[str, FileClassification]:
    """사용자 피드백을 파싱하여 분류 결과 업데이트"""
    import re
    
    updated = classifications.copy()
    feedback_lower = feedback.lower().strip()
    
    if feedback_lower in ["확인", "ok", "yes", "y", "approve", "승인"]:
        for file_path in uncertain_files:
            if file_path in updated:
                updated[file_path]["human_confirmed"] = True
                updated[file_path]["needs_review"] = False
        return updated
    
    corrections = re.findall(r'(\d+)\s*[:：]\s*(메타데이터|데이터|metadata|data|제외|skip)', feedback_lower)
    
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
    [Phase 2-1] 메타데이터 일괄 처리 노드
    """
    print("\n" + "="*80)
    print("📖 [METADATA PROCESSOR] Phase 2-1 - 메타데이터 일괄 처리")
    print("="*80)
    
    classification_result = state.get("classification_result", {})
    metadata_files = classification_result.get("metadata_files", [])
    progress = state.get("processing_progress", {})
    
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
            ontology["file_tags"][file_path] = {
                "type": "metadata",
                "role": "dictionary",
                "confidence": classification_result["classifications"].get(file_path, {}).get("confidence", 0.8),
                "detected_at": datetime.now().isoformat()
            }
            
            new_definitions = parse_metadata_content(file_path)
            ontology["definitions"].update(new_definitions)
            
            total_definitions += len(new_definitions)
            processed_metadata.append(file_path)
            
            print(f"      ✅ 용어 {len(new_definitions)}개 추가")
            
        except Exception as e:
            print(f"      ❌ 처리 실패: {e}")
    
    ontology_manager.save(ontology)
    
    progress["phase"] = "metadata_processing"
    progress["metadata_processed"] = processed_metadata
    
    print(f"\n" + "-"*40)
    print(f"📊 메타데이터 처리 완료:")
    print(f"   - 처리된 파일: {len(processed_metadata)}개")
    print(f"   - 추가된 용어: {total_definitions}개")
    print("="*80)
    
    return {
        "ontology_context": ontology,
        "processing_progress": progress,
        "logs": [f"📖 [Metadata] {len(processed_metadata)}개 파일 처리, {total_definitions}개 용어 추가"]
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
    """
    print("\n" + "-"*40)
    print("➡️ [ADVANCE] 다음 파일로 이동")
    print("-"*40)
    
    classification_result = state.get("classification_result", {})
    data_files = classification_result.get("data_files", [])
    progress = state.get("processing_progress", {})
    
    current_idx = progress.get("current_file_index", 0)
    current_file = progress.get("current_file", "")
    
    if current_file and current_file not in progress.get("data_processed", []):
        if "data_processed" not in progress:
            progress["data_processed"] = []
        progress["data_processed"].append(current_file)
    
    next_idx = current_idx + 1
    
    if next_idx >= len(data_files):
        print(f"   ✅ 모든 데이터 파일 처리 완료 ({len(data_files)}개)")
        progress["phase"] = "complete"
        progress["current_file"] = None
        progress["all_files_processed"] = True  # 명확한 종료 플래그
        
        return {
            "processing_progress": progress,
            "logs": [f"✅ [Complete] 모든 데이터 파일 처리 완료 ({len(data_files)}개)"]
        }
    
    next_file = data_files[next_idx]
    progress["current_file"] = next_file
    progress["current_file_index"] = next_idx
    
    print(f"   📂 다음 파일: [{next_idx + 1}/{len(data_files)}] {os.path.basename(next_file)}")
    
    return {
        "file_path": next_file,
        "processing_progress": progress,
        "raw_metadata": {},
        "finalized_anchor": None,
        "finalized_schema": [],
        "needs_human_review": False,
        "human_feedback": None,
        "skip_indexing": False,
        "retry_count": 0,
        "logs": [f"➡️ [Advance] 다음 파일: {os.path.basename(next_file)}"]
    }

