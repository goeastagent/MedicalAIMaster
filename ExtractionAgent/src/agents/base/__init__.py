# src/agents/base/__init__.py
"""
Base classes for ExtractionAgent nodes.

Re-exports from shared.langgraph for backward compatibility.
"""

from shared.langgraph import BaseNode

__all__ = ["BaseNode"]
