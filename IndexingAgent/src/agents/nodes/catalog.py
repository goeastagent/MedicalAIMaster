# src/agents/nodes/catalog.py
"""
Phase 2: File Catalog Node

파일을 순회하며 Processor로 메타데이터를 추출하고 DB에 저장합니다.
LLM 호출 없이 순수하게 규칙 기반으로 데이터 수집만 수행합니다.

저장 테이블:
- file_catalog: 파일 단위 거시적 정보
- column_metadata: 컬럼 단위 미시적 정보
"""

import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.agents.state import AgentState
from src.agents.nodes.common import processors
from src.database import (
    get_db_manager,
    CatalogSchemaManager,
    get_directory_by_path,
)




# 텍스트로 읽을 수 있는 파일 확장자
TEXT_READABLE_EXTENSIONS = {'csv', 'tsv', 'txt', 'json', 'xml', 'xlsx', 'xls'}


# =============================================================================
# 헬퍼 함수
# =============================================================================

def _get_processor(file_path: str):
    """파일에 맞는 Processor 반환"""
    for processor in processors:
        if processor.can_handle(file_path):
            return processor
    return None


def _is_text_readable(file_path: str) -> bool:
    """파일이 텍스트로 읽을 수 있는지 판단"""
    ext = file_path.lower().split('.')[-1]
    return ext in TEXT_READABLE_EXTENSIONS


def _get_file_modified_time(file_path: str) -> Optional[datetime]:
    """파일의 최근 수정 시간 반환"""
    try:
        mtime = os.path.getmtime(file_path)
        return datetime.fromtimestamp(mtime)
    except:
        return None


def _file_exists_in_catalog(file_path: str) -> Optional[str]:
    """
    파일이 이미 카탈로그에 있는지 확인
    
    Returns:
        file_id (UUID string) if exists, None otherwise
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT file_id FROM file_catalog WHERE file_path = %s",
        (file_path,)
    )
    result = cursor.fetchone()
    return str(result[0]) if result else None


def _file_unchanged_in_catalog(file_path: str, modified_time: datetime) -> Optional[str]:
    """
    파일이 카탈로그에 있고 modified_time이 같은지 확인
    
    Returns:
        file_id (UUID string) if unchanged, None otherwise
    """
    db = get_db_manager()
    conn = db.get_connection()
    
    # 이전 트랜잭션 오류 정리
    try:
        conn.rollback()
    except:
        pass
    
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """
            SELECT file_id FROM file_catalog 
            WHERE file_path = %s AND file_modified_at = %s
            """,
            (file_path, modified_time)
        )
        result = cursor.fetchone()
        return str(result[0]) if result else None
    except Exception as e:
        conn.rollback()
        return None


def _extract_file_metadata(metadata: Dict[str, Any], processor_type: str) -> Dict[str, Any]:
    """
    file_catalog.file_metadata에 저장할 요약 정보 추출
    
    원본 전체는 raw_stats에 저장하고, 핵심 정보만 file_metadata에 저장
    """
    file_meta = {}
    
    if processor_type == "tabular":
        file_meta = {
            "row_count": metadata.get("row_count"),
            "column_count": metadata.get("column_count"),
            "quality_summary": metadata.get("quality_summary", {}),
            "column_type_summary": metadata.get("column_type_summary", {}),
            "potential_id_columns": metadata.get("potential_id_columns", []),
            "dtype_distribution": metadata.get("dtype_distribution", {}),
        }
    elif processor_type == "signal":
        file_meta = {
            "duration": metadata.get("duration"),
            "duration_minutes": metadata.get("duration_minutes"),
            "track_count": metadata.get("track_count"),
            "device_count": metadata.get("device_count"),
            "device_names": metadata.get("device_names", []),
            "track_summary": metadata.get("track_summary", {}),
            "sample_rate_summary": metadata.get("sample_rate_summary", {}),
            "recording_info": metadata.get("recording_info", {}),
            "unique_units": metadata.get("unique_units", []),
        }
    
    return file_meta


# =============================================================================
# DB 저장 함수
# =============================================================================

def _get_dir_id_for_file(file_path: str) -> Optional[str]:
    """
    파일 경로에서 디렉토리 경로를 추출하고 dir_id 조회
    
    Returns:
        dir_id (UUID string) if found, None otherwise
    """
    dir_path = os.path.dirname(os.path.abspath(file_path))
    dir_info = get_directory_by_path(dir_path)
    return dir_info.get("dir_id") if dir_info else None


def _insert_file_catalog(file_path: str, metadata: Dict[str, Any]) -> str:
    """
    file_catalog 테이블에 파일 정보 삽입
    
    Returns:
        file_id (UUID string)
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    processor_type = metadata.get("processor_type", "unknown")
    file_meta = _extract_file_metadata(metadata, processor_type)
    is_text_readable = _is_text_readable(file_path)
    file_modified_at = _get_file_modified_time(file_path)
    
    # Phase 1에서 생성된 dir_id 조회
    dir_id = _get_dir_id_for_file(file_path)
    
    cursor.execute("""
        INSERT INTO file_catalog (
            file_path, file_name, file_extension, 
            file_size_bytes, file_size_mb, file_modified_at,
            processor_type, is_text_readable, file_metadata, raw_stats,
            dir_id
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (file_path) DO UPDATE SET
            file_name = EXCLUDED.file_name,
            file_extension = EXCLUDED.file_extension,
            file_size_bytes = EXCLUDED.file_size_bytes,
            file_size_mb = EXCLUDED.file_size_mb,
            file_modified_at = EXCLUDED.file_modified_at,
            processor_type = EXCLUDED.processor_type,
            is_text_readable = EXCLUDED.is_text_readable,
            file_metadata = EXCLUDED.file_metadata,
            raw_stats = EXCLUDED.raw_stats,
            dir_id = EXCLUDED.dir_id
        RETURNING file_id
    """, (
        file_path,
        metadata.get("file_name") or os.path.basename(file_path),
        metadata.get("file_extension") or file_path.split('.')[-1].lower(),
        metadata.get("file_size_bytes"),
        metadata.get("file_size_mb"),
        file_modified_at,
        processor_type,
        is_text_readable,
        json.dumps(file_meta),
        json.dumps(metadata),  # 원본 전체 백업
        dir_id  # Phase 1에서 생성된 dir_id
    ))
    
    file_id = cursor.fetchone()[0]
    return str(file_id)  # UUID를 문자열로 반환


def _insert_column_metadata(
    file_id: str, 
    column_details: List[Dict[str, Any]],
    processor_type: str
) -> int:
    """
    column_metadata 테이블에 컬럼 정보 삽입
    
    Returns:
        삽입된 컬럼 수
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # 기존 컬럼 삭제 (업데이트 시)
    cursor.execute(
        "DELETE FROM column_metadata WHERE file_id = %s",
        (file_id,)
    )
    
    inserted = 0
    
    for col in column_details:
        # Tabular: column_details가 list
        # Signal: column_details가 dict (track_name -> info)
        if isinstance(col, dict):
            col_name = col.get("column_name") or col.get("original_name", "unknown")
            col_type = col.get("column_type", "unknown")
            data_type = col.get("dtype") or col.get("data_type", "")
            
            # column_info: 핵심 정보만 추출
            column_info = {
                "unit": col.get("unit"),
                "sample_rate": col.get("sample_rate"),
                "null_ratio": col.get("null_ratio"),
                "unique_ratio": col.get("unique_ratio"),
                "is_potential_id": col.get("is_potential_id"),
            }
            
            # 통계 정보 추가 (continuous)
            if col_type == "continuous":
                column_info.update({
                    "min": col.get("min"),
                    "max": col.get("max"),
                    "mean": col.get("mean"),
                    "std": col.get("std"),
                    "median": col.get("median"),
                    "quartiles": col.get("quartiles"),
                })
            
            # Signal 전용 정보
            if processor_type == "signal":
                column_info.update({
                    "device_name": col.get("device_name"),
                    "track_type": col.get("track_type"),
                    "display_range": col.get("display_range"),
                    "scaling": col.get("scaling"),
                    "monitor_type": col.get("monitor_type"),
                })
            
            # Text 통계 (있는 경우)
            if col.get("text_stats"):
                column_info["text_stats"] = col.get("text_stats")
            
            # Datetime 정보 (있는 경우)
            if col.get("is_datetime"):
                column_info.update({
                    "is_datetime": True,
                    "min_date": col.get("min_date"),
                    "max_date": col.get("max_date"),
                    "date_range_days": col.get("date_range_days"),
                })
            
            # value_distribution: unique values, value_counts
            value_distribution = {}
            if col.get("unique_values"):
                value_distribution["unique_values"] = col.get("unique_values")
            if col.get("value_counts"):
                value_distribution["value_counts"] = col.get("value_counts")
            if col.get("samples"):
                value_distribution["samples"] = col.get("samples")
            
            # None 값 필터링
            column_info = {k: v for k, v in column_info.items() if v is not None}
            
            cursor.execute("""
                INSERT INTO column_metadata (
                    file_id, original_name, column_type, data_type,
                    column_info, value_distribution
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (file_id, original_name) DO UPDATE SET
                    column_type = EXCLUDED.column_type,
                    data_type = EXCLUDED.data_type,
                    column_info = EXCLUDED.column_info,
                    value_distribution = EXCLUDED.value_distribution,
                    updated_at = NOW()
            """, (
                file_id,
                col_name,
                col_type,
                data_type,
                json.dumps(column_info),
                json.dumps(value_distribution)
            ))
            
            inserted += 1
    
    return inserted


# =============================================================================
# 스키마 관리 함수
# =============================================================================

def ensure_schema():
    """스키마가 없으면 생성"""
    db = get_db_manager()
    schema_manager = CatalogSchemaManager(db)
    
    # 이전 트랜잭션 오류 상태 정리
    try:
        conn = db.get_connection()
        conn.rollback()
    except:
        pass
    
    if not schema_manager.table_exists('file_catalog'):
        schema_manager.create_tables()


# =============================================================================
# 파일 처리 함수
# =============================================================================

def process_single_file(file_path: str, skip_unchanged: bool = True, verbose: bool = True) -> Dict[str, Any]:
    """
    단일 파일 처리
    
    Args:
        file_path: 처리할 파일 경로
        skip_unchanged: True면 file_path + modified_time이 같은 파일 스킵
        verbose: True면 진행 상황 출력
    
    Returns:
        결과 딕셔너리 {file_path, success, file_id, column_count, error, skipped}
    """
    # 파일 경로 정규화 (절대 경로로 변환)
    file_path = os.path.abspath(file_path)
    filename = os.path.basename(file_path)
    
    # 파일 수정 시간 확인
    file_modified_at = _get_file_modified_time(file_path)
    
    # 변경되지 않은 파일 스킵 (file_path + modified_time 기준)
    if skip_unchanged and file_modified_at:
        existing_id = _file_unchanged_in_catalog(file_path, file_modified_at)
        if existing_id:
            short_id = existing_id[:8]  # UUID 앞 8자리만 표시
            if verbose:
                print(f"   ⏭️ [{short_id}] {filename} (skipped: unchanged)")
            return {
                "file_path": file_path,
                "success": True,
                "file_id": existing_id,
                "column_count": 0,
                "error": None,
                "skipped": True
            }
    
    # Processor 선택
    processor = _get_processor(file_path)
    if not processor:
        if verbose:
            print(f"   ❌ [--------] {filename} (no processor)")
        return {
            "file_path": file_path,
            "success": False,
            "file_id": None,
            "column_count": 0,
            "error": f"No processor available for file: {file_path}",
            "skipped": False
        }
    
    db = get_db_manager()
    
    try:
        # 1. 메타데이터 추출
        metadata = processor.extract_metadata(file_path)
        
        if "error" in metadata:
            if verbose:
                print(f"   ❌ [--------] {filename} ({metadata['error']})")
            return {
                "file_path": file_path,
                "success": False,
                "file_id": None,
                "column_count": 0,
                "error": metadata["error"],
                "skipped": False
            }
        
        # 2. file_catalog에 저장
        file_id = _insert_file_catalog(file_path, metadata)
        
        # 3. column_metadata에 저장
        processor_type = metadata.get("processor_type", "unknown")
        column_details = metadata.get("column_details", [])
        
        # Signal의 경우 dict를 list로 변환
        if isinstance(column_details, dict):
            column_details = list(column_details.values())
        
        column_count = _insert_column_metadata(file_id, column_details, processor_type)
        
        # 4. 커밋
        db.commit()
        
        # 5. file_id 출력 (UUID 앞 8자리)
        short_id = file_id[:8]
        if verbose:
            print(f"   ✅ [{short_id}] {filename} ({column_count} columns)")
        
        return {
            "file_path": file_path,
            "success": True,
            "file_id": file_id,
            "column_count": column_count,
            "error": None,
            "skipped": False
        }
        
    except Exception as e:
        db.get_connection().rollback()
        if verbose:
            print(f"   ❌ [--------] {filename} ({str(e)})")
        return {
            "file_path": file_path,
            "success": False,
            "file_id": None,
            "column_count": 0,
            "error": str(e),
            "skipped": False
        }


def process_files(
    file_paths: List[str], 
    skip_unchanged: bool = True,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    여러 파일 배치 처리
    
    Args:
        file_paths: 처리할 파일 경로 리스트
        skip_unchanged: True면 file_path + modified_time이 같은 파일 스킵
        verbose: True면 진행 상황 출력
    
    Returns:
        Phase 2 결과 딕셔너리 (file_ids 포함)
    """
    ensure_schema()
    
    total_files = len(file_paths)
    processed_files = 0
    skipped_files = 0
    failed_files = 0
    results = []
    file_ids = []  # 모든 파일의 file_id 수집
    
    for i, file_path in enumerate(file_paths):
        if verbose and (i + 1) % 100 == 0:
            print(f"[Phase 2] Processing {i + 1}/{total_files}...")
        
        file_result = process_single_file(file_path, skip_unchanged, verbose)
        results.append(file_result)
        
        # file_id 수집 (성공한 파일만)
        if file_result.get("file_id"):
            file_ids.append(file_result["file_id"])
        
        if file_result["success"]:
            if file_result.get("skipped"):
                skipped_files += 1
            else:
                processed_files += 1
        else:
            failed_files += 1
    
    if verbose:
        print(f"[Phase 2] Complete: {processed_files} processed, "
              f"{skipped_files} skipped, {failed_files} failed")
    
    success_rate = f"{(processed_files + skipped_files) / total_files * 100:.1f}%" if total_files > 0 else "0%"
    
    return {
        "total_files": total_files,
        "processed_files": processed_files,
        "skipped_files": skipped_files,
        "failed_files": failed_files,
        "success_rate": success_rate,
        "file_ids": file_ids,  # 모든 파일의 file_id
        "results": results
    }


def process_directory(
    directory: str, 
    recursive: bool = True,
    skip_unchanged: bool = True,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    디렉토리 내 모든 파일 처리
    
    Args:
        directory: 처리할 디렉토리 경로
        recursive: True면 하위 디렉토리도 처리
        skip_unchanged: True면 file_path + modified_time이 같은 파일 스킵
        verbose: True면 진행 상황 출력
    
    Returns:
        Phase 2 결과 딕셔너리
    """
    file_paths = []
    
    if recursive:
        for root, dirs, files in os.walk(directory):
            for f in files:
                file_path = os.path.join(root, f)
                if _get_processor(file_path):
                    file_paths.append(file_path)
    else:
        for f in os.listdir(directory):
            file_path = os.path.join(directory, f)
            if os.path.isfile(file_path) and _get_processor(file_path):
                file_paths.append(file_path)
    
    if verbose:
        print(f"[Phase 2] Found {len(file_paths)} processable files in {directory}")
    
    return process_files(file_paths, skip_unchanged, verbose)


# =============================================================================
# 편의 함수
# =============================================================================

def run_phase2(
    directory: str = None,
    file_paths: List[str] = None,
    recursive: bool = True,
    skip_unchanged: bool = True,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Phase 2 실행 - 편의 함수
    
    Args:
        directory: 처리할 디렉토리 (file_paths가 없을 때)
        file_paths: 처리할 파일 경로 리스트 (우선)
        recursive: True면 하위 디렉토리도 처리
        skip_unchanged: True면 file_path + modified_time이 같은 파일 스킵
        verbose: True면 진행 상황 출력
    
    Returns:
        Phase 2 결과 딕셔너리 (file_ids 포함)
    """
    if file_paths:
        return process_files(file_paths, skip_unchanged, verbose)
    elif directory:
        return process_directory(directory, recursive, skip_unchanged, verbose)
    else:
        raise ValueError("Either directory or file_paths must be provided")


def get_catalog_stats() -> dict:
    """카탈로그 통계 조회"""
    db = get_db_manager()
    schema_manager = CatalogSchemaManager(db)
    return schema_manager.get_stats()


# =============================================================================
# LangGraph Node Function
# =============================================================================

def phase2_file_catalog_node(state: AgentState) -> Dict[str, Any]:
    """
    [Phase 2] File Catalog 노드 - LangGraph용
    
    모든 입력 파일의 메타데이터를 추출하여 DB에 저장합니다.
    LLM 호출 없이 순수하게 규칙 기반으로 데이터 수집만 수행합니다.
    
    - file_path + modified_time이 같으면 스킵
    - 모든 파일의 file_id를 state에 반환
    
    Args:
        state: AgentState (input_files 필드 필요)
    
    Returns:
        업데이트된 상태 (phase2_result, phase2_file_ids, logs)
    """
    print("\n" + "="*80)
    print("📦 [PHASE 2] File Catalog - 메타데이터 추출 시작")
    print("="*80)
    
    input_files = state.get("input_files", [])
    
    if not input_files:
        return {
            "logs": ["❌ [Phase 2] Error: 입력 파일이 없습니다."],
            "phase2_result": {
                "total_files": 0,
                "processed_files": 0,
                "skipped_files": 0,
                "failed_files": 0,
                "success_rate": "0%",
                "file_ids": [],
                "results": []
            },
            "phase2_file_ids": [],
            "error_message": "No input files provided"
        }
    
    print(f"   📂 처리할 파일: {len(input_files)}개\n")
    
    # Phase 2 실행 (변경되지 않은 파일은 스킵)
    result = process_files(
        file_paths=input_files,
        skip_unchanged=True,  # file_path + modified_time이 같으면 스킵
        verbose=True
    )
    
    # 모든 파일의 file_id (처리 + 스킵 포함)
    file_ids = result.get("file_ids", [])
    
    # 로그 생성
    logs = [
        f"📦 [Phase 2] 완료: {result['processed_files']}개 처리, {result['skipped_files']}개 스킵"
    ]
    
    if file_ids:
        # UUID 앞 8자리만 표시
        short_ids = [fid[:8] for fid in file_ids]
        logs.append(f"   📋 File IDs: {short_ids}")
    
    if result["failed_files"] > 0:
        logs.append(f"   ⚠️ 실패: {result['failed_files']}개")
        for r in result["results"]:
            if not r["success"]:
                logs.append(f"      - {os.path.basename(r['file_path'])}: {r['error']}")
    
    print(f"\n✅ [Phase 2] 완료: {result['processed_files']}개 처리, {result['skipped_files']}개 스킵, {result['failed_files']}개 실패")
    if file_ids:
        short_ids = [fid[:8] for fid in file_ids]
        print(f"   📋 File IDs: {short_ids}")
    
    return {
        "logs": logs,
        "phase2_result": result,
        "phase2_file_ids": file_ids  # 모든 파일의 file_id를 state에 저장
    }


# =============================================================================
# Class-based Node (for NodeRegistry)
# =============================================================================

from ..base import BaseNode, DatabaseMixin
from ..registry import register_node


@register_node
class FileCatalogNode(BaseNode, DatabaseMixin):
    """
    File Catalog Node (Rule-based)
    
    파일을 순회하며 Processor로 메타데이터를 추출하고 DB에 저장합니다.
    LLM 호출 없이 순수하게 규칙 기반으로 데이터 수집만 수행합니다.
    """
    
    name = "file_catalog"
    description = "파일 메타데이터 추출 및 DB 저장"
    order = 200
    requires_llm = False
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """기존 함수 위임"""
        return phase2_file_catalog_node(state)
