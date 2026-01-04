# src/agents/nodes/file_grouping_prep/__init__.py
"""
File Grouping Prep Node

디렉토리별 파일 통계를 수집하고 패턴을 관찰합니다.
판단은 하지 않고, [350] file_grouping 노드의 LLM 입력을 준비합니다.

핵심 철학: "Rule Prepares, LLM Decides"
- 이 노드: 관찰된 사실만 수집 (판단 X)
- 다음 노드 [350]: LLM이 그룹핑 전략 결정
"""

from .node import FileGroupingPrepNode

__all__ = ["FileGroupingPrepNode"]

