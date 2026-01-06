# src/agents/nodes/__init__.py
"""
VitalExtractionAgent Nodes

3-Node Pipeline:
    [100] QueryUnderstandingNode - 동적 컨텍스트 로딩 + 쿼리 분석
    [200] ParameterResolverNode  - 파라미터 매핑
    [300] PlanBuilderNode        - Execution Plan 생성

Import 시 자동으로 NodeRegistry에 등록됩니다.
"""

# 각 노드 import (registry 자동 등록)
from .query_understanding import QueryUnderstandingNode
from .parameter_resolver import ParameterResolverNode
from .plan_builder import PlanBuilderNode

__all__ = [
    "QueryUnderstandingNode",
    "ParameterResolverNode",
    "PlanBuilderNode",
]

