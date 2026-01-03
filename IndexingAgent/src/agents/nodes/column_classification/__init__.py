# src/agents/nodes/column_classification/__init__.py
"""
Column Classification Node

각 컬럼의 역할을 분류하고, parameter 테이블을 생성합니다.
- Wide-format: 컬럼명이 곧 parameter (예: HR, SBP)
- Long-format: 특정 컬럼의 값들이 parameter (예: param 컬럼의 unique values)

✅ LLM 사용: column_role 판단
✅ 후처리: parameter 테이블 생성 (rule-based)
"""

from .node import ColumnClassificationNode

__all__ = ["ColumnClassificationNode"]

