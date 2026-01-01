# src/agents/nodes/__init__.py
"""
Node modules for LangGraph workflow

10개 노드 아키텍처 (order 기반):
- directory_catalog (100): 디렉토리 레벨 메타데이터 수집 (Rule-based)
- file_catalog (200): 파일 레벨 메타데이터 추출 및 DB 저장 (Rule-based)
- schema_aggregation (300): 유니크 컬럼/파일 집계 및 LLM 배치 준비 (Rule-based)
- file_classification (400): 파일 분류 - metadata vs data (LLM)
- metadata_semantic (500): 메타데이터 파일 분석 및 data_dictionary 추출 (LLM)
- data_semantic (600): 데이터 파일 컬럼 의미 분석 (LLM)
- directory_pattern (700): 디렉토리 파일명 패턴 분석 (LLM)
- entity_identification (800): Entity 식별 - row_represents, entity_identifier (LLM)
- relationship_inference (900): 테이블 간 FK 관계 추론 + Neo4j 3-Level Ontology (LLM)
- ontology_enhancement (1000): Concept Hierarchy, Semantic Edges, Medical Terms (LLM)
"""

# 각 노드 파일 임포트 시 @register_node 데코레이터가 자동으로 NodeRegistry에 등록
from src.agents.nodes.directory_catalog import DirectoryCatalogNode
from src.agents.nodes.catalog import FileCatalogNode
from src.agents.nodes.aggregator import SchemaAggregationNode
from src.agents.nodes.file_classification import FileClassificationNode  # folder
from src.agents.nodes.metadata_semantic import MetadataSemanticNode  # folder
from src.agents.nodes.data_semantic import DataSemanticNode  # folder
from src.agents.nodes.directory_pattern import DirectoryPatternNode  # folder
from src.agents.nodes.entity_identification import EntityIdentificationNode  # folder
from src.agents.nodes.relationship_inference import RelationshipInferenceNode  # folder
from src.agents.nodes.ontology_enhancement import OntologyEnhancementNode  # folder


__all__ = [
    "DirectoryCatalogNode",
    "FileCatalogNode",
    "SchemaAggregationNode",
    "FileClassificationNode",
    "MetadataSemanticNode",
    "DataSemanticNode",
    "DirectoryPatternNode",
    "EntityIdentificationNode",
    "RelationshipInferenceNode",
    "OntologyEnhancementNode",
]
