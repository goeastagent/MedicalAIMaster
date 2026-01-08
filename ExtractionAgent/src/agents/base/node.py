# src/agents/base/node.py
"""
BaseNode - Re-export from shared.langgraph

This file re-exports BaseNode from shared.langgraph for backward compatibility.
New code should import directly from shared.langgraph.

Usage (backward compatible):
    from src.agents.base.node import BaseNode
    
Recommended:
    from shared.langgraph import BaseNode
"""

from shared.langgraph import BaseNode

__all__ = ["BaseNode"]
