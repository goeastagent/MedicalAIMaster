# src/agents/registry.py
"""
NodeRegistry - Re-export from shared.langgraph

This file re-exports NodeRegistry from shared.langgraph for backward compatibility.
New code should import directly from shared.langgraph.

Usage (backward compatible):
    from src.agents.registry import NodeRegistry, register_node, get_registry
    
Recommended:
    from shared.langgraph import NodeRegistry, register_node, get_registry
"""

from shared.langgraph import (
    NodeRegistry,
    register_node,
    get_registry,
    get_node_names,
)

__all__ = [
    "NodeRegistry",
    "register_node",
    "get_registry",
    "get_node_names",
]
