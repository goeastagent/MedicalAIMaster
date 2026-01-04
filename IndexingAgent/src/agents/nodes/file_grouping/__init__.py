# src/agents/nodes/file_grouping/__init__.py
"""
File Grouping Node

[250] file_grouping_prep에서 수집한 정보를 바탕으로
LLM이 파일 그룹핑 전략을 결정하고 검증합니다.

핵심 역할:
- 그룹핑 전략 결정 (pattern_based, partitioned, paired, single)
- 그룹 생성 및 검증
- file_catalog.group_id 할당
"""

from .node import FileGroupingNode

__all__ = ["FileGroupingNode"]

