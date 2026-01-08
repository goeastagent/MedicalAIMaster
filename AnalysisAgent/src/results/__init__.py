# AnalysisAgent/src/results/__init__.py
"""
Results Module

Provides result storage, caching, and history management.
"""

from ..models.result import AnalysisResult, ResultSummary
from .store import ResultStore, get_result_store, reset_global_store

__all__ = [
    "AnalysisResult",
    "ResultSummary",
    "ResultStore",
    "get_result_store",
    "reset_global_store",
]
