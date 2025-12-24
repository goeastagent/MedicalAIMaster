# src/utils/naming.py
"""
Dataset-First Architecture: 테이블/엔티티 이름 생성 유틸리티

모든 테이블명에 데이터셋 prefix를 추가하여 충돌을 방지합니다.
"""

import os
import hashlib
from typing import Optional


def generate_table_name(file_path: str, dataset_id: str) -> str:
    """
    고유한 테이블 이름 생성
    
    Format: {dataset_prefix}_{filename}_table
    
    Args:
        file_path: 원본 파일 경로
        dataset_id: 데이터셋 ID (예: "inspire_130k_v1.3")
    
    Returns:
        고유한 테이블 이름 (예: "inspire_clinical_data_table")
    
    Examples:
        >>> generate_table_name("/data/INSPIRE/clinical_data.csv", "inspire_130k_v1.3")
        'inspire_clinical_data_table'
        >>> generate_table_name("/data/VitalDB/clinical_data.csv", "open_vitaldb_v1.0.0")
        'vitaldb_clinical_data_table'
    """
    # 데이터셋 prefix 추출
    dataset_prefix = extract_dataset_prefix(dataset_id)
    
    # 파일명 정제
    filename = os.path.basename(file_path)
    filename = filename.replace(".csv", "").replace(".CSV", "")
    filename = filename.replace(".", "_").replace("-", "_").lower()
    
    return f"{dataset_prefix}_{filename}_table"


def generate_table_id(dataset_id: str, table_name: str) -> str:
    """
    고유 테이블 ID 생성 (버전 관리용)
    
    Format: {dataset_id}.{table_name}
    
    Args:
        dataset_id: 데이터셋 ID
        table_name: 테이블 이름
    
    Returns:
        고유 테이블 ID
    
    Examples:
        >>> generate_table_id("inspire_130k_v1.3", "inspire_clinical_data_table")
        'inspire_130k_v1.3.inspire_clinical_data_table'
    """
    return f"{dataset_id}.{table_name}"


def extract_dataset_prefix(dataset_id: str) -> str:
    """
    데이터셋 ID에서 테이블 prefix 추출
    
    Args:
        dataset_id: 데이터셋 ID (예: "inspire_130k_v1.3", "open_vitaldb_v1.0.0")
    
    Returns:
        짧은 prefix (예: "inspire", "vitaldb")
    
    Examples:
        >>> extract_dataset_prefix("inspire_130k_v1.3")
        'inspire'
        >>> extract_dataset_prefix("open_vitaldb_v1.0.0")
        'vitaldb'
    """
    # 버전 정보 제거 (_v 또는 _V 이후)
    name_part = dataset_id.split("_v")[0].split("_V")[0]
    
    # 첫 번째 의미 있는 단어 추출
    # "open_vitaldb" -> "vitaldb" (open은 너무 일반적)
    parts = name_part.lower().split("_")
    
    # 'open', 'raw', 'data' 같은 일반적인 접두어 제거
    skip_prefixes = {'open', 'raw', 'data', 'dataset', 'db'}
    
    for part in parts:
        if part and part not in skip_prefixes:
            return part
    
    # fallback: 첫 번째 파트 사용
    return parts[0] if parts else "unknown"


def generate_schema_hash(columns: list, sample_size: int = 5) -> str:
    """
    스키마 변경 감지용 해시 생성
    
    Args:
        columns: 컬럼 정보 리스트
        sample_size: 샘플 데이터 크기 (해시에 포함할 행 수)
    
    Returns:
        스키마 해시 (64자 hex string)
    """
    # 컬럼 이름과 타입으로 해시 생성
    schema_str = "|".join(sorted([
        f"{col.get('original_name', '')}:{col.get('data_type', '')}"
        for col in columns
    ]))
    
    return hashlib.sha256(schema_str.encode()).hexdigest()


def sanitize_for_neo4j_label(name: str) -> str:
    """
    Neo4j 라벨로 사용할 수 있도록 이름 정제
    
    Neo4j 라벨은 특수문자를 허용하지 않으므로 정제가 필요합니다.
    
    Args:
        name: 원본 이름
    
    Returns:
        Neo4j 라벨로 사용 가능한 이름
    
    Examples:
        >>> sanitize_for_neo4j_label("inspire_130k_v1.3")
        'Inspire_130k_v1_3'
    """
    # 특수문자를 언더스코어로 대체
    sanitized = name.replace(".", "_").replace("-", "_").replace(" ", "_")
    
    # 숫자로 시작하면 안 되므로 prefix 추가
    if sanitized and sanitized[0].isdigit():
        sanitized = "D_" + sanitized
    
    # 첫 글자 대문자 (Neo4j 컨벤션)
    if sanitized:
        sanitized = sanitized[0].upper() + sanitized[1:]
    
    return sanitized

