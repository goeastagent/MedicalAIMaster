# shared/models/plan.py
"""
Execution Plan 관련 데이터 모델

ExtractionAgent의 execution_plan JSON을 파싱한 결과를 담는 모델들입니다.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class CohortMetadata:
    """
    Cohort 소스 메타데이터
    
    Execution Plan의 cohort_source 섹션을 파싱한 결과입니다.
    
    Attributes:
        file_id: DB의 file_metadata.file_id
        file_path: 실제 파일 경로 (DB에서 resolve)
        file_name: 파일명
        entity_identifier: 엔티티 식별자 컬럼명 (예: "caseid")
        row_represents: 행이 나타내는 것 (예: "surgical_case")
        filters: 적용할 필터 조건 목록
    """
    file_id: Optional[str] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    entity_identifier: Optional[str] = None
    row_represents: Optional[str] = None
    filters: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "file_id": self.file_id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "entity_identifier": self.entity_identifier,
            "row_represents": self.row_represents,
            "filters": self.filters,
        }


@dataclass
class SignalMetadata:
    """
    Signal 소스 메타데이터
    
    Execution Plan의 signal_source 섹션을 파싱한 결과입니다.
    
    Attributes:
        group_id: DB의 file_group.group_id
        group_name: 그룹명
        entity_identifier_key: 엔티티 식별자 키 (예: "caseid")
        row_represents: 행이 나타내는 것
        files: 그룹에 속한 파일 목록 [{file_id, file_path, caseid}, ...]
        param_keys: 요청된 파라미터 키 목록
        param_info: 파라미터 상세 정보 목록
        temporal_config: 시간 범위 설정
    """
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    entity_identifier_key: Optional[str] = None
    row_represents: Optional[str] = None
    files: List[Dict[str, Any]] = field(default_factory=list)
    param_keys: List[str] = field(default_factory=list)
    param_info: List[Dict[str, Any]] = field(default_factory=list)
    temporal_config: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "group_id": self.group_id,
            "group_name": self.group_name,
            "entity_identifier_key": self.entity_identifier_key,
            "row_represents": self.row_represents,
            "file_count": len(self.files),
            "param_keys": self.param_keys,
            "param_info": self.param_info,
            "temporal_config": self.temporal_config,
        }


@dataclass
class JoinConfig:
    """
    Join 설정
    
    Cohort와 Signal을 연결하는 조인 설정입니다.
    
    Attributes:
        cohort_key: Cohort 측 조인 키 컬럼명
        signal_key: Signal 측 조인 키
        join_type: 조인 타입 (inner, left, right, outer)
    """
    cohort_key: Optional[str] = None
    signal_key: Optional[str] = None
    join_type: str = "inner"
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "cohort_key": self.cohort_key,
            "signal_key": self.signal_key,
            "join_type": self.join_type,
        }


@dataclass
class ParsedPlan:
    """
    파싱된 Execution Plan
    
    ExtractionAgent가 생성한 execution_plan JSON을 파싱한 최종 결과입니다.
    
    Attributes:
        raw_plan: 원본 execution_plan JSON
        cohort: Cohort 메타데이터
        signal: Signal 메타데이터
        join: Join 설정
        original_query: 사용자의 원본 쿼리
    """
    raw_plan: Dict[str, Any]
    cohort: CohortMetadata
    signal: SignalMetadata
    join: JoinConfig
    original_query: Optional[str] = None
    
    @property
    def entity_id_column(self) -> Optional[str]:
        """주요 엔티티 식별자 컬럼명"""
        return self.signal.entity_identifier_key or self.cohort.entity_identifier
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "entity_id_column": self.entity_id_column,
            "cohort": self.cohort.to_dict(),
            "signal": self.signal.to_dict(),
            "join": self.join.to_dict(),
            "original_query": self.original_query,
        }


@dataclass
class CohortColumnInfo:
    """
    Cohort 컬럼 정보
    
    Cohort DataFrame의 각 컬럼에 대한 메타데이터입니다.
    LLM이 컬럼 구조를 이해하는 데 사용됩니다.
    
    Attributes:
        name: 컬럼명
        dtype: 데이터 타입 (str 형태)
        null_count: NULL 값 개수
        unique_count: 유니크 값 개수
        col_type: 컬럼 타입 ("numeric" | "categorical")
        stats: 숫자형일 때 통계 정보 (mean, min, max)
        sample_values: 범주형일 때 샘플 값들
    """
    name: str
    dtype: str
    null_count: int
    unique_count: int
    col_type: str  # "numeric" | "categorical"
    stats: Optional[Dict[str, Any]] = None
    sample_values: Optional[List[Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        result = {
            "name": self.name,
            "dtype": self.dtype,
            "null_count": self.null_count,
            "unique_count": self.unique_count,
            "type": self.col_type,
        }
        if self.stats:
            result["stats"] = self.stats
        if self.sample_values:
            result["sample_values"] = self.sample_values
        return result


@dataclass
class AnalysisContext:
    """
    LLM 분석을 위한 컨텍스트
    
    DataContext의 정보를 LLM이 이해할 수 있는 형태로 정리한 것입니다.
    
    Attributes:
        description: 데이터에 대한 자연어 설명
        cohort_info: Cohort 정보 (케이스 수, 필터, 컬럼 정보 등)
        signal_info: Signal 정보 (파라미터, 시간 설정 등)
        original_query: 사용자의 원본 쿼리
    """
    description: str
    cohort_info: Dict[str, Any]
    signal_info: Dict[str, Any]
    original_query: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "description": self.description,
            "cohort": self.cohort_info,
            "signals": self.signal_info,
            "original_query": self.original_query or ""
        }
