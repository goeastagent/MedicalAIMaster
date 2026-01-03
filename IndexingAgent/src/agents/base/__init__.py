# src/agents/base/__init__.py
"""
Base classes and mixins for agent nodes

Provides:
- BaseNode: Abstract base class for all nodes
- LLMMixin: Mixin for nodes that use LLM
- DatabaseMixin: Mixin for nodes that access database
- LoggingMixin: Mixin for standardized logging
- Neo4jMixin: Mixin for Neo4j graph database connection
"""

from .node import BaseNode
from .mixins import LLMMixin, DatabaseMixin, LoggingMixin, Neo4jMixin

__all__ = [
    "BaseNode",
    "LLMMixin",
    "DatabaseMixin",
    "LoggingMixin",
    "Neo4jMixin",
]

