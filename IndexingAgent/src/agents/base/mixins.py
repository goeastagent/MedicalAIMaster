# src/agents/base/mixins.py
"""
Mixins for agent nodes - Re-export from shared.langgraph

This file re-exports mixins from shared.langgraph for backward compatibility.
New code should import directly from shared.langgraph.

Usage (backward compatible):
    from src.agents.base.mixins import LLMMixin, DatabaseMixin, Neo4jMixin
    
Recommended:
    from shared.langgraph import LLMMixin, DatabaseMixin, Neo4jMixin
"""

from shared.langgraph import (
    LLMMixin,
    DatabaseMixin,
    LoggingMixin,
    Neo4jMixin,
)

__all__ = [
    "LLMMixin",
    "DatabaseMixin",
    "LoggingMixin",
    "Neo4jMixin",
]
