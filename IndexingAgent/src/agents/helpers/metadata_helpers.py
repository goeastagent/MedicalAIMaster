# src/agents/helpers/metadata_helpers.py
"""
메타데이터 처리 관련 헬퍼 함수들
"""

import os
import json
import numpy as np
import pandas as pd
from typing import Dict, Any, List

from src.utils.llm_client import get_llm_client
from src.utils.llm_cache import get_llm_cache

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
from src.config import HumanReviewConfig, ProcessingConfig


def collect_negative_evidence(col_name: str, samples: list, unique_vals: list) -> dict:
    """
    [Rule] Collect negative evidence (detect data quality issues)
    """
    total = len(samples)
    unique = len(unique_vals)
    
    null_count = sum(
        1 for s in samples 
        if s is None or s == '' or (isinstance(s, float) and np.isnan(s))
    )
    
    negative_evidence = []
    
    if total > 0 and unique / total > 0.95 and unique != total:
        dup_rate = (total - unique) / total
        negative_evidence.append({
            "type": "near_unique_with_duplicates",
            "detail": f"{unique/total:.1%} unique BUT {dup_rate:.1%} duplicates",
            "severity": "medium"
        })
    
    if 'id' in col_name.lower() and null_count > 0:
        null_rate = null_count / total
        negative_evidence.append({
            "type": "identifier_with_nulls",
            "detail": f"Column name suggests ID BUT {null_rate:.1%} null values",
            "severity": "high" if null_rate > 0.1 else "low"
        })
    
    if unique > 100:
        negative_evidence.append({
            "type": "high_cardinality",
            "detail": f"{unique} unique values - might be free text",
            "severity": "low"
        })
    
    return {
        "has_issues": len(negative_evidence) > 0,
        "issues": negative_evidence,
        "null_ratio": null_count / total if total > 0 else 0.0
    }


def summarize_long_values(values: list, max_length: int = None) -> list:
    """
    [Rule] Summarize long text (Context Window management)
    """
    if max_length is None:
        max_length = ProcessingConfig.MAX_TEXT_SUMMARY_LENGTH
        
    summarized = []
    
    for val in values:
        val_str = str(val)
        
        if len(val_str) > max_length:
            preview = val_str[:20].replace('\n', ' ')
            summarized.append(f"[Text: {len(val_str)} chars, starts='{preview}...']")
        else:
            summarized.append(val_str)
    
    return summarized


def parse_metadata_content(file_path: str) -> dict:
    """
    [Rule] Parse metadata file (CSV → Dictionary)
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


def build_metadata_detection_context(file_path: str, metadata: dict) -> dict:
    """
    [Rule] Build context for metadata detection (preprocessing)
    """
    basename = os.path.basename(file_path)
    name_without_ext = os.path.splitext(basename)[0]
    extension = os.path.splitext(basename)[1]
    
    parts = name_without_ext.split('_')
    base_name = parts[0] if parts else name_without_ext
    
    columns = metadata.get("columns", [])
    column_details = metadata.get("column_details", [])
    
    sample_summary = []
    total_text_length = 0
    
    # Handle dict vs list column_details
    if isinstance(column_details, dict):
        column_details_list = list(column_details.values())[:ProcessingConfig.MAX_COLUMN_DETAILS_FOR_LLM]
    elif isinstance(column_details, list):
        column_details_list = column_details[:ProcessingConfig.MAX_COLUMN_DETAILS_FOR_LLM]
    else:
        column_details_list = []
    
    for col_info in column_details_list:
        if not isinstance(col_info, dict):
            continue
        col_name = col_info.get('column_name', 'unknown')
        samples = col_info.get('samples', [])
        col_type = col_info.get('column_type', 'unknown')
        
        if col_type == 'categorical':
            unique_vals = col_info.get('unique_values', [])[:ProcessingConfig.MAX_UNIQUE_VALUES_DISPLAY]
            unique_vals_summarized = summarize_long_values(unique_vals)
        else:
            unique_vals = samples[:10]
            unique_vals_summarized = summarize_long_values(unique_vals)
        
        avg_length = 0.0
        if samples:
            text_lengths = [len(str(s)) for s in samples]
            avg_length = sum(text_lengths) / len(text_lengths)
            total_text_length += avg_length
        
        negative_evidence = collect_negative_evidence(col_name, samples, unique_vals if unique_vals else [])
        samples_summarized = summarize_long_values(samples[:3])
        
        sample_summary.append({
            "column": col_name,
            "type": col_type,
            "samples": samples_summarized,
            "unique_values": unique_vals_summarized,
            "avg_text_length": round(avg_length, 1),
            "null_ratio": negative_evidence.get("null_ratio", 0.0),
            "negative_evidence": negative_evidence.get("issues", [])
        })
    
    context_size = len(json.dumps(sample_summary))
    
    if context_size > ProcessingConfig.MAX_LLM_CONTEXT_SIZE_BYTES:
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

