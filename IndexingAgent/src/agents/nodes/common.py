# src/agents/nodes/common.py
"""
공통 모듈 - Processors 목록

NOTE: Processor는 LLM 없이 파일 읽기와 구조화된 데이터 추출만 담당합니다.
      LLM 분석은 Agent Node에서 수행합니다.
"""

from src.processors.tabular import TabularProcessor
from src.processors.signal import SignalProcessor


# Processors list - used by catalog.py
# Processors don't require LLM client (they only extract raw metadata)
processors = [
    TabularProcessor(),
    SignalProcessor()
]
