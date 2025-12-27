# src/agents/helpers/metadata_helpers.py
"""
메타데이터 처리 관련 헬퍼 함수들
"""

import os
import json
import pandas as pd
from typing import Dict, Any, List, Optional

from src.utils.llm_client import get_llm_client
from src.utils.llm_cache import get_llm_cache
from src.config import HumanReviewConfig, MetadataEnrichmentConfig


# Lazy initialization
_llm_client = None
_llm_cache = None


def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        _llm_client = get_llm_client()
    return _llm_client


def _get_llm_cache():
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = get_llm_cache()
    return _llm_cache


def parse_metadata_content(file_path: str) -> dict:
    """
    [Rule] Parse metadata file using Processor
    
    Processor를 활용하여 메타데이터 파일을 파싱합니다.
    - Processor가 extract_metadata()로 컬럼 정보 추출
    - 추출된 column_details를 definitions 형태로 변환
    - Processor가 없거나 에러 발생 시 폴백으로 직접 파싱
    """
    from src.agents.nodes.common import processors
    
    definitions = {}
    filename = os.path.basename(file_path)
    
    try:
        # 1. 적합한 Processor 찾기
        processor = next((p for p in processors if p.can_handle(file_path)), None)
        
        if not processor:
            print(f"      ⚠️ Processor 없음: {filename} - 직접 파싱 시도")
            return _parse_metadata_fallback(file_path)
        
        # 2. Processor로 메타데이터 추출
        raw_metadata = processor.extract_metadata(file_path)
        
        if not raw_metadata:
            print(f"      ⚠️ Processor 메타데이터 없음 - 직접 파싱 시도")
            return _parse_metadata_fallback(file_path)
        
        # 3. 추출된 column_details를 definitions 형태로 변환
        column_details = raw_metadata.get('column_details', [])
        
        if column_details:
            for col_info in column_details:
                col_name = col_info.get('column_name', '')
                if not col_name:
                    continue
                    
                # 컬럼 정보로부터 definition 문자열 생성
                desc = _build_definition_from_column_info(col_info)
                definitions[col_name] = desc
        
        # 4. 메타데이터 파일 특성: 첫 번째 컬럼이 key, 두 번째 컬럼이 description인 경우 추가 처리
        # (예: definitions.csv, dictionary.csv 등)
        if len(column_details) >= 2:
            extra_definitions = _extract_key_value_definitions(file_path)
            if extra_definitions:
                definitions.update(extra_definitions)
        
        return definitions
        
    except Exception as e:
        print(f"      ❌ [Processor Parse Error] {filename}: {e}")
        # 폴백: 직접 파싱 시도
        return _parse_metadata_fallback(file_path)


def _build_definition_from_column_info(col_info: dict) -> str:
    """
    Processor의 column_info를 definition 문자열로 변환
    """
    parts = []
    
    col_type = col_info.get('column_type', 'unknown')
    dtype = col_info.get('dtype', 'unknown')
    
    parts.append(f"Type: {col_type}")
    parts.append(f"dtype: {dtype}")
    
    if col_type == 'categorical':
        unique_values = col_info.get('unique_values', [])
        n_unique = col_info.get('n_unique', len(unique_values))
        parts.append(f"unique: {n_unique}")
        if unique_values:
            # 처음 5개만 표시
            sample_vals = unique_values[:5] if isinstance(unique_values, list) else [str(unique_values)]
            parts.append(f"values: {sample_vals}")
    else:  # continuous
        min_val = col_info.get('min')
        max_val = col_info.get('max')
        if min_val is not None and max_val is not None:
            parts.append(f"range: [{min_val}, {max_val}]")
        samples = col_info.get('samples', [])
        if samples:
            parts.append(f"samples: {samples[:3]}")
    
    return " | ".join(parts)


def _extract_key_value_definitions(file_path: str) -> dict:
    """
    메타데이터 파일에서 key-value 형태의 definitions 추출
    (첫 번째 컬럼 = key, 두 번째 컬럼 = description)
    """
    definitions = {}
    
    try:
        df = pd.read_csv(file_path)
        
        if len(df.columns) >= 2:
            key_col = df.columns[0]
            desc_col = df.columns[1]
            
            for _, row in df.iterrows():
                key = str(row[key_col]).strip()
                desc = str(row[desc_col]).strip()
                
                # NaN 체크
                if key == 'nan' or desc == 'nan':
                    continue
                
                # 추가 컬럼 정보 포함
                extra_info = []
                for col in df.columns[2:]:
                    val = row[col]
                    if pd.notna(val) and str(val).strip() and str(val).strip() != 'nan':
                        extra_info.append(f"{col}={val}")
                
                if extra_info:
                    desc += " | " + " | ".join(extra_info)
                
                definitions[key] = desc
        
        return definitions
        
    except Exception:
        return {}


def _parse_metadata_fallback(file_path: str) -> dict:
    """
    Processor 실패 시 직접 파싱 폴백
    """
    definitions = {}
    
    try:
        df = pd.read_csv(file_path)
        
        if len(df.columns) >= 2:
            key_col = df.columns[0]
            desc_col = df.columns[1]
            
            for _, row in df.iterrows():
                key = str(row[key_col]).strip()
                desc = str(row[desc_col]).strip()
                
                if key == 'nan' or desc == 'nan':
                    continue
                
                extra_info = []
                for col in df.columns[2:]:
                    val = row[col]
                    if pd.notna(val) and str(val).strip() and str(val).strip() != 'nan':
                        extra_info.append(f"{col}={val}")
                
                if extra_info:
                    desc += " | " + " | ".join(extra_info)
                
                definitions[key] = desc
        
        return definitions
        
    except Exception as e:
        print(f"      ❌ [Fallback Parse Error] {file_path}: {e}")
        return {}


def build_lightweight_classification_context(file_path: str, max_rows: int = 10) -> dict:
    """
    [Rule] 파일에서 직접 간단한 샘플만 읽어 분류용 context 생성 (extract_metadata 없이)
    
    batch_classifier에서 metadata vs data 분류만 할 때 사용.
    전체 메타데이터 추출은 loader 노드에서 별도로 수행.
    """
    basename = os.path.basename(file_path)
    name_without_ext = os.path.splitext(basename)[0]
    extension = os.path.splitext(basename)[1].lower()
    
    parts = name_without_ext.split('_')
    base_name = parts[0] if parts else name_without_ext
    
    columns = []
    sample_data = []
    
    try:
        # CSV/TSV 파일만 처리 (다른 형식은 rule-based로 처리)
        if extension in ['.csv', '.tsv']:
            sep = '\t' if extension == '.tsv' else ','
            df = pd.read_csv(file_path, nrows=max_rows, sep=sep)
            columns = df.columns.tolist()
            
            # 간단한 샘플 데이터 생성
            for col in columns[:10]:  # 최대 10개 컬럼만
                col_data = df[col].dropna()
                unique_vals = col_data.unique()[:5].tolist()  # 최대 5개 unique values
                
                # numpy 타입을 Python 타입으로 변환
                unique_vals = [
                    int(v) if hasattr(v, 'item') and isinstance(v.item(), int) else
                    float(v) if hasattr(v, 'item') and isinstance(v.item(), float) else
                    str(v) for v in unique_vals
                ]
                
                sample_data.append({
                    "column": col,
                    "samples": unique_vals,
                    "is_text": df[col].dtype == object
                })
        else:
            # 비-CSV 파일은 파일명만으로 판단
            pass
            
    except Exception as e:
        print(f"⚠️ [Lightweight Context] Error reading {basename}: {e}")
    
    return {
        "filename": basename,
        "name_parts": parts,
        "base_name": base_name,
        "extension": extension,
        "columns": columns,
        "num_columns": len(columns),
        "sample_data": sample_data,
        "avg_text_length_overall": 0,  # 간소화 - 사용 안함
        "context_size_bytes": 0
    }


def extract_filename_hints(filename: str) -> dict:
    """
    [Rule + LLM] Extract semantic hints from filename
    """
    basename = os.path.basename(filename)
    name_without_ext = os.path.splitext(basename)[0]
    extension = os.path.splitext(basename)[1]
    
    parts = name_without_ext.split('_')
    base_name = parts[0] if parts else name_without_ext
    
    prefix = parts[0] if len(parts) >= 2 else None
    suffix = parts[-1] if len(parts) >= 2 else None
    
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
    
    cached = _get_llm_cache().get("filename_hints", parsed_structure)
    if cached:
        return cached
    
    prompt = f"""
You are a Data Architecture Analyst.
Infer semantic meaning from this parsed filename structure.

[PARSED FILENAME STRUCTURE]
{json.dumps(parsed_structure, indent=2)}

[TASK]
Infer:
1. **Entity Type**: What domain entity does base_name represent?
2. **Scope**: individual, event, measurement, treatment
3. **Suggested Hierarchy Level**: 1(highest) to 5(lowest)
4. **Data Type Indicator**: transactional, metadata, or reference

[OUTPUT FORMAT - JSON]
{{
    "entity_type": "Laboratory" or null,
    "scope": "measurement" or null,
    "suggested_level": 4 or null,
    "data_type_indicator": "transactional" or "metadata",
    "related_file_patterns": [],
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation"
}}
"""
    
    try:
        hints = _get_llm_client().ask_json(prompt)
        
        hints["filename"] = basename
        hints["base_name"] = base_name
        hints["parts"] = parts
        
        _get_llm_cache().set("filename_hints", parsed_structure, hints)
        
        if hints.get("confidence", 1.0) < HumanReviewConfig.FILENAME_ANALYSIS_CONFIDENCE_THRESHOLD:
            print(f"⚠️  [Filename Analysis] Low confidence ({hints.get('confidence'):.2%}) for {basename}")
        
        return hints
        
    except Exception as e:
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


def summarize_existing_tables(ontology_context: dict, processed_files_data: dict = None) -> dict:
    """
    [Rule] Summarize existing table info (for LLM)
    """
    tables = {}
    
    for file_path, tag_info in ontology_context.get("file_tags", {}).items():
        if tag_info.get("type") == "transactional_data":
            table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_")
            
            columns = tag_info.get("columns", [])
            
            if not columns and processed_files_data:
                columns = processed_files_data.get(file_path, {}).get("columns", [])
            
            tables[table_name] = {
                "file_path": file_path,
                "type": tag_info.get("type"),
                "columns": columns
            }
    
    return tables


def find_common_columns(current_cols: List[str], existing_tables: dict) -> List[dict]:
    """
    [Rule] Find common columns between current table and existing tables (FK candidate search)
    """
    candidates = []
    
    for table_name, table_info in existing_tables.items():
        existing_cols = table_info.get("columns", [])
        
        common_cols = set(current_cols) & set(existing_cols)
        
        for common_col in common_cols:
            candidates.append({
                "column_name": common_col,
                "current_table": "new_table",
                "existing_table": table_name,
                "match_type": "exact_name",
                "confidence_hint": 0.9
            })
    
    # Find similar names (underscore normalization)
    for table_name, table_info in existing_tables.items():
        existing_cols = table_info.get("columns", [])
        
        for curr_col in current_cols:
            for exist_col in existing_cols:
                curr_normalized = curr_col.replace('_', '').lower()
                exist_normalized = exist_col.replace('_', '').lower()
                
                if curr_normalized == exist_normalized and curr_col != exist_col:
                    candidates.append({
                        "current_col": curr_col,
                        "existing_col": exist_col,
                        "existing_table": table_name,
                        "match_type": "similar_name",
                        "confidence_hint": 0.7
                    })
    
    return candidates


def infer_relationships_with_llm(
    current_table_name: str,
    current_cols: List[str],
    ontology_context: dict,
    current_metadata: dict
) -> dict:
    """
    [Rule 전처리 + LLM 판단] 테이블 간 관계 추론
    """
    # 파일명 힌트
    filename_hints = extract_filename_hints(current_table_name)
    
    # 기존 테이블 요약
    existing_tables = summarize_existing_tables(ontology_context)
    
    # FK 후보
    fk_candidates = find_common_columns(current_cols, existing_tables)
    
    # 카디널리티 분석
    cardinality_hints = {}
    column_details = current_metadata.get("column_details", [])
    
    for col_info in column_details:
        if not isinstance(col_info, dict):
            continue
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
    
    llm_context = {
        "current_table": current_table_name,
        "current_cols": current_cols,
        "filename_hints": filename_hints,
        "fk_candidates": fk_candidates,
        "cardinality": cardinality_hints,
        "existing_tables": existing_tables,
        "definitions": ontology_context.get("definitions", {})
    }
    
    cached = _get_llm_cache().get("relationship_inference", llm_context)
    if cached:
        print(f"✅ [Cache Hit] 관계 추론 캐시 사용")
        return cached
    
    prompt = f"""
You are a Database Schema Architect for Medical Data Integration.
Infer table relationships from pre-processed data.

[NEW TABLE]
Name: {current_table_name}
Columns: {current_cols}

[FILENAME HINTS]
{json.dumps(filename_hints, indent=2)}

[FK CANDIDATES (Common Columns)]
{json.dumps(fk_candidates, indent=2)}

[CARDINALITY]
{json.dumps(cardinality_hints, indent=2)}

[EXISTING TABLES]
{json.dumps(existing_tables, indent=2)}

[TASK]
1. Validate FK Candidates using cardinality and filename hints
2. Determine Relationship Type (1:1, 1:N, N:1, M:N)
3. Infer Hierarchy

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
  "hierarchy": [],
  "reasoning": "Overall explanation"
}}
"""
    
    try:
        result = _get_llm_client().ask_json(prompt)
        _get_llm_cache().set("relationship_inference", llm_context, result)
        
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


# =============================================================================
# Hybrid Approach: LLM Enrichment Functions
# =============================================================================

def extract_relevant_context(conversation_history: Dict[str, Any]) -> str:
    """
    [Helper] 대화 히스토리에서 LLM 프롬프트에 사용할 관련 컨텍스트만 추출
    
    전체 히스토리가 아닌 핵심 결정사항과 사용자 선호도만 추출하여
    토큰 사용량을 최소화합니다.
    
    Args:
        conversation_history: 전체 대화 히스토리 (state의 conversation_history)
    
    Returns:
        LLM 프롬프트에 삽입할 컨텍스트 문자열
    """
    if not conversation_history:
        return ""
    
    context_parts = []
    
    # 1. 사용자 선호도 (학습된 패턴)
    user_preferences = conversation_history.get("user_preferences", {})
    if user_preferences:
        prefs_text = "\n".join([f"  - {k}: {v}" for k, v in user_preferences.items()])
        context_parts.append(f"[USER PREFERENCES]\n{prefs_text}")
    
    # 2. 이전 분류 결정 (최근 3개만)
    classification_decisions = conversation_history.get("classification_decisions", [])[-3:]
    if classification_decisions:
        decisions_text = "\n".join([
            f"  - {d.get('file', 'unknown')}: {d.get('response', '')}" 
            for d in classification_decisions
        ])
        context_parts.append(f"[PREVIOUS CLASSIFICATION DECISIONS]\n{decisions_text}")
    
    # 3. 이전 앵커 결정 (최근 3개만)
    anchor_decisions = conversation_history.get("anchor_decisions", [])[-3:]
    if anchor_decisions:
        decisions_text = "\n".join([
            f"  - {d.get('file', 'unknown')}: {d.get('response', '')}"
            for d in anchor_decisions
        ])
        context_parts.append(f"[PREVIOUS ANCHOR DECISIONS]\n{decisions_text}")
    
    # 4. 최근 대화에서 도메인 힌트 추출 (사용자가 준 설명)
    turns = conversation_history.get("turns", [])[-MetadataEnrichmentConfig.MAX_CONVERSATION_TURNS:]
    domain_hints = []
    for turn in turns:
        response = turn.get("human_response", "")
        # 의미있는 설명이 포함된 응답만 추출 (단순 확인 제외)
        if response and len(response) > 10 and response.lower() not in ["ok", "확인", "yes", "y", "approve"]:
            domain_hints.append(f"  - Q: {turn.get('agent_question', '')[:80]}...")
            domain_hints.append(f"    A: {response}")
    
    if domain_hints:
        context_parts.append(f"[DOMAIN HINTS FROM USER]\n" + "\n".join(domain_hints[-6:]))  # 최대 3쌍
    
    if not context_parts:
        return ""
    
    return "\n\n".join(context_parts)


def enrich_definitions_with_llm(
    definitions: Dict[str, str],
    conversation_context: str = "",
    chunk_size: int = MetadataEnrichmentConfig.ENRICHMENT_CHUNK_SIZE,
    dataset_domain: str = "medical",
    max_chunks: Optional[int] = None  # NEW: 처리할 최대 청크 수 (None이면 전체)
) -> List[Dict[str, str]]:
    """
    [LLM] 규칙 기반으로 파싱된 definitions를 LLM으로 의미론적으로 풍부하게 만듦
    
    기존 parse_metadata_content()로 추출한 단순 {key: desc} 형태를
    의료 도메인 관점에서 enriched_definition으로 변환합니다.
    
    Args:
        definitions: 규칙 기반 파싱 결과 {term: description}
        conversation_context: extract_relevant_context()로 추출한 컨텍스트
        chunk_size: LLM에 한 번에 보낼 definition 수
        dataset_domain: 데이터셋 도메인 (medical, clinical, etc.)
        max_chunks: 처리할 최대 청크 수 (None이면 전체, 1이면 첫 번째만)
    
    Returns:
        List[Dict]: [{
            "name": "caseid",
            "enriched_definition": "수술 케이스 고유 식별자. 한 환자가 여러 수술을...",
            "analysis_context": "user_hint: 수술ID"
        }, ...]
    """
    if not definitions:
        return []
    
    enriched_results = []
    definition_items = list(definitions.items())
    total_chunks = (len(definition_items) + chunk_size - 1) // chunk_size
    
    # max_chunks 적용
    chunks_to_process = total_chunks
    if max_chunks is not None:
        chunks_to_process = min(max_chunks, total_chunks)
    
    if max_chunks and max_chunks < total_chunks:
        print(f"\n   🧠 [LLM Enrichment] {len(definitions)}개 용어 중 {chunks_to_process}/{total_chunks}개 청크만 분석 (빠른 테스트 모드)")
    else:
        print(f"\n   🧠 [LLM Enrichment] {len(definitions)}개 용어를 {total_chunks}개 청크로 분석")
    
    processed_chunks = 0
    for chunk_idx in range(0, len(definition_items), chunk_size):
        # max_chunks 체크
        if max_chunks is not None and processed_chunks >= max_chunks:
            remaining = total_chunks - processed_chunks
            print(f"      ⏭️ 나머지 {remaining}개 청크 스킵 (빠른 테스트 모드)")
            break
        
        chunk = definition_items[chunk_idx:chunk_idx + chunk_size]
        chunk_num = chunk_idx // chunk_size + 1
        
        # 캐시 키 생성 (청크 내용 기반)
        cache_key = {
            "chunk": [(k, v[:100]) for k, v in chunk],  # 설명 100자로 제한
            "context_hash": hash(conversation_context[:200]) if conversation_context else 0
        }
        
        cached = _get_llm_cache().get("definition_enrichment", cache_key)
        if cached:
            print(f"      ✅ [Cache Hit] 청크 {chunk_num}/{total_chunks}")
            enriched_results.extend(cached)
            processed_chunks += 1
            continue
        
        # 청크 데이터 포맷팅
        definitions_text = "\n".join([
            f"- {term}: {desc[:200]}{'...' if len(desc) > 200 else ''}"
            for term, desc in chunk
        ])
        
        # 컨텍스트 포함 여부
        context_section = ""
        if conversation_context:
            context_section = f"""
[CONVERSATION CONTEXT - Use this to improve analysis accuracy]
{conversation_context}
"""
        
        prompt = f"""You are a Medical Data Ontologist specializing in healthcare terminology.
Enrich the following term definitions with detailed medical domain knowledge.

{context_section}
[TERMS TO ENRICH]
{definitions_text}

[TASK]
For each term, provide:
1. **enriched_definition**: A comprehensive medical definition including:
   - Full medical term (if abbreviated)
   - What it represents in clinical context
   - Typical usage/importance in medical data
   - Relationship to patient care
   
2. **semantic_category**: One of:
   - identifier (patient ID, case ID, etc.)
   - demographic (age, sex, etc.)
   - vital_sign (HR, BP, etc.)
   - laboratory (lab test results)
   - medication (drug info)
   - procedure (surgery, intervention)
   - diagnosis (ICD codes, conditions)
   - temporal (dates, timestamps)
   - administrative (hospital info)
   - measurement (clinical measurements)
   - other

3. **korean_summary**: 한글 요약 (1-2문장)

[OUTPUT FORMAT - JSON]
{{
    "enrichments": [
        {{
            "name": "term_name",
            "enriched_definition": "Detailed medical definition...",
            "semantic_category": "identifier",
            "korean_summary": "한글 요약"
        }}
    ]
}}

IMPORTANT:
- If conversation context provides user hints about terms, PRIORITIZE that information
- Keep enriched_definition concise but informative (max 200 chars)
- Use standard medical terminology where applicable
"""
        from src.config import LLMConfig
        
        try:
            result = _get_llm_client().ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS_ENRICHMENT)
            chunk_enrichments = result.get("enrichments", [])
            
            # 분석 컨텍스트 추가
            for item in chunk_enrichments:
                item["analysis_context"] = f"chunk_{chunk_num}, context_provided={bool(conversation_context)}"
            
            _get_llm_cache().set("definition_enrichment", cache_key, chunk_enrichments)
            enriched_results.extend(chunk_enrichments)
            processed_chunks += 1
            
            print(f"      ✅ 청크 {chunk_num}/{total_chunks} 완료 ({len(chunk_enrichments)}개)")
            
        except Exception as e:
            print(f"      ⚠️ 청크 {chunk_num} 실패: {e}")
            processed_chunks += 1
            # 실패 시 원본 유지
            for term, desc in chunk:
                enriched_results.append({
                    "name": term,
                    "enriched_definition": desc,
                    "semantic_category": "other",
                    "korean_summary": "",
                    "analysis_context": f"error: {str(e)[:50]}"
                })
    
    skipped_count = len(definitions) - len(enriched_results)
    if skipped_count > 0:
        print(f"   ✅ [LLM Enrichment] 완료: {len(enriched_results)}개 분석, {skipped_count}개 스킵")
    else:
        print(f"   ✅ [LLM Enrichment] 완료: {len(enriched_results)}개 용어 분석됨")
    return enriched_results


def infer_concept_relationships(
    definitions: Dict[str, str],
    enrichments: List[Dict[str, str]],
    conversation_context: str = ""
) -> Dict[str, Any]:
    """
    [LLM] 개념(Concept) 간의 관계 추론
    
    메타데이터에서 추출한 용어들 사이의 관계를 추론합니다.
    예: caseid와 subjectid가 계층 관계임을 파악
    
    Args:
        definitions: 원본 definitions
        enrichments: enrich_definitions_with_llm()의 결과
        conversation_context: 대화 컨텍스트
    
    Returns:
        Dict with:
        - concept_relationships: [{source, target, relation_type, reasoning}, ...]
        - hierarchy_hints: [{concept, level, reasoning}, ...]
    """
    if not definitions or len(definitions) < 2:
        return {"concept_relationships": [], "hierarchy_hints": []}
    
    # ID 관련 용어 필터링 (관계 추론에 집중)
    id_terms = [e for e in enrichments if e.get("semantic_category") == "identifier"]
    
    if len(id_terms) < 2:
        # ID 용어가 부족하면 전체에서 샘플링
        sample_terms = enrichments[:20] if len(enrichments) > 20 else enrichments
    else:
        sample_terms = id_terms[:10]  # ID 용어 최대 10개
    
    # 캐시 확인
    cache_key = {
        "terms": [t["name"] for t in sample_terms],
        "context_hash": hash(conversation_context[:100]) if conversation_context else 0
    }
    
    cached = _get_llm_cache().get("concept_relationships", cache_key)
    if cached:
        print(f"   ✅ [Cache Hit] 개념 관계 추론 캐시 사용")
        return cached
    
    # 용어 요약 생성
    terms_summary = "\n".join([
        f"- {t['name']}: {t.get('enriched_definition', '')[:100]}... (category: {t.get('semantic_category', 'unknown')})"
        for t in sample_terms
    ])
    
    context_section = f"\n[USER CONTEXT]\n{conversation_context}" if conversation_context else ""
    
    prompt = f"""You are a Medical Data Ontologist analyzing term relationships.

[TERMS FROM METADATA]
{terms_summary}
{context_section}
[TASK]
1. Identify HIERARCHICAL relationships between identifier terms
   - Example: subjectid (patient) → caseid (surgery case) is a 1:N hierarchy
   - Patient level > Case/Visit level > Measurement level

2. Identify SEMANTIC relationships between concepts
   - Example: "age" and "sex" are both "demographic" attributes
   - Example: "HR" and "BP" are both "vital_sign" measurements

[OUTPUT FORMAT - JSON]
{{
    "concept_relationships": [
        {{
            "source": "subjectid",
            "target": "caseid",
            "relation_type": "PARENT_OF",
            "cardinality": "1:N",
            "reasoning": "One patient can have multiple surgery cases"
        }}
    ],
    "hierarchy_hints": [
        {{
            "concept": "subjectid",
            "level": 1,
            "entity_type": "patient",
            "reasoning": "Top-level patient identifier"
        }},
        {{
            "concept": "caseid",
            "level": 2,
            "entity_type": "case",
            "reasoning": "Surgery case, child of patient"
        }}
    ],
    "semantic_groups": [
        {{
            "group_name": "patient_identifiers",
            "members": ["subjectid", "patientid"],
            "reasoning": "Both refer to patient identification"
        }}
    ]
}}

IMPORTANT:
- Only include relationships you are confident about
- Common medical hierarchies: Patient > Case/Visit > Measurement > Signal
- If no clear relationships found, return empty arrays
"""
    
    try:
        result = _get_llm_client().ask_json(prompt)
        
        # 결과 정리
        output = {
            "concept_relationships": result.get("concept_relationships", []),
            "hierarchy_hints": result.get("hierarchy_hints", []),
            "semantic_groups": result.get("semantic_groups", [])
        }
        
        _get_llm_cache().set("concept_relationships", cache_key, output)
        
        print(f"   ✅ [Concept Relations] 발견: {len(output['concept_relationships'])}개 관계, {len(output['hierarchy_hints'])}개 계층 힌트")
        
        return output
        
    except Exception as e:
        print(f"   ⚠️ [Concept Relations] 추론 실패: {e}")
        return {"concept_relationships": [], "hierarchy_hints": [], "semantic_groups": []}
