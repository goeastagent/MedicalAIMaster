# shared/processors/base.py
"""
Base Processor - 메타데이터 추출 + 데이터 로드

Processor의 역할:
1. extract_metadata(): 파일 메타데이터 추출 (IndexingAgent용)
2. load_data(): 실제 데이터 로드 (DataContext용)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import pandas as pd


class BaseDataProcessor(ABC):
    """
    모든 데이터 프로세서의 기본 클래스.
    
    두 가지 주요 기능:
    1. extract_metadata(): 파일 구조/스키마 정보 추출 (빠름, IndexingAgent용)
    2. load_data(): 실제 데이터 로드 (느림, DataContext용)
    """
    
    # 서브클래스에서 오버라이드
    SUPPORTED_EXTENSIONS: set = set()

    @abstractmethod
    def can_handle(self, file_path: str) -> bool:
        """파일 처리 가능 여부 확인"""
        pass

    @abstractmethod
    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        [IndexingAgent용] 파일에서 메타데이터를 추출합니다.
        
        Returns:
            {
                "processor_type": str,      # "tabular" or "signal"
                "file_path": str,
                "columns": List[str],       # 컬럼/트랙 이름 목록
                "column_details": List/Dict, # 컬럼별 상세 정보
                ...                         # 프로세서별 추가 정보
            }
        """
        pass
    
    @abstractmethod
    def load_data(
        self,
        file_path: str,
        columns: Optional[List[str]] = None,
        **kwargs
    ) -> pd.DataFrame:
        """
        [DataContext용] 파일에서 실제 데이터를 로드합니다.
        
        Args:
            file_path: 파일 경로
            columns: 로드할 컬럼/트랙 (None이면 전체)
            **kwargs: 프로세서별 추가 옵션
                - TabularProcessor: filters, limit
                - SignalProcessor: time_range, resample_interval
        
        Returns:
            DataFrame
        """
        pass
    
    def get_available_columns(self, file_path: str) -> List[str]:
        """
        파일에서 사용 가능한 컬럼/트랙 목록 반환 (데이터 로드 없이)
        
        기본 구현: extract_metadata()의 'columns' 필드 사용
        서브클래스에서 더 효율적인 방법으로 오버라이드 가능
        """
        metadata = self.extract_metadata(file_path)
        return metadata.get("columns", [])

