# src/agents/nodes/__init__.py
"""
Node modules for LangGraph workflow

Multi-Phase Architecture:
- Phase -1 (directory_catalog): 디렉토리 레벨 메타데이터 수집 (Rule-based)
- Phase 0 (catalog): 파일 레벨 메타데이터 추출 및 DB 저장 (Rule-based)
- Phase 0.5 (aggregator): 유니크 컬럼/파일 집계 및 LLM 배치 준비
- Phase 0.7 (classification): 파일 분류 (metadata vs data)
- Phase 1A (metadata_semantic): 메타데이터 파일 분석
- Phase 1C (directory_pattern): 디렉토리 패턴 분석
- Phase 1B (data_semantic): 데이터 파일 분석
- Phase 2A (entity_identification): Entity 식별
- Phase 2B (relationship_inference): 관계 추론
- Phase 2C (ontology_enhancement): 온톨로지 확장
"""

# Phase -1: Directory Catalog
from src.agents.nodes.directory_catalog import phase_neg1_directory_catalog_node

# Phase 0: Data Catalog
from src.agents.nodes.catalog import phase0_catalog_node

# Phase 0.5 ~ 2C
from src.agents.nodes.loader import load_data_node
from src.agents.nodes.analyzer import analyze_semantics_node
from src.agents.nodes.indexer import index_data_node
from src.agents.nodes.human_review import human_review_node
from src.agents.nodes.aggregator import phase05_aggregation_node
from src.agents.nodes.classification import file_classification_node
from src.agents.nodes.metadata_semantic import metadata_semantic_node
from src.agents.nodes.directory_pattern import phase1c_directory_pattern_node
from src.agents.nodes.data_semantic import data_semantic_node
from src.agents.nodes.entity_identification import entity_identification_node
from src.agents.nodes.relationship_inference import relationship_inference_node
from src.agents.nodes.ontology_enhancement import ontology_enhancement_node
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
    # Phase -1: Directory Catalog
    "phase_neg1_directory_catalog_node",
    # Phase 0: Data Catalog
    "phase0_catalog_node",
    # Phase 0.5: Schema Aggregation
    "phase05_aggregation_node",
    # Phase 0.7: File Classification
    "file_classification_node",
    # Phase 1A: MetaData Semantic
    "metadata_semantic_node",
    # Phase 1C: Directory Pattern Analysis
    "phase1c_directory_pattern_node",
    # Phase 1B: Data Semantic Analysis
    "data_semantic_node",
    # Phase 2A: Entity Identification
    "entity_identification_node",
    # Phase 2B: Relationship Inference + Neo4j
    "relationship_inference_node",
    # Phase 2C: Ontology Enhancement
    "ontology_enhancement_node",
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

