# src/agents/nodes/__init__.py
"""
Node modules for LangGraph workflow

2-Phase Architecture:
- loader: 파일 로드 및 메타데이터 추출
- analyzer: 시맨틱 분석 및 Anchor 확정
- indexer: PostgreSQL 인덱싱
- batch: 배치 분류 및 처리 노드
- routing: 조건부 라우팅 함수
"""

from src.agents.nodes.loader import load_data_node
from src.agents.nodes.analyzer import (
    analyze_semantics_node,
    ontology_builder_node,
)
from src.agents.nodes.indexer import index_data_node
from src.agents.nodes.human_review import human_review_node
from src.agents.nodes.batch import (
    batch_classifier_node,
    classification_review_node,
    process_metadata_batch_node,
    process_data_batch_node,
    advance_to_next_file_node,
)
from src.agents.nodes.routing import (
    check_classification_needs_review,
    check_has_more_files,
    check_data_needs_review,
)

__all__ = [
    # Core nodes
    "load_data_node",
    "analyze_semantics_node",
    "ontology_builder_node",
    "index_data_node",
    "human_review_node",
    # Batch workflow nodes
    "batch_classifier_node",
    "classification_review_node",
    "process_metadata_batch_node",
    "process_data_batch_node",
    "advance_to_next_file_node",
    # Routing functions
    "check_classification_needs_review",
    "check_has_more_files",
    "check_data_needs_review",
]

