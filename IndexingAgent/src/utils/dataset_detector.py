# src/utils/dataset_detector.py
"""
Dataset-First Architecture: 데이터셋 자동 감지 및 관리

파일 경로에서 데이터셋 정보를 자동으로 추출합니다.
"""

import os
import re
from typing import Optional, Dict, Any
from datetime import datetime


def detect_dataset_from_path(file_path: str) -> Optional[str]:
    """
    파일 경로에서 데이터셋 ID 자동 추출
    
    지원하는 경로 패턴:
    - /data/raw/{DATASET_NAME}/file.csv
    - /data/{DATASET_NAME}/file.csv
    - /{any_path}/{DATASET_NAME_VERSION}/file.csv
    
    Args:
        file_path: 파일 경로
    
    Returns:
        데이터셋 ID (예: "inspire_130k_v1.3") 또는 None
    
    Examples:
        >>> detect_dataset_from_path("/data/raw/INSPIRE_130K_1.3/clinical_data.csv")
        'inspire_130k_v1.3'
        >>> detect_dataset_from_path("/data/raw/Open_VitalDB_1.0.0/vital_signs.csv")
        'open_vitaldb_v1.0.0'
    """
    path_parts = file_path.replace("\\", "/").split("/")
    
    # 'raw' 다음 폴더를 데이터셋으로 간주
    try:
        if "raw" in path_parts:
            raw_idx = path_parts.index("raw")
            if raw_idx + 1 < len(path_parts):
                dataset_folder = path_parts[raw_idx + 1]
                return _parse_dataset_folder(dataset_folder)
    except (ValueError, IndexError):
        pass
    
    # 'data' 다음 폴더를 데이터셋으로 간주 (raw가 없는 경우)
    try:
        if "data" in path_parts:
            data_idx = path_parts.index("data")
            # raw가 바로 다음이면 그 다음, 아니면 data 다음
            next_idx = data_idx + 1
            if next_idx < len(path_parts):
                if path_parts[next_idx] == "raw" and next_idx + 1 < len(path_parts):
                    dataset_folder = path_parts[next_idx + 1]
                else:
                    dataset_folder = path_parts[next_idx]
                return _parse_dataset_folder(dataset_folder)
    except (ValueError, IndexError):
        pass
    
    # 마지막 디렉토리 이름에서 버전 패턴 찾기
    for part in reversed(path_parts[:-1]):  # 파일명 제외
        if _looks_like_dataset_folder(part):
            return _parse_dataset_folder(part)
    
    return None


def _parse_dataset_folder(folder_name: str) -> str:
    """
    폴더명을 데이터셋 ID로 파싱
    
    Examples:
        'INSPIRE_130K_1.3' -> 'inspire_130k_v1.3'
        'Open_VitalDB_1.0.0' -> 'open_vitaldb_v1.0.0'
        'my_dataset' -> 'my_dataset_vlatest'
    """
    # 소문자로 변환
    name = folder_name.lower()
    
    # 버전 번호 추출 (마지막 숫자.숫자 패턴)
    # 예: INSPIRE_130K_1.3 -> ["inspire", "130k", "1.3"]
    version_pattern = r'[_\-]?(\d+\.\d+\.?\d*)$'
    version_match = re.search(version_pattern, name)
    
    if version_match:
        version = version_match.group(1)
        name_without_version = name[:version_match.start()]
        # 트레일링 언더스코어/하이픈 제거
        name_without_version = name_without_version.rstrip('_-')
        return f"{name_without_version}_v{version}"
    else:
        # 버전이 없으면 'latest'
        return f"{name}_vlatest"


def _looks_like_dataset_folder(name: str) -> bool:
    """폴더명이 데이터셋처럼 보이는지 확인"""
    # 최소 길이
    if len(name) < 3:
        return False
    
    # 일반적인 시스템 폴더 제외
    system_folders = {
        'bin', 'lib', 'usr', 'etc', 'var', 'tmp', 'home', 'root',
        'users', 'applications', 'program files', 'windows', 'system',
        'node_modules', 'venv', '.git', '__pycache__', 'cache'
    }
    if name.lower() in system_folders:
        return False
    
    # 버전 패턴이 있으면 높은 확률로 데이터셋
    if re.search(r'\d+\.\d+', name):
        return True
    
    # 언더스코어나 하이픈으로 구분된 이름
    if '_' in name or '-' in name:
        return True
    
    return False


def create_dataset_info(
    dataset_id: str,
    source_path: str,
    master_anchor: Optional[str] = None
) -> Dict[str, Any]:
    """
    새 데이터셋 정보 객체 생성
    
    Args:
        dataset_id: 데이터셋 ID
        source_path: 원본 데이터 경로
        master_anchor: Master Anchor 컬럼명 (선택)
    
    Returns:
        DatasetInfo 딕셔너리
    """
    # 버전 추출
    version = "latest"
    if "_v" in dataset_id:
        version = dataset_id.split("_v")[-1]
    
    # 표시명 생성 (ID를 읽기 좋게)
    display_name = dataset_id.replace("_v", " v").replace("_", " ").title()
    
    return {
        "dataset_id": dataset_id,
        "dataset_name": display_name,
        "source_path": source_path,
        "version": version,
        "master_anchor": master_anchor,
        "created_at": datetime.now().isoformat(),
        "indexed_at": None
    }


def create_empty_data_catalog() -> Dict[str, Any]:
    """
    빈 DataCatalog 생성
    
    Returns:
        빈 DataCatalog 딕셔너리
    """
    return {
        "version": "2.0",  # Dataset-First Architecture
        "created_at": datetime.now().isoformat(),
        "datasets": {},              # dataset_id -> DatasetInfo
        "tables": {},                # table_id -> TableInfo
        "ontologies": {},            # dataset_id -> DatasetOntology
        "cross_dataset_mappings": [] # 데이터셋 간 수동 매핑 (선택적)
    }


def get_dataset_source_path(file_path: str) -> str:
    """
    파일 경로에서 데이터셋 소스 디렉토리 추출
    
    Examples:
        '/data/raw/INSPIRE_130K_1.3/subdir/file.csv' -> '/data/raw/INSPIRE_130K_1.3'
    """
    path_parts = file_path.replace("\\", "/").split("/")
    
    # 'raw' 다음 폴더까지
    try:
        if "raw" in path_parts:
            raw_idx = path_parts.index("raw")
            if raw_idx + 1 < len(path_parts):
                return "/".join(path_parts[:raw_idx + 2])
    except (ValueError, IndexError):
        pass
    
    # 파일의 부모 디렉토리
    return os.path.dirname(file_path)

