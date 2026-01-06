# shared/processors/__init__.py
"""
Data Processors

파일에서 메타데이터를 추출하고 데이터를 로드하는 프로세서들:
- SignalProcessor: 생체신호 파일 (.vital, .edf)
- TabularProcessor: 테이블 파일 (.csv, .parquet, .xlsx)

사용 예시:
    from shared.processors import SignalProcessor, TabularProcessor
    
    # 메타데이터 추출 (IndexingAgent용)
    processor = SignalProcessor()
    metadata = processor.extract_metadata("path/to/file.vital")
    
    # 데이터 로드 (DataContext용)
    df = processor.load_data("path/to/file.vital", columns=["Solar8000/HR"])
"""

from .base import BaseDataProcessor
from .signal import SignalProcessor
from .tabular import TabularProcessor

__all__ = [
    "BaseDataProcessor",
    "SignalProcessor",
    "TabularProcessor",
]

