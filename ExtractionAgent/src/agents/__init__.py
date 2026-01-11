# src/agents/__init__.py
"""
ExtractionAgent - 3-Node Pipeline for Data Extraction

Pipeline:
    [100] QueryUnderstanding - 동적 컨텍스트 로딩 + 쿼리 분석
    [200] ParameterResolver  - 파라미터 매핑
    [300] PlanBuilder        - Execution Plan 생성
"""

from .state import ExtractionState
from .registry import NodeRegistry, register_node, get_registry
from .graph import build_agent, build_custom_agent

# Backward compatibility alias
VitalExtractionState = ExtractionState

__all__ = [
    "ExtractionState",
    "VitalExtractionState",  # backward compatibility
    "NodeRegistry",
    "register_node",
    "get_registry",
    "build_agent",
    "build_custom_agent",
]

