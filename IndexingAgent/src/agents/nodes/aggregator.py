# src/agents/nodes/aggregator.py
"""
Phase 3: Schema Aggregation Node

DB에서 유니크 컬럼명과 대표 통계를 집계하여
Phase 1의 배치 LLM 호출을 준비합니다.

핵심 기능:
- 유니크 컬럼명 추출 (GROUP BY original_name)
- 대표 통계 집계 (AVG min/max/mean, sample values)
- 배치 분할 (config.BATCH_SIZE 단위)
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.agents.state import AgentState
from src.database.connection import get_db_manager
from src.config import Phase3Config




# =============================================================================
# SQL 쿼리
# =============================================================================

# 유니크 컬럼 집계 쿼리 (Continuous)
AGGREGATE_CONTINUOUS_SQL = """
SELECT 
    cm.original_name,
    cm.column_type,
    COUNT(DISTINCT cm.file_id) as frequency,
    
    -- 수치형 통계 집계
    AVG((cm.column_info->>'min')::float) as avg_min,
    AVG((cm.column_info->>'max')::float) as avg_max,
    AVG((cm.column_info->>'mean')::float) as avg_mean,
    AVG((cm.column_info->>'std')::float) as avg_std,
    MAX(cm.column_info->>'unit') as sample_unit,
    
    -- 샘플 file_id (최대 N개)
    (SELECT array_agg(DISTINCT sub.file_id::text)
     FROM (
         SELECT file_id FROM column_metadata 
         WHERE original_name = cm.original_name 
         LIMIT %s
     ) sub
    ) as sample_file_ids

FROM column_metadata cm
WHERE cm.column_type IN ('continuous', 'waveform')
GROUP BY cm.original_name, cm.column_type
ORDER BY frequency DESC;
"""

# 유니크 컬럼 집계 쿼리 (Categorical)
AGGREGATE_CATEGORICAL_SQL = """
SELECT 
    cm.original_name,
    cm.column_type,
    COUNT(DISTINCT cm.file_id) as frequency,
    
    -- 범주형 통계 집계
    AVG((cm.column_info->>'unique_count')::float) as avg_unique_count,
    AVG((cm.column_info->>'unique_ratio')::float) as avg_unique_ratio,
    
    -- 대표 값 (첫 번째 파일에서 가져옴)
    (SELECT sub.value_distribution
     FROM column_metadata sub 
     WHERE sub.original_name = cm.original_name 
       AND sub.value_distribution != '{}'::jsonb
     LIMIT 1
    ) as sample_distribution,
    
    -- 샘플 file_id
    (SELECT array_agg(DISTINCT sub.file_id::text)
     FROM (
         SELECT file_id FROM column_metadata 
         WHERE original_name = cm.original_name 
         LIMIT %s
     ) sub
    ) as sample_file_ids

FROM column_metadata cm
WHERE cm.column_type = 'categorical'
GROUP BY cm.original_name, cm.column_type
ORDER BY frequency DESC;
"""

# 유니크 컬럼 집계 쿼리 (Datetime)
AGGREGATE_DATETIME_SQL = """
SELECT 
    cm.original_name,
    cm.column_type,
    COUNT(DISTINCT cm.file_id) as frequency,
    
    -- 날짜 범위
    MIN(cm.column_info->>'min_date') as min_date,
    MAX(cm.column_info->>'max_date') as max_date,
    
    -- 샘플 file_id
    (SELECT array_agg(DISTINCT sub.file_id::text)
     FROM (
         SELECT file_id FROM column_metadata 
         WHERE original_name = cm.original_name 
         LIMIT %s
     ) sub
    ) as sample_file_ids

FROM column_metadata cm
WHERE cm.column_type = 'datetime'
GROUP BY cm.original_name, cm.column_type
ORDER BY frequency DESC;
"""

# 전체 유니크 컬럼 집계 (통합 쿼리 - 단순화된 버전)
AGGREGATE_ALL_SQL = """
SELECT 
    cm.original_name,
    cm.column_type,
    COUNT(DISTINCT cm.file_id) as frequency,
    
    -- 통계 (JSON에서 추출)
    AVG((cm.column_info->>'min')::float) as avg_min,
    AVG((cm.column_info->>'max')::float) as avg_max,
    AVG((cm.column_info->>'mean')::float) as avg_mean,
    AVG((cm.column_info->>'unique_count')::float) as avg_unique_count,
    AVG((cm.column_info->>'unique_ratio')::float) as avg_unique_ratio,
    MAX(cm.column_info->>'unit') as sample_unit,
    
    -- 대표 값 분포 (첫 번째 유효값)
    (SELECT sub.value_distribution
     FROM column_metadata sub 
     WHERE sub.original_name = cm.original_name 
       AND sub.value_distribution IS NOT NULL 
       AND sub.value_distribution != '{}'::jsonb
     LIMIT 1
    ) as sample_distribution

FROM column_metadata cm
GROUP BY cm.original_name, cm.column_type
ORDER BY frequency DESC, cm.original_name;
"""


# =============================================================================
# 핵심 함수
# =============================================================================

def aggregate_unique_columns() -> List[Dict[str, Any]]:
    """
    DB에서 유니크 컬럼명과 대표 통계 추출
    
    Returns:
        List of unique columns with aggregated stats
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # 통합 쿼리 실행
        cursor.execute(AGGREGATE_ALL_SQL)
        rows = cursor.fetchall()
        
        # 컬럼명 추출
        col_names = [desc[0] for desc in cursor.description]
        
        unique_columns = []
        for row in rows:
            row_dict = dict(zip(col_names, row))
            
            # 통계 정리
            column_info = {
                "original_name": row_dict["original_name"],
                "column_type": row_dict["column_type"] or "unknown",
                "frequency": row_dict["frequency"] or 0,
            }
            
            # 수치형 통계
            if row_dict.get("avg_min") is not None:
                column_info["avg_min"] = round(row_dict["avg_min"], 2)
            if row_dict.get("avg_max") is not None:
                column_info["avg_max"] = round(row_dict["avg_max"], 2)
            if row_dict.get("avg_mean") is not None:
                column_info["avg_mean"] = round(row_dict["avg_mean"], 2)
            
            # 범주형 통계
            if row_dict.get("avg_unique_count") is not None:
                column_info["avg_unique_count"] = round(row_dict["avg_unique_count"], 1)
            if row_dict.get("avg_unique_ratio") is not None:
                column_info["avg_unique_ratio"] = round(row_dict["avg_unique_ratio"], 3)
            
            # 단위
            if row_dict.get("sample_unit"):
                column_info["sample_unit"] = row_dict["sample_unit"]
            
            # 대표 값 분포 (최대 N개)
            sample_dist = row_dict.get("sample_distribution")
            if sample_dist and isinstance(sample_dist, dict):
                # 상위 N개 값만 추출
                max_samples = Phase3Config.MAX_SAMPLE_VALUES
                top_values = dict(list(sample_dist.items())[:max_samples])
                if top_values:
                    column_info["sample_values"] = top_values
            
            unique_columns.append(column_info)
        
        return unique_columns
        
    except Exception as e:
        print(f"[Aggregator] Error aggregating columns: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()


def prepare_llm_batches(
    unique_columns: List[Dict[str, Any]], 
    batch_size: Optional[int] = None
) -> List[List[Dict[str, Any]]]:
    """
    유니크 컬럼을 배치로 나눔
    
    Args:
        unique_columns: 유니크 컬럼 리스트
        batch_size: 배치당 컬럼 수 (None이면 config에서 가져옴)
    
    Returns:
        List of batches (각 배치는 컬럼 리스트)
    """
    if batch_size is None:
        batch_size = Phase3Config.BATCH_SIZE
    
    batches = []
    for i in range(0, len(unique_columns), batch_size):
        batch = unique_columns[i:i + batch_size]
        batches.append(batch)
    
    return batches


def get_aggregation_stats() -> Dict[str, Any]:
    """
    집계 통계 조회 (디버깅/모니터링용)
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    stats = {}
    
    try:
        # 전체 컬럼 수
        cursor.execute("SELECT COUNT(*) FROM column_metadata")
        stats["total_columns"] = cursor.fetchone()[0]
        
        # 유니크 컬럼 수
        cursor.execute("SELECT COUNT(DISTINCT original_name) FROM column_metadata")
        stats["unique_columns"] = cursor.fetchone()[0]
        
        # column_type별 유니크 수
        cursor.execute("""
            SELECT column_type, COUNT(DISTINCT original_name) 
            FROM column_metadata 
            GROUP BY column_type
        """)
        stats["unique_by_type"] = dict(cursor.fetchall())
        
        # 파일 수
        cursor.execute("SELECT COUNT(*) FROM file_catalog")
        stats["total_files"] = cursor.fetchone()[0]
        
    except Exception as e:
        print(f"[Aggregator] Error getting stats: {e}")
        stats["error"] = str(e)
    
    return stats


# =============================================================================
# LangGraph Node Function
# =============================================================================

def phase3_aggregation_node(state: AgentState) -> Dict[str, Any]:
    """
    Phase 0.5: Schema Aggregation 노드
    
    DB에서 유니크 컬럼과 파일을 집계하고 Phase 1 LLM 배치를 준비합니다.
    
    Input (from state):
        - phase0_file_ids: Phase 0에서 처리된 파일 ID들 (참고용)
    
    Output (to state):
        - phase05_result: 집계 결과 요약
        - unique_columns: 유니크 컬럼 리스트
        - unique_files: 유니크 파일 리스트
        - column_batches: 컬럼 LLM 배치 리스트
        - file_batches: 파일 LLM 배치 리스트
    """
    from src.config import Phase5Config
    
    print("\n" + "=" * 60)
    print("🔄 Phase 3: Schema Aggregation")
    print("=" * 60)
    
    # 1. 집계 통계 조회
    stats = get_aggregation_stats()
    print(f"\n📊 Current DB Stats:")
    print(f"   Total files: {stats.get('total_files', 0):,}")
    print(f"   Total columns: {stats.get('total_columns', 0):,}")
    print(f"   Unique columns: {stats.get('unique_columns', 0):,}")
    
    if stats.get('unique_by_type'):
        print(f"   By type: {stats.get('unique_by_type')}")
    
    # =========================================================================
    # 2. 유니크 컬럼 집계
    # =========================================================================
    print(f"\n🔍 Aggregating unique columns...")
    unique_columns = aggregate_unique_columns()
    print(f"   ✅ Found {len(unique_columns)} unique columns")
    
    # 컬럼 배치 준비
    column_batch_size = Phase5Config.COLUMN_BATCH_SIZE
    column_batches = prepare_llm_batches(unique_columns, column_batch_size)
    print(f"\n📦 Column LLM Batches:")
    print(f"   Batch size: {column_batch_size}")
    print(f"   Total batches: {len(column_batches)}")
    
    # 샘플 출력 (처음 5개 컬럼)
    if unique_columns:
        print(f"\n📝 Sample columns (top 5 by frequency):")
        for col in unique_columns[:5]:
            freq = col.get('frequency', 0)
            col_type = col.get('column_type', 'unknown')
            name = col.get('original_name', '?')
            
            stat_str = ""
            if col.get('avg_min') is not None:
                stat_str = f"range: [{col.get('avg_min'):.1f}, {col.get('avg_max'):.1f}]"
            elif col.get('sample_values'):
                values = list(col['sample_values'].keys())[:3]
                stat_str = f"values: {values}"
            
            print(f"   - {name} ({col_type}, freq={freq}) {stat_str}")
    
    # =========================================================================
    # 3. 파일 집계
    # =========================================================================
    print(f"\n🔍 Aggregating files for semantic analysis...")
    unique_files = aggregate_unique_files()
    print(f"   ✅ Found {len(unique_files)} files to analyze")
    
    # 파일 배치 준비
    file_batch_size = Phase5Config.FILE_BATCH_SIZE
    file_batches = prepare_file_batches(unique_files, file_batch_size)
    print(f"\n📦 File LLM Batches:")
    print(f"   Batch size: {file_batch_size}")
    print(f"   Total batches: {len(file_batches)}")
    
    # 샘플 출력 (처음 5개 파일)
    if unique_files:
        print(f"\n📁 Sample files:")
        for f in unique_files[:5]:
            name = f.get('file_name', '?')
            cols = f.get('column_count', 0)
            ptype = f.get('processor_type', '?')
            print(f"   - {name} ({ptype}, {cols} columns)")
    
    # =========================================================================
    # 4. 결과 구성
    # =========================================================================
    result = {
        "total_columns_in_db": stats.get('total_columns', 0),
        "unique_column_count": len(unique_columns),
        "unique_file_count": len(unique_files),
        "column_batch_size": column_batch_size,
        "file_batch_size": file_batch_size,
        "column_batches": len(column_batches),
        "file_batches": len(file_batches),
        "aggregated_at": datetime.now().isoformat(),
        "stats": stats
    }
    
    print(f"\n✅ Phase 3 Complete!")
    print(f"   → {len(unique_columns)} unique columns → {len(column_batches)} batches")
    print(f"   → {len(unique_files)} files → {len(file_batches)} batches")
    print(f"   → Ready for Phase 4 LLM analysis!")
    print("=" * 60 + "\n")
    
    return {
        "phase3_result": result,
        "unique_columns": unique_columns,
        "unique_files": unique_files,
        "column_batches": column_batches,
        "file_batches": file_batches
    }


# =============================================================================
# 파일 집계 함수 (Phase 1 File Analysis용)
# =============================================================================

AGGREGATE_FILES_SQL = """
SELECT 
    fc.file_id,
    fc.file_name,
    fc.file_extension,
    fc.processor_type,
    fc.file_size_mb,
    fc.file_metadata,
    
    -- 컬럼 정보 요약
    COUNT(cm.col_id) as column_count,
    ARRAY_AGG(DISTINCT cm.original_name) as column_names,
    ARRAY_AGG(DISTINCT cm.column_type) as column_types
    
FROM file_catalog fc
LEFT JOIN column_metadata cm ON fc.file_id = cm.file_id
WHERE fc.semantic_type IS NULL  -- 아직 분석 안 된 파일만
GROUP BY fc.file_id, fc.file_name, fc.file_extension, 
         fc.processor_type, fc.file_size_mb, fc.file_metadata
ORDER BY fc.file_name;
"""


def aggregate_unique_files() -> List[Dict[str, Any]]:
    """
    Phase 1 File Analysis를 위해 파일 정보 집계
    
    Returns:
        List of file info dicts
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(AGGREGATE_FILES_SQL)
        rows = cursor.fetchall()
        
        col_names = [desc[0] for desc in cursor.description]
        
        files = []
        for row in rows:
            row_dict = dict(zip(col_names, row))
            
            file_info = {
                "file_id": str(row_dict["file_id"]),
                "file_name": row_dict["file_name"],
                "file_extension": row_dict["file_extension"],
                "processor_type": row_dict["processor_type"],
                "file_size_mb": float(row_dict["file_size_mb"]) if row_dict["file_size_mb"] else 0,
                "column_count": row_dict["column_count"] or 0,
                "column_names": row_dict["column_names"][:20] if row_dict["column_names"] else [],  # 처음 20개만
                "column_types": list(set(row_dict["column_types"])) if row_dict["column_types"] else []
            }
            
            # file_metadata에서 주요 정보 추출
            metadata = row_dict.get("file_metadata", {}) or {}
            if metadata:
                file_info["row_count"] = metadata.get("row_count")
                file_info["duration_seconds"] = metadata.get("duration_seconds")
            
            files.append(file_info)
        
        return files
        
    except Exception as e:
        print(f"[Aggregator] Error aggregating files: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()


def prepare_file_batches(
    files: List[Dict[str, Any]],
    batch_size: Optional[int] = None
) -> List[List[Dict[str, Any]]]:
    """
    파일을 배치로 나눔
    
    Args:
        files: 파일 정보 리스트
        batch_size: 배치당 파일 수 (None이면 config에서 가져옴)
    """
    from src.config import Phase5Config
    
    if batch_size is None:
        batch_size = Phase5Config.FILE_BATCH_SIZE
    
    batches = []
    for i in range(0, len(files), batch_size):
        batch = files[i:i + batch_size]
        batches.append(batch)
    
    return batches


# =============================================================================
# 편의 함수 (테스트/디버깅용)
# =============================================================================

def run_aggregation(verbose: bool = True) -> Dict[str, Any]:
    """
    Phase 0.5 실행 (독립 실행용)
    
    Returns:
        Dict with unique_columns, batches, and stats
    """
    if verbose:
        print("\n" + "=" * 60)
        print("🔄 Running Schema Aggregation...")
        print("=" * 60)
    
    # 컬럼 집계
    unique_columns = aggregate_unique_columns()
    column_batches = prepare_llm_batches(unique_columns)
    
    # 파일 집계
    unique_files = aggregate_unique_files()
    file_batches = prepare_file_batches(unique_files)
    
    # 통계
    stats = get_aggregation_stats()
    
    result = {
        "unique_columns": unique_columns,
        "column_batches": column_batches,
        "unique_files": unique_files,
        "file_batches": file_batches,
        "stats": stats,
        "unique_column_count": len(unique_columns),
        "unique_file_count": len(unique_files),
        "column_batch_count": len(column_batches),
        "file_batch_count": len(file_batches)
    }
    
    if verbose:
        print(f"\n✅ Aggregation Complete:")
        print(f"   Unique columns: {len(unique_columns)} → {len(column_batches)} batches")
        print(f"   Unique files: {len(unique_files)} → {len(file_batches)} batches")
    
    return result

