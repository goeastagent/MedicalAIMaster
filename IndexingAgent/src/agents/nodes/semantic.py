# src/agents/nodes/semantic.py
"""
Phase 1: Semantic Analysis Node with Human Review

LLM을 사용하여 컬럼과 파일의 의미론적 정보를 분석합니다.
Confidence가 낮은 결과에 대해 Human Review를 요청하고,
피드백을 반영하여 재분석할 수 있습니다.

Human Review 방식:
- CLI 모드: 터미널에서 직접 input()으로 피드백 수집
- Web 모드: ReviewService를 통해 DB에 저장 후 polling (추후 구현)
"""

import json
import time
import sys
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from src.agents.state import AgentState
from src.database.connection import get_db_manager
from src.config import Phase1Config, LLMConfig
from src.agents.models.llm_responses import (
    ColumnSemanticMapping,
    FileSemanticMapping,
    Phase1HumanFeedback,
    BatchReviewState,
)


# =============================================================================
# 전역 리소스
# =============================================================================

_db_manager = None
_llm_client = None

def _get_db():
    """DB Manager 싱글톤 반환"""
    global _db_manager
    if _db_manager is None:
        _db_manager = get_db_manager()
    return _db_manager


def _get_llm():
    """LLM Client 싱글톤 반환"""
    global _llm_client
    if _llm_client is None:
        from src.utils.llm_client import get_llm_client
        _llm_client = get_llm_client()
    return _llm_client


# =============================================================================
# 프롬프트 템플릿
# =============================================================================

COLUMN_ANALYSIS_PROMPT = """You are a Medical Data Expert specializing in healthcare informatics.
You have extensive knowledge of:
- Clinical data standards (HL7, FHIR, OMOP CDM)
- Medical terminology (ICD-10, SNOMED-CT, LOINC)
- Physiological signals (ECG, EEG, SpO2, ABP, etc.)
- Laboratory values and reference ranges
- Electronic Health Records (EHR) structure

{feedback_context}
[Task]
Analyze the following column names from a medical dataset.
For each column, provide:

1. **semantic**: Standardized name in English (e.g., "Heart Rate", "Systolic Blood Pressure")
2. **unit**: Measurement unit if applicable (e.g., "bpm", "mmHg", "mg/dL")
3. **concept**: Category from this list:
   {concept_categories}
4. **description**: Brief clinical explanation (1-2 sentences)
5. **standard_code**: LOINC or SNOMED code if known (format: "LOINC:xxxx" or "SNOMED:xxxx"), null if unknown
6. **is_pii**: true if this could identify a patient (name, ID, address, etc.)
7. **confidence**: Your confidence in this interpretation (0.0-1.0)

[Input Columns]
{columns_list}

[Output Format]
Return ONLY valid JSON (no markdown, no explanation):
{{
  "mappings": [
    {{
      "original": "column_name_here",
      "semantic": "Standardized Name",
      "unit": "unit_or_null",
      "concept": "Category",
      "description": "Brief description",
      "standard_code": "LOINC:xxxx or null",
      "is_pii": false,
      "confidence": 0.95
    }}
  ]
}}
"""


FILE_ANALYSIS_PROMPT = """You are a Medical Data Expert analyzing healthcare dataset files.

{feedback_context}
[Task]
Analyze the following files from a medical dataset and determine their semantic meaning.

For each file, provide:
1. **semantic_type**: Format as "Domain:SubType", choose from:
   - Signal:Physiological, Signal:Neurological, Signal:Waveform
   - Clinical:Demographics, Clinical:Encounters, Clinical:Diagnoses
   - Lab:Chemistry, Lab:Hematology, Lab:Coagulation
   - Medication:Administration, Medication:Orders
   - Reference:Parameters, Reference:Codes, Reference:Lookup
   - Surgical:Procedures, Surgical:Anesthesia
   - Other:Unknown

2. **semantic_name**: Human-readable name for this file's content
3. **purpose**: What this file is used for (1-2 sentences)
4. **primary_entity**: What each row represents (e.g., "patient", "surgery", "lab_result")
5. **entity_identifier_column**: Column name that identifies each row (if identifiable)
6. **domain**: Medical domain from: {domain_categories}
7. **confidence**: Your confidence (0.0-1.0)

[Input Files]
{files_list}

[Output Format]
Return ONLY valid JSON (no markdown, no explanation):
{{
  "files": [
    {{
      "file_name": "filename.csv",
      "semantic_type": "Domain:SubType",
      "semantic_name": "Human Readable Name",
      "purpose": "Description of purpose",
      "primary_entity": "entity_type",
      "entity_identifier_column": "column_name_or_null",
      "domain": "Medical Domain",
      "data_quality_notes": null,
      "confidence": 0.9
    }}
  ]
}}
"""


# =============================================================================
# CLI Human Feedback 수집
# =============================================================================

def _print_separator(title: str = "", char: str = "=", width: int = 70):
    """구분선 출력"""
    if title:
        padding = (width - len(title) - 2) // 2
        print(f"\n{char * padding} {title} {char * padding}")
    else:
        print(char * width)


def _print_mappings(mappings: List[Dict], title: str = "Mappings", max_items: int = 15):
    """매핑 결과 출력"""
    print(f"\n📊 {title} ({len(mappings)} items):")
    for i, m in enumerate(mappings[:max_items], 1):
        if 'original' in m:
            conf = m.get('confidence', 0)
            print(f"   {i:2}. {m.get('original', '?'):30} → {m.get('semantic', '?'):25} "
                  f"[{m.get('concept', '?'):15}] conf={conf:.2f}")
        elif 'file_name' in m:
            conf = m.get('confidence', 0)
            print(f"   {i:2}. {m.get('file_name', '?'):30} → {m.get('semantic_type', '?'):20} "
                  f"[{m.get('domain', '?'):15}] conf={conf:.2f}")
    if len(mappings) > max_items:
        print(f"   ... and {len(mappings) - max_items} more")


def get_human_feedback_cli(
    batch_type: str,
    batch_index: int,
    retry_count: int,
    avg_confidence: float,
    low_conf_items: List[str],
    current_mappings: List[Dict]
) -> Phase1HumanFeedback:
    """
    CLI에서 Human 피드백 수집
    
    Returns:
        Phase1HumanFeedback 객체
    """
    _print_separator(f"🔍 HUMAN REVIEW - Batch {batch_index + 1}", "!", 70)
    
    print(f"\n📋 Review Information:")
    print(f"   Type: {batch_type}")
    print(f"   Batch: {batch_index + 1}")
    print(f"   Retry: {retry_count}/{Phase1Config.MAX_REVIEW_RETRIES}")
    print(f"   Avg Confidence: {avg_confidence:.2f} (threshold: {Phase1Config.CONFIDENCE_THRESHOLD})")
    print(f"   Low Conf Count: {len(low_conf_items)}")
    
    # Low confidence 항목 출력
    if low_conf_items:
        print(f"\n⚠️ Low Confidence Items:")
        for item in low_conf_items[:10]:
            print(f"      - {item}")
        if len(low_conf_items) > 10:
            print(f"      ... and {len(low_conf_items) - 10} more")
    
    # 현재 매핑 결과 출력
    if current_mappings:
        _print_mappings(current_mappings, "Current LLM Analysis")
    
    # 옵션 출력
    print("\n" + "-" * 60)
    print("📝 Available Actions:")
    print("   [1] accept  - Accept current results as-is")
    print("   [2] correct - Provide corrections and re-analyze")
    print("   [3] skip    - Skip this batch (don't save to DB)")
    print("-" * 60)
    
    # 사용자 입력
    while True:
        try:
            choice = input("\n🎯 Select action (1/2/3) or 'q' to quit: ").strip().lower()
        except EOFError:
            # Non-interactive 환경에서는 자동 accept
            print("\n⚠️ Non-interactive mode, auto accepting...")
            return Phase1HumanFeedback(action="accept")
        
        if choice == 'q':
            print("\n⛔ User requested quit")
            sys.exit(0)
        
        if choice == '1' or choice == 'accept':
            return Phase1HumanFeedback(action="accept")
        
        elif choice == '2' or choice == 'correct':
            print("\n✏️ Enter corrections (JSON format):")
            print('   Example: {"additional_context": "VitalDB anesthesia data", "domain_hints": ["Anesthesia"]}')
            
            try:
                correction_input = input("\n📝 Corrections (JSON, or press Enter for default): ").strip()
                if not correction_input:
                    return Phase1HumanFeedback(
                        action="correct",
                        additional_context="Please improve the analysis with better accuracy",
                        domain_hints=["Medical", "Healthcare"]
                    )
                
                corrections = json.loads(correction_input)
                return Phase1HumanFeedback(
                    action="correct",
                    additional_context=corrections.get("additional_context"),
                    domain_hints=corrections.get("domain_hints", []),
                    column_corrections=corrections.get("column_corrections", []),
                    file_corrections=corrections.get("file_corrections", [])
                )
                
            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON: {e}, using as context...")
                return Phase1HumanFeedback(
                    action="correct",
                    additional_context=correction_input,
                    domain_hints=[]
                )
            except EOFError:
                return Phase1HumanFeedback(action="accept")
        
        elif choice == '3' or choice == 'skip':
            return Phase1HumanFeedback(action="skip")
        
        else:
            print("❌ Invalid choice. Please enter 1, 2, 3, or 'q'")


# =============================================================================
# 피드백 컨텍스트 빌더
# =============================================================================

def build_feedback_context_for_columns(feedback_history: List[Phase1HumanFeedback]) -> str:
    """Human 피드백을 LLM 프롬프트 컨텍스트로 변환"""
    if not feedback_history:
        return ""
    
    context_parts = ["[Previous Analysis Feedback from Human Expert]"]
    context_parts.append("Please carefully consider this feedback to improve your analysis:\n")
    
    for fb in feedback_history:
        if fb.additional_context:
            context_parts.append(f"📌 Context: {fb.additional_context}")
        
        if fb.domain_hints:
            context_parts.append(f"📌 Domain: {', '.join(fb.domain_hints)}")
        
        for corr in fb.column_corrections:
            if corr.correct_semantic:
                context_parts.append(
                    f"✏️ Correction: '{corr.original_name}' should be '{corr.correct_semantic}'"
                )
            if corr.correct_unit:
                context_parts.append(f"   - Unit: {corr.correct_unit}")
            if corr.correct_concept:
                context_parts.append(f"   - Category: {corr.correct_concept}")
            if corr.hint:
                context_parts.append(f"   - Hint: {corr.hint}")
    
    context_parts.append("")
    return "\n".join(context_parts)


def build_feedback_context_for_files(feedback_history: List[Phase1HumanFeedback]) -> str:
    """파일 분석용 Human 피드백 컨텍스트 빌더"""
    if not feedback_history:
        return ""
    
    context_parts = ["[Previous Analysis Feedback from Human Expert]"]
    context_parts.append("Please carefully consider this feedback to improve your analysis:\n")
    
    for fb in feedback_history:
        if fb.additional_context:
            context_parts.append(f"📌 Context: {fb.additional_context}")
        
        if fb.domain_hints:
            context_parts.append(f"📌 Domain: {', '.join(fb.domain_hints)}")
        
        for corr in fb.file_corrections:
            if corr.correct_semantic_type:
                context_parts.append(
                    f"✏️ Correction: '{corr.file_name}' semantic_type should be '{corr.correct_semantic_type}'"
                )
            if corr.correct_semantic_name:
                context_parts.append(f"   - Name: {corr.correct_semantic_name}")
            if corr.correct_primary_entity:
                context_parts.append(f"   - Primary Entity: {corr.correct_primary_entity}")
            if corr.hint:
                context_parts.append(f"   - Hint: {corr.hint}")
    
    context_parts.append("")
    return "\n".join(context_parts)


# =============================================================================
# 프롬프트 빌더
# =============================================================================

def build_column_prompt(
    columns: List[Dict[str, Any]],
    feedback_history: List[Phase1HumanFeedback] = None
) -> str:
    """컬럼 배치를 LLM 프롬프트로 변환"""
    
    feedback_context = ""
    if feedback_history:
        feedback_context = build_feedback_context_for_columns(feedback_history)
    
    lines = []
    for i, col in enumerate(columns, 1):
        name = col.get('original_name', '?')
        col_type = col.get('column_type', 'unknown')
        
        stats = []
        if col.get('avg_min') is not None:
            stats.append(f"range: [{col.get('avg_min'):.1f}, {col.get('avg_max'):.1f}]")
        if col.get('avg_mean') is not None:
            stats.append(f"mean: {col.get('avg_mean'):.1f}")
        if col.get('avg_unique_ratio') is not None:
            stats.append(f"unique_ratio: {col.get('avg_unique_ratio'):.2f}")
        if col.get('sample_values'):
            values = list(col['sample_values'].keys())[:5]
            stats.append(f"sample_values: {values}")
        if col.get('sample_unit'):
            stats.append(f"unit_hint: {col.get('sample_unit')}")
        
        freq = col.get('frequency', 0)
        stats_str = f" ({', '.join(stats)})" if stats else ""
        
        lines.append(f"{i}. \"{name}\" [{col_type}, freq={freq}]{stats_str}")
    
    columns_list = "\n".join(lines)
    concept_categories = ", ".join(Phase1Config.CONCEPT_CATEGORIES)
    
    return COLUMN_ANALYSIS_PROMPT.format(
        feedback_context=feedback_context,
        concept_categories=concept_categories,
        columns_list=columns_list
    )


def build_file_prompt(
    files: List[Dict[str, Any]],
    feedback_history: List[Phase1HumanFeedback] = None
) -> str:
    """파일 배치를 LLM 프롬프트로 변환"""
    
    feedback_context = ""
    if feedback_history:
        feedback_context = build_feedback_context_for_files(feedback_history)
    
    lines = []
    for i, f in enumerate(files, 1):
        name = f.get('file_name', '?')
        ptype = f.get('processor_type', '?')
        cols = f.get('column_count', 0)
        col_names = f.get('column_names', [])[:15]
        
        info = []
        if f.get('row_count'):
            info.append(f"rows: {f.get('row_count'):,}")
        if f.get('duration_seconds'):
            info.append(f"duration: {f.get('duration_seconds'):.1f}s")
        
        info_str = f" ({', '.join(info)})" if info else ""
        col_preview = ", ".join(col_names[:10])
        if len(col_names) > 10:
            col_preview += f"... (+{len(col_names)-10} more)"
        
        lines.append(
            f"{i}. \"{name}\" [{ptype}, {cols} columns]{info_str}\n"
            f"   Columns: [{col_preview}]"
        )
    
    files_list = "\n".join(lines)
    domain_categories = ", ".join(Phase1Config.DOMAIN_CATEGORIES)
    
    return FILE_ANALYSIS_PROMPT.format(
        feedback_context=feedback_context,
        domain_categories=domain_categories,
        files_list=files_list
    )


# =============================================================================
# LLM 호출
# =============================================================================

def call_llm_for_columns(
    batch: List[Dict[str, Any]],
    feedback_history: List[Phase1HumanFeedback] = None
) -> List[ColumnSemanticMapping]:
    """컬럼 배치에 대해 LLM 호출"""
    llm = _get_llm()
    prompt = build_column_prompt(batch, feedback_history)
    
    try:
        data = llm.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS_COLUMN_ANALYSIS)
        
        if data.get("error"):
            print(f"   ❌ LLM returned error: {data.get('error')}")
            return []
        
        mappings = []
        for item in data.get('mappings', []):
            try:
                mapping = ColumnSemanticMapping(**item)
                mappings.append(mapping)
            except Exception as e:
                print(f"   ⚠️ Failed to parse mapping for {item.get('original', '?')}: {e}")
        
        return mappings
        
    except Exception as e:
        print(f"   ❌ LLM call error: {e}")
        return []


def call_llm_for_files(
    batch: List[Dict[str, Any]],
    feedback_history: List[Phase1HumanFeedback] = None
) -> List[FileSemanticMapping]:
    """파일 배치에 대해 LLM 호출"""
    llm = _get_llm()
    prompt = build_file_prompt(batch, feedback_history)
    
    try:
        data = llm.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
        
        if data.get("error"):
            print(f"   ❌ LLM returned error: {data.get('error')}")
            return []
        
        mappings = []
        for item in data.get('files', []):
            try:
                mapping = FileSemanticMapping(**item)
                mappings.append(mapping)
            except Exception as e:
                print(f"   ⚠️ Failed to parse file mapping for {item.get('file_name', '?')}: {e}")
        
        return mappings
        
    except Exception as e:
        print(f"   ❌ LLM call error: {e}")
        return []


# =============================================================================
# Confidence 계산
# =============================================================================

def compute_column_batch_stats(
    mappings: List[ColumnSemanticMapping],
    threshold: float = Phase1Config.CONFIDENCE_THRESHOLD
) -> Tuple[float, float, float, List[str]]:
    """컬럼 배치의 confidence 통계 계산"""
    if not mappings:
        return 0.0, 0.0, 0.0, []
    
    confidences = [m.confidence for m in mappings]
    avg_conf = sum(confidences) / len(confidences)
    min_conf = min(confidences)
    max_conf = max(confidences)
    
    low_conf_items = [
        m.original for m in mappings 
        if m.confidence < threshold
    ]
    
    return avg_conf, min_conf, max_conf, low_conf_items


def compute_file_batch_stats(
    mappings: List[FileSemanticMapping],
    threshold: float = Phase1Config.CONFIDENCE_THRESHOLD
) -> Tuple[float, float, float, List[str]]:
    """파일 배치의 confidence 통계 계산"""
    if not mappings:
        return 0.0, 0.0, 0.0, []
    
    confidences = [m.confidence for m in mappings]
    avg_conf = sum(confidences) / len(confidences)
    min_conf = min(confidences)
    max_conf = max(confidences)
    
    low_conf_items = [
        m.file_name for m in mappings 
        if m.confidence < threshold
    ]
    
    return avg_conf, min_conf, max_conf, low_conf_items


# =============================================================================
# DB 업데이트 (Broadcast)
# =============================================================================

def broadcast_column_mappings(mappings: List[ColumnSemanticMapping]) -> int:
    """컬럼 매핑 결과를 DB에 일괄 업데이트"""
    db = _get_db()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    total_updated = 0
    now = datetime.now()
    
    try:
        for mapping in mappings:
            cursor.execute("""
                UPDATE column_metadata
                SET 
                    semantic_name = %s,
                    unit = %s,
                    concept_category = %s,
                    description = %s,
                    standard_code = %s,
                    is_pii = %s,
                    llm_confidence = %s,
                    llm_analyzed_at = %s
                WHERE original_name = %s
            """, (
                mapping.semantic,
                mapping.unit,
                mapping.concept,
                mapping.description,
                mapping.standard_code,
                mapping.is_pii,
                mapping.confidence,
                now,
                mapping.original
            ))
            total_updated += cursor.rowcount
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"   ❌ DB update error: {e}")
        raise
    
    return total_updated


def broadcast_file_mappings(mappings: List[FileSemanticMapping]) -> int:
    """파일 매핑 결과를 DB에 업데이트"""
    db = _get_db()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    total_updated = 0
    now = datetime.now()
    
    try:
        for mapping in mappings:
            cursor.execute("""
                UPDATE file_catalog
                SET 
                    semantic_type = %s,
                    semantic_name = %s,
                    file_purpose = %s,
                    primary_entity = %s,
                    entity_identifier_column = %s,
                    domain = %s,
                    llm_confidence = %s,
                    llm_analyzed_at = %s
                WHERE file_name = %s
            """, (
                mapping.semantic_type,
                mapping.semantic_name,
                mapping.purpose,
                mapping.primary_entity,
                mapping.entity_identifier_column,
                mapping.domain,
                mapping.confidence,
                now,
                mapping.file_name
            ))
            total_updated += cursor.rowcount
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"   ❌ DB update error: {e}")
        raise
    
    return total_updated


# =============================================================================
# 배치 처리 (with Human Review Loop)
# =============================================================================

def process_column_batch_with_review(
    batch: List[Dict[str, Any]],
    batch_index: int,
    total_batches: int
) -> Tuple[List[ColumnSemanticMapping], BatchReviewState]:
    """
    단일 컬럼 배치 처리 + Human Review Loop
    
    confidence가 만족되거나 retry가 초과될 때까지 반복
    """
    feedback_history: List[Phase1HumanFeedback] = []
    retry_count = 0
    final_mappings = []
    
    while retry_count <= Phase1Config.MAX_REVIEW_RETRIES:
        # 1. LLM 분석
        print(f"\n   🔄 Analyzing batch {batch_index + 1}/{total_batches} "
              f"(retry {retry_count}/{Phase1Config.MAX_REVIEW_RETRIES})...")
        
        mappings = call_llm_for_columns(batch, feedback_history if feedback_history else None)
        
        if not mappings:
            print(f"   ❌ No mappings returned, skipping batch")
            return [], BatchReviewState(
                batch_type="column",
                batch_index=batch_index,
                batch_size=len(batch),
                status="skipped"
            )
        
        # 2. Confidence 통계 계산
        avg_conf, min_conf, max_conf, low_conf_items = compute_column_batch_stats(mappings)
        
        print(f"      Avg confidence: {avg_conf:.2f}")
        print(f"      Low conf items: {len(low_conf_items)}/{len(batch)}")
        
        # 3. Confidence 체크
        low_conf_ratio = len(low_conf_items) / len(batch) if batch else 0
        needs_review = (
            avg_conf < Phase1Config.CONFIDENCE_THRESHOLD or
            low_conf_ratio >= Phase1Config.MIN_LOW_CONF_RATIO
        )
        
        if not needs_review:
            # ✅ Confidence 충분 - DB 저장
            print(f"      ✅ Confidence OK! Saving to DB...")
            updated = broadcast_column_mappings(mappings)
            print(f"      ✅ {updated} rows updated")
            
            return mappings, BatchReviewState(
                batch_type="column",
                batch_index=batch_index,
                batch_size=len(batch),
                avg_confidence=avg_conf,
                min_confidence=min_conf,
                max_confidence=max_conf,
                low_conf_count=len(low_conf_items),
                low_conf_items=low_conf_items,
                retry_count=retry_count,
                status="accepted"
            )
        
        # 4. Human Review 필요
        if retry_count >= Phase1Config.MAX_REVIEW_RETRIES:
            # Max retries 도달 - 강제 저장
            print(f"      ⚠️ Max retries reached. Force accepting...")
            updated = broadcast_column_mappings(mappings)
            print(f"      ⚠️ {updated} rows updated (force accepted)")
            
            return mappings, BatchReviewState(
                batch_type="column",
                batch_index=batch_index,
                batch_size=len(batch),
                avg_confidence=avg_conf,
                min_confidence=min_conf,
                max_confidence=max_conf,
                low_conf_count=len(low_conf_items),
                low_conf_items=low_conf_items,
                retry_count=retry_count,
                status="max_retries"
            )
        
        # 5. Human 피드백 수집
        feedback = get_human_feedback_cli(
            batch_type="column",
            batch_index=batch_index,
            retry_count=retry_count,
            avg_confidence=avg_conf,
            low_conf_items=low_conf_items,
            current_mappings=[m.model_dump() for m in mappings]
        )
        
        if feedback.action == "accept":
            # Accept - DB 저장
            print(f"\n      ✅ Human accepted. Saving to DB...")
            updated = broadcast_column_mappings(mappings)
            print(f"      ✅ {updated} rows updated")
            
            return mappings, BatchReviewState(
                batch_type="column",
                batch_index=batch_index,
                batch_size=len(batch),
                avg_confidence=avg_conf,
                min_confidence=min_conf,
                max_confidence=max_conf,
                low_conf_count=len(low_conf_items),
                low_conf_items=low_conf_items,
                retry_count=retry_count,
                status="accepted"
            )
        
        elif feedback.action == "skip":
            # Skip - DB 저장 안 함
            print(f"\n      ⏭️ Batch skipped by human")
            
            return [], BatchReviewState(
                batch_type="column",
                batch_index=batch_index,
                batch_size=len(batch),
                avg_confidence=avg_conf,
                retry_count=retry_count,
                status="skipped"
            )
        
        elif feedback.action == "correct":
            # Correct - 피드백 반영 후 재분석
            print(f"\n      🔄 Re-analyzing with feedback...")
            feedback_history.append(feedback)
            retry_count += 1
            time.sleep(Phase1Config.RETRY_DELAY_SECONDS)
            continue
    
    # Should not reach here
    return final_mappings, BatchReviewState(
        batch_type="column",
        batch_index=batch_index,
        batch_size=len(batch),
        status="error"
    )


def process_file_batch_with_review(
    batch: List[Dict[str, Any]],
    batch_index: int,
    total_batches: int
) -> Tuple[List[FileSemanticMapping], BatchReviewState]:
    """단일 파일 배치 처리 + Human Review Loop"""
    feedback_history: List[Phase1HumanFeedback] = []
    retry_count = 0
    
    while retry_count <= Phase1Config.MAX_REVIEW_RETRIES:
        print(f"\n   🔄 Analyzing file batch {batch_index + 1}/{total_batches} "
              f"(retry {retry_count}/{Phase1Config.MAX_REVIEW_RETRIES})...")
        
        mappings = call_llm_for_files(batch, feedback_history if feedback_history else None)
        
        if not mappings:
            print(f"   ❌ No mappings returned, skipping batch")
            return [], BatchReviewState(
                batch_type="file",
                batch_index=batch_index,
                batch_size=len(batch),
                status="skipped"
            )
        
        avg_conf, min_conf, max_conf, low_conf_items = compute_file_batch_stats(mappings)
        
        print(f"      Avg confidence: {avg_conf:.2f}")
        print(f"      Low conf items: {len(low_conf_items)}/{len(batch)}")
        
        low_conf_ratio = len(low_conf_items) / len(batch) if batch else 0
        needs_review = (
            avg_conf < Phase1Config.CONFIDENCE_THRESHOLD or
            low_conf_ratio >= Phase1Config.MIN_LOW_CONF_RATIO
        )
        
        if not needs_review:
            print(f"      ✅ Confidence OK! Saving to DB...")
            updated = broadcast_file_mappings(mappings)
            print(f"      ✅ {updated} files updated")
            
            return mappings, BatchReviewState(
                batch_type="file",
                batch_index=batch_index,
                batch_size=len(batch),
                avg_confidence=avg_conf,
                min_confidence=min_conf,
                max_confidence=max_conf,
                low_conf_count=len(low_conf_items),
                low_conf_items=low_conf_items,
                retry_count=retry_count,
                status="accepted"
            )
        
        if retry_count >= Phase1Config.MAX_REVIEW_RETRIES:
            print(f"      ⚠️ Max retries reached. Force accepting...")
            updated = broadcast_file_mappings(mappings)
            print(f"      ⚠️ {updated} files updated (force accepted)")
            
            return mappings, BatchReviewState(
                batch_type="file",
                batch_index=batch_index,
                batch_size=len(batch),
                avg_confidence=avg_conf,
                min_confidence=min_conf,
                max_confidence=max_conf,
                low_conf_count=len(low_conf_items),
                low_conf_items=low_conf_items,
                retry_count=retry_count,
                status="max_retries"
            )
        
        feedback = get_human_feedback_cli(
            batch_type="file",
            batch_index=batch_index,
            retry_count=retry_count,
            avg_confidence=avg_conf,
            low_conf_items=low_conf_items,
            current_mappings=[m.model_dump() for m in mappings]
        )
        
        if feedback.action == "accept":
            print(f"\n      ✅ Human accepted. Saving to DB...")
            updated = broadcast_file_mappings(mappings)
            print(f"      ✅ {updated} files updated")
            
            return mappings, BatchReviewState(
                batch_type="file",
                batch_index=batch_index,
                batch_size=len(batch),
                avg_confidence=avg_conf,
                min_confidence=min_conf,
                max_confidence=max_conf,
                low_conf_count=len(low_conf_items),
                low_conf_items=low_conf_items,
                retry_count=retry_count,
                status="accepted"
            )
        
        elif feedback.action == "skip":
            print(f"\n      ⏭️ Batch skipped by human")
            
            return [], BatchReviewState(
                batch_type="file",
                batch_index=batch_index,
                batch_size=len(batch),
                avg_confidence=avg_conf,
                retry_count=retry_count,
                status="skipped"
            )
        
        elif feedback.action == "correct":
            print(f"\n      🔄 Re-analyzing with feedback...")
            feedback_history.append(feedback)
            retry_count += 1
            time.sleep(Phase1Config.RETRY_DELAY_SECONDS)
            continue
    
    return [], BatchReviewState(
        batch_type="file",
        batch_index=batch_index,
        batch_size=len(batch),
        status="error"
    )


# =============================================================================
# LangGraph Node Function
# =============================================================================

def phase1_semantic_node(state: AgentState) -> Dict[str, Any]:
    """
    Phase 1: Semantic Analysis 노드 (with Human Review Loop)
    
    interrupt() 없이 for loop으로 Human Review 수행
    """
    print("\n" + "=" * 60)
    print("🧠 Phase 1: Semantic Analysis (with Human Review)")
    print("=" * 60)
    print(f"   Confidence Threshold: {Phase1Config.CONFIDENCE_THRESHOLD}")
    print(f"   Max Review Retries: {Phase1Config.MAX_REVIEW_RETRIES}")
    
    started_at = datetime.now()
    
    # State에서 배치 가져오기
    column_batches = state.get("column_batches", [])
    file_batches = state.get("file_batches", [])
    
    # 결과 저장용
    all_column_mappings = []
    all_file_mappings = []
    all_batch_states = []
    
    total_llm_calls = 0
    total_review_requests = 0
    total_reanalyzes = 0
    batches_force_accepted = 0
    
    # =========================================================================
    # 1. 컬럼 분석
    # =========================================================================
    print(f"\n📊 Column Semantic Analysis")
    print(f"   Batches: {len(column_batches)}")
    print(f"   Total columns: {sum(len(b) for b in column_batches)}")
    
    for i, batch in enumerate(column_batches):
        mappings, review_state = process_column_batch_with_review(
            batch, i, len(column_batches)
        )
        
        all_column_mappings.extend([m.model_dump() for m in mappings])
        all_batch_states.append(review_state.model_dump())
        
        total_llm_calls += review_state.retry_count + 1
        if review_state.retry_count > 0:
            total_review_requests += 1
            total_reanalyzes += review_state.retry_count
        if review_state.status == "max_retries":
            batches_force_accepted += 1
        
        # Rate limit 방지
        if i < len(column_batches) - 1:
            time.sleep(Phase1Config.RETRY_DELAY_SECONDS)
    
    # =========================================================================
    # 2. 파일 분석
    # =========================================================================
    print(f"\n📁 File Semantic Analysis")
    print(f"   Batches: {len(file_batches)}")
    print(f"   Total files: {sum(len(b) for b in file_batches)}")
    
    for i, batch in enumerate(file_batches):
        mappings, review_state = process_file_batch_with_review(
            batch, i, len(file_batches)
        )
        
        all_file_mappings.extend([m.model_dump() for m in mappings])
        all_batch_states.append(review_state.model_dump())
        
        total_llm_calls += review_state.retry_count + 1
        if review_state.retry_count > 0:
            total_review_requests += 1
            total_reanalyzes += review_state.retry_count
        if review_state.status == "max_retries":
            batches_force_accepted += 1
        
        if i < len(file_batches) - 1:
            time.sleep(Phase1Config.RETRY_DELAY_SECONDS)
    
    # =========================================================================
    # 3. 결과 요약
    # =========================================================================
    completed_at = datetime.now()
    duration = (completed_at - started_at).total_seconds()
    
    column_high_conf = sum(1 for m in all_column_mappings if m.get('confidence', 0) >= Phase1Config.CONFIDENCE_THRESHOLD)
    column_low_conf = len(all_column_mappings) - column_high_conf
    file_high_conf = sum(1 for m in all_file_mappings if m.get('confidence', 0) >= Phase1Config.CONFIDENCE_THRESHOLD)
    file_low_conf = len(all_file_mappings) - file_high_conf
    
    result = {
        "total_columns_analyzed": len(all_column_mappings),
        "columns_with_semantic": len(all_column_mappings),
        "columns_high_conf": column_high_conf,
        "columns_low_conf": column_low_conf,
        "column_batches_processed": len(column_batches),
        "total_files_analyzed": len(all_file_mappings),
        "files_with_semantic": len(all_file_mappings),
        "files_high_conf": file_high_conf,
        "files_low_conf": file_low_conf,
        "file_batches_processed": len(file_batches),
        "total_review_requests": total_review_requests,
        "total_reanalyzes": total_reanalyzes,
        "batches_force_accepted": batches_force_accepted,
        "total_llm_calls": total_llm_calls,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": duration
    }
    
    print(f"\n✅ Phase 1 Complete!")
    print(f"   Columns analyzed: {len(all_column_mappings)} (high: {column_high_conf}, low: {column_low_conf})")
    print(f"   Files analyzed: {len(all_file_mappings)} (high: {file_high_conf}, low: {file_low_conf})")
    print(f"   Total LLM calls: {total_llm_calls}")
    print(f"   Review requests: {total_review_requests}")
    print(f"   Re-analyzes: {total_reanalyzes}")
    print(f"   Force accepted: {batches_force_accepted}")
    print(f"   Duration: {duration:.1f}s")
    print("=" * 60 + "\n")
    
    return {
        "phase1_result": result,
        "column_semantic_mappings": all_column_mappings,
        "file_semantic_mappings": all_file_mappings,
        "phase1_all_batch_states": all_batch_states
    }


# =============================================================================
# 편의 함수
# =============================================================================

def run_semantic_analysis_standalone(
    column_batches: List[List[Dict[str, Any]]] = None,
    file_batches: List[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Phase 1 독립 실행 (테스트용)"""
    from src.agents.nodes.aggregator import aggregate_unique_columns, aggregate_unique_files
    from src.agents.nodes.aggregator import prepare_llm_batches, prepare_file_batches
    
    print("\n" + "=" * 60)
    print("🧠 Running Semantic Analysis (standalone)...")
    print("=" * 60)
    
    if column_batches is None:
        columns = aggregate_unique_columns()
        column_batches = prepare_llm_batches(columns, Phase1Config.COLUMN_BATCH_SIZE)
    
    if file_batches is None:
        files = aggregate_unique_files()
        file_batches = prepare_file_batches(files, Phase1Config.FILE_BATCH_SIZE)
    
    # State 시뮬레이션
    state = {
        "column_batches": column_batches,
        "file_batches": file_batches
    }
    
    return phase1_semantic_node(state)
