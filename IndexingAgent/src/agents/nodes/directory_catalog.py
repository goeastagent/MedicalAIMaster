# src/agents/nodes/directory_catalog.py
"""
Phase 1: Directory Catalog Node

디렉토리 레벨 메타데이터를 수집하여 DB에 저장합니다.
LLM 호출 없이 순수하게 규칙 기반으로 데이터 수집만 수행합니다.

저장 테이블:
- directory_catalog: 디렉토리 단위 메타데이터

수집 정보:
- 디렉토리 계층 구조 (parent_dir_id)
- 파일 확장자별 카운트
- 파일명 샘플 (LLM 분석용, Phase 7에서 사용)
- 총 파일 크기
"""

import os
import fnmatch
from typing import Dict, Any, List, Optional, Set
from collections import defaultdict
from datetime import datetime

from src.agents.state import AgentState
from src.database.connection import get_db_manager
from src.database.schema_directory import (
    DirectorySchemaManager,
    insert_directory,
    get_directory_by_path,
    update_file_catalog_dir_ids,
)
from src.config import Phase1Config




# =============================================================================
# 헬퍼 함수: 파일 필터링
# =============================================================================

def _should_ignore_dir(dir_name: str) -> bool:
    """무시해야 할 디렉토리인지 확인"""
    return dir_name in Phase1Config.IGNORE_DIRS or dir_name.startswith('.')


def _should_ignore_file(filename: str) -> bool:
    """무시해야 할 파일인지 확인"""
    for pattern in Phase1Config.IGNORE_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False


def _get_file_extension(filename: str) -> str:
    """파일 확장자 추출 (소문자)"""
    ext = os.path.splitext(filename)[1].lower()
    return ext[1:] if ext.startswith('.') else ext


# =============================================================================
# 헬퍼 함수: 디렉토리 스캔
# =============================================================================

def _scan_directory(dir_path: str) -> Dict[str, Any]:
    """
    단일 디렉토리 스캔 (재귀하지 않음, 직계 자식만)
    
    Returns:
        {
            "dir_path": "/path/to/dir",
            "dir_name": "vital_files",
            "file_count": 6388,
            "file_extensions": {"vital": 6388},
            "total_size_bytes": 123456789,
            "files": ["0001.vital", "0002.vital", ...],
            "subdirs": ["subdir1", "subdir2"]
        }
    """
    dir_path = os.path.abspath(dir_path)
    dir_name = os.path.basename(dir_path)
    
    file_extensions: Dict[str, int] = defaultdict(int)
    total_size_bytes = 0
    files: List[str] = []
    subdirs: List[str] = []
    
    try:
        entries = os.listdir(dir_path)
    except PermissionError:
        print(f"   ⚠️ Permission denied: {dir_path}")
        return {
            "dir_path": dir_path,
            "dir_name": dir_name,
            "file_count": 0,
            "file_extensions": {},
            "total_size_bytes": 0,
            "files": [],
            "subdirs": [],
            "error": "Permission denied"
        }
    
    for entry in entries:
        entry_path = os.path.join(dir_path, entry)
        
        if os.path.isdir(entry_path):
            if not _should_ignore_dir(entry):
                subdirs.append(entry)
        elif os.path.isfile(entry_path):
            if not _should_ignore_file(entry):
                files.append(entry)
                ext = _get_file_extension(entry)
                if ext:
                    file_extensions[ext] += 1
                try:
                    total_size_bytes += os.path.getsize(entry_path)
                except OSError:
                    pass
    
    return {
        "dir_path": dir_path,
        "dir_name": dir_name,
        "file_count": len(files),
        "file_extensions": dict(file_extensions),
        "total_size_bytes": total_size_bytes,
        "files": files,
        "subdirs": subdirs
    }


def _collect_filename_samples(
    files: List[str], 
    max_samples: int = None
) -> List[str]:
    """
    파일명 샘플 수집 (다양한 샘플 확보)
    
    전략 (diverse):
    - 처음 N개: 시작 패턴 확인
    - 마지막 N개: 끝 패턴 확인  
    - 중간 균등 분포: 전체 패턴 확인
    
    Returns:
        샘플 파일명 리스트
    """
    if max_samples is None:
        max_samples = Phase1Config.FILENAME_SAMPLE_SIZE
    
    if len(files) <= max_samples:
        return sorted(files)
    
    strategy = Phase1Config.SAMPLE_STRATEGY
    
    if strategy == "first":
        return sorted(files[:max_samples])
    
    elif strategy == "random":
        import random
        return sorted(random.sample(files, max_samples))
    
    else:  # diverse (default)
        sorted_files = sorted(files)
        samples = []
        
        # 처음 N개
        first_n = max_samples // 4
        samples.extend(sorted_files[:first_n])
        
        # 마지막 N개
        last_n = max_samples // 4
        samples.extend(sorted_files[-last_n:])
        
        # 중간 균등 분포
        middle_n = max_samples - first_n - last_n
        middle_files = sorted_files[first_n:-last_n] if last_n > 0 else sorted_files[first_n:]
        
        if middle_files and middle_n > 0:
            step = max(1, len(middle_files) // middle_n)
            for i in range(0, len(middle_files), step):
                if len(samples) >= max_samples:
                    break
                if middle_files[i] not in samples:
                    samples.append(middle_files[i])
        
        return sorted(set(samples))


def _classify_directory_type(file_extensions: Dict[str, int]) -> Optional[str]:
    """
    파일 확장자 분포에 따라 디렉토리 타입 분류
    
    Returns:
        "signal_files", "tabular_files", "metadata_files", "mixed", or None
    """
    if not file_extensions:
        return None
    
    total_files = sum(file_extensions.values())
    if total_files == 0:
        return None
    
    threshold = Phase1Config.TYPE_CLASSIFICATION_THRESHOLD
    
    # 각 타입별 파일 수 계산
    signal_count = sum(
        count for ext, count in file_extensions.items() 
        if ext in Phase1Config.SIGNAL_EXTENSIONS
    )
    tabular_count = sum(
        count for ext, count in file_extensions.items() 
        if ext in Phase1Config.TABULAR_EXTENSIONS
    )
    metadata_count = sum(
        count for ext, count in file_extensions.items() 
        if ext in Phase1Config.METADATA_EXTENSIONS
    )
    
    # 비율 기반 분류
    if signal_count / total_files >= threshold:
        return "signal_files"
    elif tabular_count / total_files >= threshold:
        return "tabular_files"
    elif metadata_count / total_files >= threshold:
        return "metadata_files"
    else:
        return "mixed"


# =============================================================================
# 메인 처리 함수
# =============================================================================

def process_directory_tree(
    root_path: str,
    recursive: bool = True,
    skip_unchanged: bool = True,
    verbose: bool = True,
    current_depth: int = 0,
    parent_dir_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    디렉토리 트리 처리 (재귀)
    
    Args:
        root_path: 루트 디렉토리 경로
        recursive: 하위 디렉토리 포함 여부
        skip_unchanged: 변경되지 않은 디렉토리 스킵 (현재 미구현)
        verbose: 진행 상황 출력
        current_depth: 현재 깊이 (내부 사용)
        parent_dir_id: 부모 디렉토리 ID (내부 사용)
    
    Returns:
        {
            "total_dirs": 5,
            "processed_dirs": 3,
            "skipped_dirs": 2,
            "total_files": 6391,
            "dir_ids": ["uuid1", "uuid2", ...]
        }
    """
    root_path = os.path.abspath(root_path)
    
    # 깊이 제한 체크
    if current_depth > Phase1Config.MAX_DEPTH:
        if verbose:
            print(f"   ⚠️ Max depth reached: {root_path}")
        return {
            "total_dirs": 0,
            "processed_dirs": 0,
            "skipped_dirs": 0,
            "total_files": 0,
            "dir_ids": []
        }
    
    # 디렉토리 스캔
    dir_info = _scan_directory(root_path)
    
    if "error" in dir_info:
        return {
            "total_dirs": 0,
            "processed_dirs": 0,
            "skipped_dirs": 0,
            "total_files": 0,
            "dir_ids": [],
            "error": dir_info["error"]
        }
    
    # 파일명 샘플 수집
    filename_samples = _collect_filename_samples(dir_info["files"])
    
    # 디렉토리 타입 분류
    dir_type = _classify_directory_type(dir_info["file_extensions"])
    
    # DB 저장
    try:
        dir_id = insert_directory(
            dir_path=dir_info["dir_path"],
            dir_name=dir_info["dir_name"],
            parent_dir_id=parent_dir_id,
            file_count=dir_info["file_count"],
            file_extensions=dir_info["file_extensions"],
            total_size_bytes=dir_info["total_size_bytes"],
            subdir_count=len(dir_info["subdirs"]),
            filename_samples=filename_samples
        )
        
        # dir_type 업데이트 (별도 쿼리)
        if dir_type:
            db = get_db_manager()
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE directory_catalog SET dir_type = %s WHERE dir_id = %s",
                (dir_type, dir_id)
            )
            conn.commit()
        
        if verbose:
            short_id = dir_id[:8]
            type_str = f" [{dir_type}]" if dir_type else ""
            print(f"   ✅ [{short_id}] {dir_info['dir_name']}{type_str} ({dir_info['file_count']} files, {len(dir_info['subdirs'])} subdirs)")
        
    except Exception as e:
        if verbose:
            print(f"   ❌ Error processing {dir_info['dir_name']}: {e}")
        return {
            "total_dirs": 1,
            "processed_dirs": 0,
            "skipped_dirs": 0,
            "total_files": dir_info["file_count"],
            "dir_ids": [],
            "error": str(e)
        }
    
    # 결과 집계
    result = {
        "total_dirs": 1,
        "processed_dirs": 1,
        "skipped_dirs": 0,
        "total_files": dir_info["file_count"],
        "dir_ids": [dir_id]
    }
    
    # 재귀 처리 (하위 디렉토리)
    if recursive and dir_info["subdirs"]:
        for subdir_name in sorted(dir_info["subdirs"]):
            subdir_path = os.path.join(root_path, subdir_name)
            
            sub_result = process_directory_tree(
                root_path=subdir_path,
                recursive=True,
                skip_unchanged=skip_unchanged,
                verbose=verbose,
                current_depth=current_depth + 1,
                parent_dir_id=dir_id
            )
            
            result["total_dirs"] += sub_result["total_dirs"]
            result["processed_dirs"] += sub_result["processed_dirs"]
            result["skipped_dirs"] += sub_result["skipped_dirs"]
            result["total_files"] += sub_result["total_files"]
            result["dir_ids"].extend(sub_result["dir_ids"])
    
    return result


def _find_common_parent_directory(file_paths: List[str]) -> Optional[str]:
    """
    파일 경로 리스트에서 공통 상위 디렉토리 추출
    
    Returns:
        공통 상위 디렉토리 경로 또는 None
    """
    if not file_paths:
        return None
    
    # 모든 파일의 디렉토리 경로 추출
    dir_paths = [os.path.dirname(os.path.abspath(f)) for f in file_paths]
    
    # 고유한 디렉토리만
    unique_dirs = set(dir_paths)
    
    if len(unique_dirs) == 1:
        # 모든 파일이 같은 디렉토리에 있음
        return unique_dirs.pop()
    
    # 공통 접두사 찾기
    common = os.path.commonpath(list(unique_dirs))
    return common if common else None


# =============================================================================
# 스키마 관리 함수
# =============================================================================

def ensure_schema():
    """스키마가 없으면 생성"""
    schema_manager = DirectorySchemaManager()
    
    if not schema_manager.table_exists('directory_catalog'):
        schema_manager.create_tables()


# =============================================================================
# LangGraph Node Function
# =============================================================================

def phase1_directory_catalog_node(state: AgentState) -> Dict[str, Any]:
    """
    [Phase 1] Directory Catalog 노드 - LangGraph용
    
    입력 디렉토리의 구조를 분석하여 DB에 저장합니다.
    LLM 호출 없이 순수하게 규칙 기반으로 데이터 수집만 수행합니다.
    
    수집 정보:
    - 디렉토리 계층 구조
    - 파일 확장자별 카운트
    - 파일명 샘플 (Phase 7에서 LLM이 분석)
    - 파일 크기 통계
    
    Args:
        state: AgentState (input_directory 또는 input_files 필드 필요)
    
    Returns:
        업데이트된 상태:
        - phase_neg1_result: 처리 결과
        - phase_neg1_dir_ids: 생성된 dir_id 목록
        - logs: 로그 메시지
    """
    print("\n" + "="*80)
    print("📁 [PHASE 1] Directory Catalog - 디렉토리 구조 분석 시작")
    print("="*80)
    
    started_at = datetime.now().isoformat()
    
    # 입력 디렉토리 결정
    input_directory = state.get("input_directory")
    input_files = state.get("input_files", [])
    
    if not input_directory and input_files:
        # input_files에서 공통 상위 디렉토리 추출
        input_directory = _find_common_parent_directory(input_files)
        if input_directory:
            print(f"   📂 Inferred directory from input_files: {input_directory}")
    
    if not input_directory:
        error_msg = "No input directory provided"
        print(f"   ❌ {error_msg}")
        return {
            "logs": [f"❌ [Phase 1] Error: {error_msg}"],
            "phase1_result": {
                "total_dirs": 0,
                "processed_dirs": 0,
                "skipped_dirs": 0,
                "total_files": 0,
                "dir_ids": [],
                "started_at": started_at,
                "completed_at": datetime.now().isoformat(),
                "error": error_msg
            },
            "phase1_dir_ids": [],
            "error_message": error_msg
        }
    
    # 디렉토리 존재 확인
    if not os.path.isdir(input_directory):
        error_msg = f"Directory not found: {input_directory}"
        print(f"   ❌ {error_msg}")
        return {
            "logs": [f"❌ [Phase 1] Error: {error_msg}"],
            "phase1_result": {
                "total_dirs": 0,
                "processed_dirs": 0,
                "skipped_dirs": 0,
                "total_files": 0,
                "dir_ids": [],
                "started_at": started_at,
                "completed_at": datetime.now().isoformat(),
                "error": error_msg
            },
            "phase1_dir_ids": [],
            "error_message": error_msg
        }
    
    print(f"   📂 Input directory: {input_directory}\n")
    
    # 스키마 확인/생성
    ensure_schema()
    
    # 디렉토리 트리 처리
    result = process_directory_tree(
        root_path=input_directory,
        recursive=True,
        skip_unchanged=True,
        verbose=True
    )
    
    completed_at = datetime.now().isoformat()
    
    # 결과에 시간 정보 추가
    result["started_at"] = started_at
    result["completed_at"] = completed_at
    
    # 로그 생성
    logs = [
        f"📁 [Phase 1] 완료: {result['processed_dirs']}개 디렉토리 처리, "
        f"{result['total_files']}개 파일 탐지"
    ]
    
    if result.get("dir_ids"):
        short_ids = [did[:8] for did in result["dir_ids"][:5]]
        if len(result["dir_ids"]) > 5:
            short_ids.append(f"... (+{len(result['dir_ids']) - 5})")
        logs.append(f"   📋 Dir IDs: {short_ids}")
    
    if result.get("error"):
        logs.append(f"   ⚠️ Error: {result['error']}")
    
    # 요약 출력
    print(f"\n✅ [Phase 1] 완료:")
    print(f"   📊 총 디렉토리: {result['total_dirs']}개")
    print(f"   ✅ 처리 완료: {result['processed_dirs']}개")
    print(f"   📄 총 파일: {result['total_files']}개")
    
    return {
        "logs": logs,
        "phase1_result": result,
        "phase1_dir_ids": result.get("dir_ids", [])
    }


# =============================================================================
# 편의 함수
# =============================================================================

def run_phase_neg1(
    directory: str,
    recursive: bool = True,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Phase 1 직접 실행 (테스트/디버깅용)
    
    Args:
        directory: 처리할 디렉토리 경로
        recursive: 하위 디렉토리 포함 여부
        verbose: 진행 상황 출력
    
    Returns:
        처리 결과 딕셔너리
    """
    ensure_schema()
    
    if verbose:
        print(f"[Phase 1] Processing directory: {directory}")
    
    return process_directory_tree(
        root_path=directory,
        recursive=recursive,
        skip_unchanged=True,
        verbose=verbose
    )


def get_directory_catalog_stats() -> dict:
    """directory_catalog 통계 조회"""
    schema_manager = DirectorySchemaManager()
    return schema_manager.get_stats()

