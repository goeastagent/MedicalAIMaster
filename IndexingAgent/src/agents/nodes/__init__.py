# src/agents/nodes/__init__.py
"""
Node modules for LangGraph workflow

Multi-Phase Architecture:
- Phase 0 (catalog): 규칙 기반 메타데이터 추출 및 DB 저장
- Phase 0.5 (aggregator): 유니크 컬럼/파일 집계 및 LLM 배치 준비
- Phase 1 (semantic): LLM 기반 의미론적 분석 (컬럼 + 파일)
- Phase 2 (processing): 개별 파일 처리 및 인덱싱
"""

from src.agents.nodes.loader import load_data_node
from src.agents.nodes.analyzer import analyze_semantics_node
from src.agents.nodes.indexer import index_data_node
from src.agents.nodes.human_review import human_review_node
from src.agents.nodes.catalog import phase0_catalog_node
from src.agents.nodes.aggregator import phase05_aggregation_node
from src.agents.nodes.classification import file_classification_node
from src.agents.nodes.metadata_semantic import metadata_semantic_node
from src.agents.nodes.data_semantic import data_semantic_node
from src.agents.nodes.semantic import phase1_semantic_node
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
    # Phase 0: Data Catalog
    "phase0_catalog_node",
    # Phase 0.5: Schema Aggregation
    "phase05_aggregation_node",
    # Phase 0.7: File Classification
    "file_classification_node",
    # Phase 1A: MetaData Semantic
    "metadata_semantic_node",
    # Phase 1B: Data Semantic Analysis (새로운 노드)
    "data_semantic_node",
    # Phase 1 (Legacy): Semantic Analysis
    "phase1_semantic_node",
    # Core nodes
    "load_data_node",
    "analyze_semantics_node",
    "index_data_node",
    "human_review_node",
    # Batch workflow nodes (legacy)
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

