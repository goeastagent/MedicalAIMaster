# src/agents/nodes/classification.py
"""
Phase 0.7: File Classification Node

파일을 metadata/data로 분류합니다.
- metadata: 데이터 사전, 파라미터 정의 파일 (clinical_parameters.csv 등)
- data: 실제 측정/기록 데이터 파일 (clinical_data.csv 등)

✅ LLM 사용: is_metadata 판단
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.agents.state import AgentState
from src.database.connection import get_db_manager
from src.config import Phase5Config, LLMConfig
from src.agents.models.llm_responses import (
    FileClassificationItem,
    FileClassificationResponse,
    FileClassificationResult,
)


from src.utils.llm_client import get_llm_client


# =============================================================================
# 프롬프트 템플릿
# =============================================================================

FILE_CLASSIFICATION_PROMPT = """You are a Medical Data Expert specializing in healthcare informatics.

[Task]
Classify each file as "metadata" or "data":

**metadata** files:
- Data dictionaries, codebooks, parameter definitions, lookup tables
- Typically contain columns like: Parameter, Description, Unit, Code, Category
- Values are mostly text descriptions, definitions, or codes
- Purpose: Define or describe what data means
- Examples: clinical_parameters.csv, lab_parameters.csv, track_names.csv

**data** files:
- Actual measurements, patient records, lab results, vital signs
- Typically contain columns like: patient_id, timestamp, measured values
- Values are mostly numbers, IDs, dates, measurements
- Purpose: Store actual recorded data
- Examples: clinical_data.csv, lab_data.csv, vitals.csv

[Files to Classify]
{files_info}

[Output Format]
Return ONLY valid JSON (no markdown, no explanation):
{{
  "classifications": [
    {{
      "file_name": "example.csv",
      "is_metadata": true,
      "confidence": 0.95,
      "reasoning": "Contains Parameter, Description, Unit columns typical of a data dictionary"
    }}
  ]
}}
"""


# =============================================================================
# 파일 정보 수집
# =============================================================================

def _get_file_info_for_classification(file_id: str) -> Optional[Dict[str, Any]]:
    """
    DB에서 파일 정보 조회 (분류용)
    
    Returns:
        {
            "file_id": str,
            "file_name": str,
            "file_path": str,
            "row_count": int,
            "column_count": int,
            "columns": [
                {
                    "name": str,
                    "dtype": str,
                    "unique_values": List[str],  # 샘플
                    "n_unique": int
                }
            ]
        }
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # 파일 기본 정보
        cursor.execute("""
            SELECT file_id, file_name, file_path, file_metadata, raw_stats
            FROM file_catalog
            WHERE file_id = %s
        """, (file_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        file_id, file_name, file_path, file_metadata, raw_stats = row
        
        # row_count, column_count 추출
        metadata = file_metadata if isinstance(file_metadata, dict) else {}
        row_count = metadata.get('row_count', 0)
        column_count = metadata.get('column_count', 0)
        
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
            if not unique_values and samples:
                unique_values = samples
            
            # 최대 10개만
            unique_values = unique_values[:10] if unique_values else []
            
            columns.append({
                "name": col_name,
                "dtype": dtype or "unknown",
                "column_type": col_type or "unknown",
                "unique_values": unique_values,
                "n_unique": len(unique_values)
            })
        
        return {
            "file_id": str(file_id),
            "file_name": file_name,
            "file_path": file_path,
            "row_count": row_count,
            "column_count": column_count or len(columns),
            "columns": columns
        }
        
    except Exception as e:
        print(f"   ❌ Error getting file info: {e}")
        return None


def _build_files_info_text(file_infos: List[Dict[str, Any]]) -> str:
    """
    파일 정보를 LLM 프롬프트용 텍스트로 변환
    
    예시 출력:
    1. "clinical_parameters.csv" [tabular, 4 columns, 82 rows]
       Columns: Parameter, Data Source, Description, Unit
       Sample values per column:
       - Parameter: ["age", "sex", "height", "weight", "bmi"]
       - Description: ["Age", "Sex", "Height", "Weight", "Body mass index"]
       - Unit: ["years", "M/F", "cm", "kg", "kg/m2"]
    """
    lines = []
    
    for i, info in enumerate(file_infos, 1):
        file_name = info.get('file_name', '?')
        col_count = info.get('column_count', 0)
        row_count = info.get('row_count', 0)
        columns = info.get('columns', [])
        
        # 파일 헤더
        lines.append(f'{i}. "{file_name}" [tabular, {col_count} columns, {row_count} rows]')
        
        # 컬럼명 목록
        col_names = [c['name'] for c in columns]
        lines.append(f"   Columns: {', '.join(col_names[:15])}")
        if len(col_names) > 15:
            lines.append(f"            ... and {len(col_names) - 15} more columns")
        
        # 컬럼별 샘플 값 (최대 5개 컬럼만)
        lines.append("   Sample values per column:")
        for col in columns[:5]:
            col_name = col['name']
            unique_vals = col.get('unique_values', [])
            # 값을 문자열로 변환하고 최대 5개만
            vals_str = [str(v)[:30] for v in unique_vals[:5]]
            lines.append(f"   - {col_name}: {vals_str}")
        
        if len(columns) > 5:
            lines.append(f"   ... and {len(columns) - 5} more columns")
        
        lines.append("")  # 빈 줄
    
    return "\n".join(lines)


# =============================================================================
# LLM 호출
# =============================================================================

def _call_llm_for_classification(
    file_infos: List[Dict[str, Any]]
) -> List[FileClassificationItem]:
    """
    LLM을 호출하여 파일 분류
    
    Returns:
        List[FileClassificationItem]
    """
    llm = get_llm_client()
    
    files_info_text = _build_files_info_text(file_infos)
    prompt = FILE_CLASSIFICATION_PROMPT.format(files_info=files_info_text)
    
    try:
        data = llm.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
        
        if data.get("error"):
            print(f"   ❌ LLM returned error: {data.get('error')}")
            return []
        
        classifications = []
        for item in data.get('classifications', []):
            try:
                classification = FileClassificationItem(**item)
                classifications.append(classification)
            except Exception as e:
                print(f"   ⚠️ Failed to parse classification for {item.get('file_name', '?')}: {e}")
        
        return classifications
        
    except Exception as e:
        print(f"   ❌ LLM call error: {e}")
        return []


# =============================================================================
# DB 업데이트
# =============================================================================

def _update_file_is_metadata(file_name: str, is_metadata: bool, confidence: float):
    """file_catalog.is_metadata 업데이트"""
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE file_catalog
            SET is_metadata = %s, llm_confidence = %s, llm_analyzed_at = NOW()
            WHERE file_name = %s
        """, (is_metadata, confidence, file_name))
        
        conn.commit()
        return cursor.rowcount
        
    except Exception as e:
        conn.rollback()
        print(f"   ❌ Error updating is_metadata: {e}")
        return 0


# =============================================================================
# LangGraph Node Function
# =============================================================================

def phase4_classification_node(state: AgentState) -> Dict[str, Any]:
    """
    Phase 0.7: 파일을 metadata/data로 분류
    
    입력: state.phase0_file_ids (Phase 0에서 처리된 파일들)
    
    처리:
    1. 각 파일의 정보 수집 (컬럼명, unique values)
    2. LLM 호출 → is_metadata 판단
    3. file_catalog.is_metadata 업데이트
    
    출력:
    - phase07_result: 분류 결과 요약
    - metadata_files: is_metadata=true 파일 경로 목록
    - data_files: is_metadata=false 파일 경로 목록
    """
    print("\n" + "=" * 60)
    print("🏷️  Phase 4: File Classification (metadata vs data)")
    print("=" * 60)
    
    started_at = datetime.now()
    
    # Phase 2에서 처리된 파일 ID들
    file_ids = state.get("phase2_file_ids", [])
    
    if not file_ids:
        print("   ⚠️ No files to classify")
        return {
            "phase4_result": {
                "total_files": 0,
                "metadata_files": [],
                "data_files": [],
                "error": "No files to classify"
            },
            "metadata_files": [],
            "data_files": [],
            "logs": ["⚠️ [Phase 4] No files to classify"]
        }
    
    print(f"   📂 Files to classify: {len(file_ids)}")
    
    # 1. 파일 정보 수집
    print("\n   📊 Collecting file information...")
    file_infos = []
    file_id_to_path = {}  # file_id → file_path 매핑
    
    for file_id in file_ids:
        info = _get_file_info_for_classification(file_id)
        if info:
            file_infos.append(info)
            file_id_to_path[info['file_name']] = info['file_path']
            print(f"      ✅ {info['file_name']} ({info['column_count']} cols, {info['row_count']} rows)")
        else:
            print(f"      ❌ Failed to get info for file_id: {file_id[:8]}...")
    
    if not file_infos:
        print("   ❌ No file info collected")
        return {
            "phase4_result": {"error": "No file info collected"},
            "metadata_files": [],
            "data_files": [],
            "logs": ["❌ [Phase 4] No file info collected"]
        }
    
    # 2. LLM 호출
    print(f"\n   🤖 Calling LLM for classification...")
    classifications = _call_llm_for_classification(file_infos)
    
    if not classifications:
        print("   ❌ LLM classification failed")
        return {
            "phase4_result": {"error": "LLM classification failed"},
            "metadata_files": [],
            "data_files": [],
            "logs": ["❌ [Phase 4] LLM classification failed"]
        }
    
    # 3. 결과 처리 및 DB 업데이트
    print(f"\n   📝 Processing {len(classifications)} classifications...")
    
    metadata_files = []
    data_files = []
    classifications_dict = {}
    
    for clf in classifications:
        file_name = clf.file_name
        is_metadata = clf.is_metadata
        confidence = clf.confidence
        reasoning = clf.reasoning
        
        # file_path 찾기
        file_path = file_id_to_path.get(file_name, file_name)
        
        # DB 업데이트
        updated = _update_file_is_metadata(file_name, is_metadata, confidence)
        
        # 결과 분류
        if is_metadata:
            metadata_files.append(file_path)
            marker = "📋 metadata"
        else:
            data_files.append(file_path)
            marker = "📊 data"
        
        print(f"      {marker}: {file_name} (conf={confidence:.2f})")
        
        classifications_dict[file_name] = {
            "file_path": file_path,
            "is_metadata": is_metadata,
            "confidence": confidence,
            "reasoning": reasoning
        }
    
    # 4. 결과 요약
    completed_at = datetime.now()
    duration = (completed_at - started_at).total_seconds()
    
    result = FileClassificationResult(
        total_files=len(file_infos),
        metadata_files=metadata_files,
        data_files=data_files,
        classifications=classifications_dict,
        llm_calls=1,
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat()
    )
    
    print(f"\n✅ Phase 4 Complete!")
    print(f"   📋 Metadata files: {len(metadata_files)}")
    for f in metadata_files:
        print(f"      - {f.split('/')[-1]}")
    print(f"   📊 Data files: {len(data_files)}")
    for f in data_files:
        print(f"      - {f.split('/')[-1]}")
    print(f"   ⏱️  Duration: {duration:.1f}s")
    print("=" * 60 + "\n")
    
    return {
        "phase4_result": result.model_dump(),
        "metadata_files": metadata_files,
        "data_files": data_files,
        "logs": [
            f"🏷️ [Phase 4] Classified {len(file_infos)} files: "
            f"{len(metadata_files)} metadata, {len(data_files)} data"
        ]
    }


# =============================================================================
# 편의 함수
# =============================================================================

def run_classification_standalone(file_ids: List[str] = None) -> Dict[str, Any]:
    """
    Phase 4 독립 실행 (테스트용)
    
    Args:
        file_ids: 분류할 파일 ID 목록 (None이면 DB에서 모든 파일 조회)
    
    Returns:
        분류 결과
    """
    if file_ids is None:
        # DB에서 모든 파일 ID 조회
        db = get_db_manager()
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT file_id FROM file_catalog ORDER BY file_name")
        file_ids = [str(row[0]) for row in cursor.fetchall()]
    
    # State 시뮬레이션
    state = {
        "phase2_file_ids": file_ids
    }
    
    return phase4_classification_node(state)