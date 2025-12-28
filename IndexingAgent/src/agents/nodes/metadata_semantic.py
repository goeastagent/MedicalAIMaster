# src/agents/nodes/metadata_semantic.py
"""
Phase 1A: MetaData Semantic Analysis Node

metadata 파일에서 key-desc-unit을 추출하여 data_dictionary에 저장합니다.

✅ LLM 사용:
  1. 컬럼 역할 추론 (어떤 컬럼이 key/desc/unit인지)
  2. 비구조화 TXT 파일 파싱 (추후 지원)
"""

import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from src.agents.state import AgentState
from src.database.connection import get_db_manager
from src.database.schema_dictionary import (
    ensure_dictionary_schema,
    insert_dictionary_entries_batch,
    DictionarySchemaManager,
)
from src.config import Phase1Config, LLMConfig
from src.agents.models.llm_responses import (
    ColumnRoleMapping,
    ColumnRoleMappingResponse,
    DataDictionaryEntry,
    MetadataSemanticResult,
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

COLUMN_ROLE_PROMPT = """You are a Medical Data Expert analyzing a metadata/dictionary file.

[Task]
Analyze this file and identify which column serves which role:

- **key_column**: The column containing parameter names/codes (e.g., "age", "hr", "sbp")
  This is the main identifier column that other data files will reference.
  
- **desc_column**: The column containing descriptions or definitions
  Human-readable explanations of what each parameter means.
  
- **unit_column**: The column containing measurement units (e.g., "years", "bpm", "mmHg")
  May be empty or null for some parameters.
  
- **extra_columns**: Other useful columns mapped to their semantic role
  Examples: {{"category": "Category", "reference_value": "Reference value", "data_source": "Data Source"}}

[File Info]
File: {file_name}
Columns: {column_names}

[Columns with Sample Values]
{columns_info}

[Sample Rows (first 5)]
{sample_rows}

[Output Format]
Return ONLY valid JSON (no markdown, no explanation):
{{
  "key_column": "Parameter",
  "desc_column": "Description",
  "unit_column": "Unit",
  "extra_columns": {{"category": "Category", "reference": "Reference value"}},
  "confidence": 0.95,
  "reasoning": "Parameter column contains unique identifiers, Description has explanations, Unit has measurement units"
}}
"""


# =============================================================================
# 파일/컬럼 정보 수집
# =============================================================================

def _get_metadata_file_details(file_path: str) -> Optional[Dict[str, Any]]:
    """
    metadata 파일의 상세 정보 조회 (컬럼별 unique values 포함)
    
    Returns:
        {
            "file_id": str,
            "file_name": str,
            "file_path": str,
            "row_count": int,
            "columns": [
                {
                    "name": str,
                    "dtype": str,
                    "all_unique_values": List[str],  # 모든 unique values
                    "n_unique": int
                }
            ],
            "sample_rows": List[Dict]  # 첫 5행
        }
    """
    db = _get_db()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # 파일 기본 정보
        cursor.execute("""
            SELECT file_id, file_name, file_path, file_metadata, raw_stats
            FROM file_catalog
            WHERE file_path = %s
        """, (file_path,))
        
        row = cursor.fetchone()
        if not row:
            # file_name으로도 시도
            cursor.execute("""
                SELECT file_id, file_name, file_path, file_metadata, raw_stats
                FROM file_catalog
                WHERE file_name = %s
            """, (file_path.split('/')[-1],))
            row = cursor.fetchone()
        
        if not row:
            return None
        
        file_id, file_name, file_path_db, file_metadata, raw_stats = row
        
        # row_count 추출
        metadata = file_metadata if isinstance(file_metadata, dict) else {}
        raw = raw_stats if isinstance(raw_stats, dict) else {}
        row_count = metadata.get('row_count') or raw.get('row_count', 0)
        
        # sample_rows 추출
        sample_rows = raw.get('sample_rows', [])
        
        # 컬럼 정보 조회
        cursor.execute("""
            SELECT original_name, data_type, column_type, value_distribution
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,))
        
        columns = []
        for col_row in cursor.fetchall():
            col_name, dtype, col_type, value_dist = col_row
            
            # value_distribution에서 unique_values 추출
            dist = value_dist if isinstance(value_dist, dict) else {}
            unique_values = dist.get('unique_values', [])
            samples = dist.get('samples', [])
            
            # unique_values가 없으면 samples 사용
            all_unique = unique_values if unique_values else samples
            
            columns.append({
                "name": col_name,
                "dtype": dtype or "unknown",
                "column_type": col_type or "unknown",
                "all_unique_values": all_unique,
                "n_unique": len(all_unique)
            })
        
        return {
            "file_id": str(file_id),
            "file_name": file_name,
            "file_path": file_path_db or file_path,
            "row_count": row_count,
            "columns": columns,
            "sample_rows": sample_rows[:5] if sample_rows else []
        }
        
    except Exception as e:
        print(f"   ❌ Error getting metadata file details: {e}")
        return None


def _build_columns_info_text(columns: List[Dict[str, Any]]) -> str:
    """
    컬럼 정보를 LLM 프롬프트용 텍스트로 변환
    
    예시:
    1. "Parameter" [categorical, 82 unique values]
       dtype: object
       unique_ratio: 1.0
       All unique values: ["age", "sex", "height", ...]
    """
    lines = []
    
    for i, col in enumerate(columns, 1):
        col_name = col['name']
        col_type = col.get('column_type', 'unknown')
        n_unique = col.get('n_unique', 0)
        dtype = col.get('dtype', 'unknown')
        unique_vals = col.get('all_unique_values', [])
        
        lines.append(f'{i}. "{col_name}" [{col_type}, {n_unique} unique values]')
        lines.append(f"   dtype: {dtype}")
        
        # unique values 표시 (최대 20개)
        if unique_vals:
            vals_display = unique_vals[:20]
            vals_str = [str(v)[:50] for v in vals_display]
            lines.append(f"   Sample values: {vals_str}")
            if len(unique_vals) > 20:
                lines.append(f"   ... and {len(unique_vals) - 20} more values")
        
        lines.append("")
    
    return "\n".join(lines)


def _build_sample_rows_text(sample_rows: List[Dict], columns: List[Dict]) -> str:
    """샘플 행을 테이블 형식 텍스트로 변환"""
    if not sample_rows:
        return "(No sample rows available)"
    
    col_names = [c['name'] for c in columns]
    
    lines = []
    
    # 헤더
    header = " | ".join(col_names[:8])  # 최대 8개 컬럼만
    lines.append(header)
    lines.append("-" * len(header))
    
    # 데이터 행
    for row in sample_rows[:5]:
        if isinstance(row, dict):
            values = [str(row.get(c, ''))[:20] for c in col_names[:8]]
        else:
            values = [str(v)[:20] for v in list(row)[:8]]
        lines.append(" | ".join(values))
    
    return "\n".join(lines)


# =============================================================================
# LLM 호출
# =============================================================================

def _call_llm_for_column_roles(
    file_info: Dict[str, Any]
) -> Optional[ColumnRoleMapping]:
    """
    LLM을 호출하여 컬럼 역할 추론
    
    Returns:
        ColumnRoleMapping or None
    """
    llm = _get_llm()
    
    file_name = file_info['file_name']
    columns = file_info['columns']
    sample_rows = file_info.get('sample_rows', [])
    
    column_names = [c['name'] for c in columns]
    columns_info_text = _build_columns_info_text(columns)
    sample_rows_text = _build_sample_rows_text(sample_rows, columns)
    
    prompt = COLUMN_ROLE_PROMPT.format(
        file_name=file_name,
        column_names=", ".join(column_names),
        columns_info=columns_info_text,
        sample_rows=sample_rows_text
    )
    
    try:
        data = llm.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
        
        if data.get("error"):
            print(f"   ❌ LLM returned error: {data.get('error')}")
            return None
        
        return ColumnRoleMapping(
            key_column=data.get('key_column', ''),
            desc_column=data.get('desc_column'),
            unit_column=data.get('unit_column'),
            extra_columns=data.get('extra_columns', {}),
            confidence=data.get('confidence', 0.8),
            reasoning=data.get('reasoning', '')
        )
        
    except Exception as e:
        print(f"   ❌ LLM call error: {e}")
        return None


# =============================================================================
# Data Dictionary 추출
# =============================================================================

def _extract_dictionary_entries(
    file_info: Dict[str, Any],
    column_mapping: ColumnRoleMapping
) -> List[Dict[str, Any]]:
    """
    파일에서 data_dictionary 엔트리 추출
    
    컬럼 역할 매핑을 기반으로 각 행을 key-desc-unit 엔트리로 변환
    """
    file_id = file_info['file_id']
    file_name = file_info['file_name']
    columns = file_info['columns']
    
    # 컬럼명 → unique_values 매핑
    col_values = {c['name']: c.get('all_unique_values', []) for c in columns}
    
    key_col = column_mapping.key_column
    desc_col = column_mapping.desc_column
    unit_col = column_mapping.unit_column
    extra_cols = column_mapping.extra_columns  # {role: col_name}
    
    # key 컬럼이 없으면 추출 불가
    if not key_col or key_col not in col_values:
        print(f"   ⚠️ Key column '{key_col}' not found in file")
        return []
    
    # raw_stats에서 sample_rows 가져오기 (전체 데이터가 있으면 좋음)
    # 현재는 unique_values를 사용하여 추출
    
    # 방법 1: sample_rows가 있으면 사용
    sample_rows = file_info.get('sample_rows', [])
    
    entries = []
    
    if sample_rows:
        # sample_rows에서 추출
        for row in sample_rows:
            if not isinstance(row, dict):
                continue
            
            key_val = row.get(key_col)
            if not key_val:
                continue
            
            desc_val = row.get(desc_col) if desc_col else None
            unit_val = row.get(unit_col) if unit_col else None
            
            # extra_info 구성
            extra_info = {}
            for role, col_name in extra_cols.items():
                if col_name in row:
                    extra_info[role] = row[col_name]
            
            entries.append({
                'source_file_id': file_id,
                'source_file_name': file_name,
                'parameter_key': str(key_val),
                'parameter_desc': str(desc_val) if desc_val else None,
                'parameter_unit': str(unit_val) if unit_val else None,
                'extra_info': extra_info,
                'llm_confidence': column_mapping.confidence
            })
    else:
        # unique_values 기반으로 추출 (제한적)
        # key 컬럼의 각 값에 대해 엔트리 생성
        key_values = col_values.get(key_col, [])
        desc_values = col_values.get(desc_col, []) if desc_col else []
        unit_values = col_values.get(unit_col, []) if unit_col else []
        
        # 값들을 매칭 (같은 인덱스끼리 - 순서가 유지된다고 가정)
        for i, key_val in enumerate(key_values):
            desc_val = desc_values[i] if i < len(desc_values) else None
            unit_val = unit_values[i] if i < len(unit_values) else None
            
            entries.append({
                'source_file_id': file_id,
                'source_file_name': file_name,
                'parameter_key': str(key_val),
                'parameter_desc': str(desc_val) if desc_val else None,
                'parameter_unit': str(unit_val) if unit_val else None,
                'extra_info': {},
                'llm_confidence': column_mapping.confidence
            })
    
    return entries


def _extract_from_raw_data(file_info: Dict[str, Any], column_mapping: ColumnRoleMapping) -> List[Dict[str, Any]]:
    """
    raw_stats에 저장된 전체 데이터에서 dictionary 엔트리 추출
    
    Phase 0에서 저장한 raw_stats를 활용
    """
    import pandas as pd
    import os
    
    file_id = file_info['file_id']
    file_name = file_info['file_name']
    file_path = file_info['file_path']
    
    key_col = column_mapping.key_column
    desc_col = column_mapping.desc_column
    unit_col = column_mapping.unit_column
    extra_cols = column_mapping.extra_columns
    
    entries = []
    
    try:
        # 파일 직접 읽기 (가장 정확한 방법)
        if os.path.exists(file_path):
            ext = file_path.lower().split('.')[-1]
            
            if ext == 'csv':
                df = pd.read_csv(file_path)
            elif ext == 'tsv':
                df = pd.read_csv(file_path, sep='\t')
            elif ext in ['xlsx', 'xls']:
                df = pd.read_excel(file_path)
            else:
                print(f"   ⚠️ Unsupported file type: {ext}")
                return []
            
            # 각 행에서 엔트리 추출
            for _, row in df.iterrows():
                key_val = row.get(key_col)
                if pd.isna(key_val) or key_val == '':
                    continue
                
                desc_val = row.get(desc_col) if desc_col else None
                unit_val = row.get(unit_col) if unit_col else None
                
                # NaN 처리
                if pd.isna(desc_val):
                    desc_val = None
                if pd.isna(unit_val):
                    unit_val = None
                
                # extra_info 구성
                extra_info = {}
                for role, col_name in extra_cols.items():
                    if col_name in row.index:
                        val = row[col_name]
                        if not pd.isna(val):
                            extra_info[role] = str(val)
                
                entries.append({
                    'source_file_id': file_id,
                    'source_file_name': file_name,
                    'parameter_key': str(key_val),
                    'parameter_desc': str(desc_val) if desc_val else None,
                    'parameter_unit': str(unit_val) if unit_val else None,
                    'extra_info': extra_info,
                    'llm_confidence': column_mapping.confidence
                })
            
            print(f"      📄 Extracted {len(entries)} entries from file")
            
    except Exception as e:
        print(f"   ❌ Error reading file: {e}")
    
    return entries


# =============================================================================
# LangGraph Node Function
# =============================================================================

def metadata_semantic_node(state: AgentState) -> Dict[str, Any]:
    """
    Phase 1A: 메타데이터 파일에서 key-desc-unit 추출
    
    입력: state.metadata_files (Phase 0.7에서 분류된 metadata 파일들)
    
    처리:
    1. 각 metadata 파일에 대해:
       a. 파일 상세 정보 조회
       b. LLM 호출 → 컬럼 역할 추론
       c. 파일에서 dictionary 엔트리 추출
       d. data_dictionary 테이블에 저장
    
    출력:
    - phase1a_result: 처리 결과 요약
    - data_dictionary_entries: 추출된 모든 엔트리
    """
    print("\n" + "=" * 60)
    print("📖 Phase 1A: MetaData Semantic Analysis")
    print("=" * 60)
    
    started_at = datetime.now()
    
    # data_dictionary 테이블 확인/생성
    ensure_dictionary_schema()
    
    # metadata 파일 목록
    metadata_files = state.get("metadata_files", [])
    
    if not metadata_files:
        print("   ⚠️ No metadata files to process")
        return {
            "phase1a_result": {
                "total_metadata_files": 0,
                "processed_files": 0,
                "total_entries_extracted": 0,
                "error": "No metadata files"
            },
            "data_dictionary_entries": [],
            "logs": ["⚠️ [Phase 1A] No metadata files to process"]
        }
    
    print(f"   📂 Metadata files to process: {len(metadata_files)}")
    for f in metadata_files:
        print(f"      - {f.split('/')[-1]}")
    
    all_entries = []
    entries_by_file = {}
    processed_files = 0
    llm_calls = 0
    
    for file_path in metadata_files:
        file_name = file_path.split('/')[-1]
        print(f"\n   📄 Processing: {file_name}")
        
        # 1. 파일 상세 정보 조회
        file_info = _get_metadata_file_details(file_path)
        if not file_info:
            print(f"      ❌ Failed to get file details")
            continue
        
        print(f"      Columns: {[c['name'] for c in file_info['columns']]}")
        
        # 2. LLM 호출 → 컬럼 역할 추론
        print(f"      🤖 Calling LLM for column role mapping...")
        column_mapping = _call_llm_for_column_roles(file_info)
        llm_calls += 1
        
        if not column_mapping:
            print(f"      ❌ Failed to get column mapping")
            continue
        
        print(f"      ✅ Column roles identified (conf={column_mapping.confidence:.2f}):")
        print(f"         key: {column_mapping.key_column}")
        print(f"         desc: {column_mapping.desc_column}")
        print(f"         unit: {column_mapping.unit_column}")
        if column_mapping.extra_columns:
            print(f"         extra: {column_mapping.extra_columns}")
        
        # 3. Dictionary 엔트리 추출 (파일 직접 읽기)
        entries = _extract_from_raw_data(file_info, column_mapping)
        
        if not entries:
            # 대안: sample_rows/unique_values 기반 추출
            entries = _extract_dictionary_entries(file_info, column_mapping)
        
        if entries:
            # 4. DB에 저장
            print(f"      💾 Saving {len(entries)} entries to data_dictionary...")
            inserted = insert_dictionary_entries_batch(entries)
            print(f"      ✅ Saved {inserted} entries")
            
            all_entries.extend(entries)
            entries_by_file[file_name] = len(entries)
            processed_files += 1
        else:
            print(f"      ⚠️ No entries extracted")
    
    # 결과 요약
    completed_at = datetime.now()
    duration = (completed_at - started_at).total_seconds()
    
    result = MetadataSemanticResult(
        total_metadata_files=len(metadata_files),
        processed_files=processed_files,
        total_entries_extracted=len(all_entries),
        entries_by_file=entries_by_file,
        llm_calls=llm_calls,
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat()
    )
    
    print(f"\n✅ Phase 1A Complete!")
    print(f"   📁 Processed files: {processed_files}/{len(metadata_files)}")
    print(f"   📝 Total entries: {len(all_entries)}")
    for fname, count in entries_by_file.items():
        print(f"      - {fname}: {count} entries")
    print(f"   🤖 LLM calls: {llm_calls}")
    print(f"   ⏱️  Duration: {duration:.1f}s")
    print("=" * 60 + "\n")
    
    # 통계 출력
    schema_manager = DictionarySchemaManager()
    stats = schema_manager.get_stats()
    print(f"   📊 Data Dictionary Stats: {stats}")
    
    return {
        "phase1a_result": result.model_dump(),
        "data_dictionary_entries": all_entries,
        "logs": [
            f"📖 [Phase 1A] Extracted {len(all_entries)} entries from "
            f"{processed_files} metadata files"
        ]
    }


# =============================================================================
# 편의 함수
# =============================================================================

def run_metadata_semantic_standalone(metadata_files: List[str] = None) -> Dict[str, Any]:
    """
    Phase 1A 독립 실행 (테스트용)
    
    Args:
        metadata_files: 처리할 metadata 파일 경로 목록
                       None이면 DB에서 is_metadata=true인 파일 조회
    
    Returns:
        처리 결과
    """
    if metadata_files is None:
        # DB에서 is_metadata=true인 파일 조회
        db = _get_db()
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT file_path FROM file_catalog 
            WHERE is_metadata = true 
            ORDER BY file_name
        """)
        metadata_files = [row[0] for row in cursor.fetchall()]
    
    # State 시뮬레이션
    state = {
        "metadata_files": metadata_files
    }
    
    return metadata_semantic_node(state)

