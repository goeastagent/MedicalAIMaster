# src/agents/nodes/__init__.py
"""
Node modules for LangGraph workflow

10-Phase Sequential Architecture:
- Phase 1 (directory_catalog): 디렉토리 레벨 메타데이터 수집 (Rule-based)
- Phase 2 (file_catalog): 파일 레벨 메타데이터 추출 및 DB 저장 (Rule-based)
- Phase 3 (schema_aggregation): 유니크 컬럼/파일 집계 및 LLM 배치 준비 (Rule-based)
- Phase 4 (file_classification): 파일 분류 - metadata vs data (LLM)
- Phase 5 (metadata_semantic): 메타데이터 파일 분석 및 data_dictionary 추출 (LLM)
- Phase 6 (data_semantic): 데이터 파일 컬럼 의미 분석 (LLM)
- Phase 7 (directory_pattern): 디렉토리 파일명 패턴 분석 (LLM)
- Phase 8 (entity_identification): Entity 식별 - row_represents, entity_identifier (LLM)
- Phase 9 (relationship_inference): 테이블 간 FK 관계 추론 + Neo4j 3-Level Ontology (LLM)
- Phase 10 (ontology_enhancement): Concept Hierarchy, Semantic Edges, Medical Terms (LLM)
"""

# Phase 1: Directory Catalog
from src.agents.nodes.directory_catalog import phase1_directory_catalog_node

# Phase 2: File Catalog
from src.agents.nodes.catalog import phase2_file_catalog_node

# Phase 3: Schema Aggregation
from src.agents.nodes.aggregator import phase3_aggregation_node

# Phase 4: File Classification
from src.agents.nodes.classification import phase4_classification_node

# Phase 5: Metadata Semantic
from src.agents.nodes.metadata_semantic import phase5_metadata_semantic_node

# Phase 6: Data Semantic
from src.agents.nodes.data_semantic import phase6_data_semantic_node

# Phase 7: Directory Pattern
from src.agents.nodes.directory_pattern import phase7_directory_pattern_node

# Phase 8: Entity Identification
from src.agents.nodes.entity_identification import phase8_entity_identification_node

# Phase 9: Relationship Inference
from src.agents.nodes.relationship_inference import phase9_relationship_inference_node

# Phase 10: Ontology Enhancement
from src.agents.nodes.ontology_enhancement import phase10_ontology_enhancement_node


__all__ = [
    # Phase 1: Directory Catalog
    "phase1_directory_catalog_node",
    # Phase 2: File Catalog
    "phase2_file_catalog_node",
    # Phase 3: Schema Aggregation
    "phase3_aggregation_node",
    # Phase 4: File Classification
    "phase4_classification_node",
    # Phase 5: Metadata Semantic
    "phase5_metadata_semantic_node",
    # Phase 6: Data Semantic
    "phase6_data_semantic_node",
    # Phase 7: Directory Pattern
    "phase7_directory_pattern_node",
    # Phase 8: Entity Identification
    "phase8_entity_identification_node",
    # Phase 9: Relationship Inference
    "phase9_relationship_inference_node",
    # Phase 10: Ontology Enhancement
    "phase10_ontology_enhancement_node",
]
