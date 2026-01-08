# src/agents/base/__init__.py
"""
Base classes and mixins for agent nodes

Re-exports from shared.langgraph for backward compatibility.

Provides:
- BaseNode: Abstract base class for all nodes
- LLMMixin: Mixin for nodes that use LLM
- DatabaseMixin: Mixin for nodes that access database
- LoggingMixin: Mixin for standardized logging
- Neo4jMixin: Mixin for Neo4j graph database connection
"""

from shared.langgraph import (
    BaseNode,
    LLMMixin,
    DatabaseMixin,
    LoggingMixin,
    Neo4jMixin,
)

__all__ = [
    "BaseNode",
    "LLMMixin",
    "DatabaseMixin",
    "LoggingMixin",
    "Neo4jMixin",
]
