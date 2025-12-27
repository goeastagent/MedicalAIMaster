# src/processors/base.py
"""
Base Processor - 데이터 추출만 담당 (LLM 없음)

Processor의 역할:
- 파일 읽기
- 구조화된 데이터 추출 (컬럼, 샘플, 메타데이터)

Analyzer의 역할 (Processor에서 분리됨):
- LLM을 통한 Entity Identifier 감지
- 시맨틱 분석
- 계층 관계 추론
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseDataProcessor(ABC):
    """
    모든 데이터 프로세서의 기본 클래스.
    
    [Rule Prepares Only]
    - 파일을 읽고 구조화된 데이터만 추출합니다.
    - LLM 호출은 하지 않습니다 (Analyzer에서 담당).
    """

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: 더 이상 사용되지 않음 (하위 호환성을 위해 유지)
        """
        # LLM 클라이언트는 더 이상 사용하지 않음
        # Analyzer에서 직접 LLM을 호출함
        pass

    @abstractmethod
    def can_handle(self, file_path: str) -> bool:
        """파일 처리 가능 여부 확인"""
        pass

    @abstractmethod
    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        [Rule Prepares Only]
        파일에서 메타데이터를 추출합니다.
        
        Returns:
            {
                "processor_type": str,      # "tabular" or "signal"
                "file_path": str,
                "columns": List[str],       # 컬럼/트랙 이름 목록
                "column_details": List/Dict, # 컬럼별 상세 정보
                ...                         # 프로세서별 추가 정보
            }
            
        NOTE: entity_info는 포함하지 않음 (Analyzer에서 결정)
        """
        pass
