# shared/langgraph/__init__.py
"""
Shared LangGraph Components

LangGraph 기반 Agent 파이프라인을 위한 공통 컴포넌트:
- BaseNode: 모든 노드의 추상 베이스 클래스
- NodeRegistry: 노드 등록 및 관리 (싱글톤)
- Mixins: LLM, Database, Neo4j, Logging 기능 믹스인
- Graph Builder: 순차적 파이프라인 빌드 유틸리티

Usage:
    from shared.langgraph import BaseNode, register_node, get_registry
    from shared.langgraph import LLMMixin, DatabaseMixin, Neo4jMixin
    from shared.langgraph import build_sequential_graph
    
    @register_node
    class MyNode(BaseNode, LLMMixin):
        name = "my_node"
        order = 100
        requires_llm = True
        
        def execute(self, state):
            response = self.call_llm(prompt)
            return {"result": response}
    
    # Build pipeline
    workflow = build_sequential_graph(
        state_class=MyState,
        node_module="myagent.nodes",
        agent_name="MyAgent"
    )
"""

from .base_node import BaseNode
from .registry import NodeRegistry, register_node, get_registry, get_node_names
from .mixins import LLMMixin, DatabaseMixin, LoggingMixin, Neo4jMixin
from .graph_builder import build_sequential_graph, build_partial_graph

__all__ = [
    # Base
    "BaseNode",
    # Registry
    "NodeRegistry",
    "register_node",
    "get_registry",
    "get_node_names",
    # Mixins
    "LLMMixin",
    "DatabaseMixin",
    "LoggingMixin",
    "Neo4jMixin",
    # Graph Builder
    "build_sequential_graph",
    "build_partial_graph",
]

