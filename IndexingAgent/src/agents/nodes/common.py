# src/agents/nodes/common.py
"""
공통 모듈 - Processors 목록
"""

from src.processors.tabular import TabularProcessor
from src.processors.signal import SignalProcessor
from src.utils.llm_client import get_llm_client


# Processors list - used by catalog.py
_llm_client = get_llm_client()

processors = [
    TabularProcessor(_llm_client),
    SignalProcessor(_llm_client)
]
