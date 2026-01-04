# src/agents/nodes/__init__.py
"""
Node modules for LangGraph workflow

13개 노드 아키텍처 (order 기반):

Phase 1 (Rule-based 메타데이터 수집):
- directory_catalog (100): 디렉토리 레벨 메타데이터 수집
- file_catalog (200): 파일 레벨 메타데이터 추출 및 DB 저장
- file_grouping_prep (250): 파일 그룹핑 준비 - 패턴 관찰 (NEW!)
- schema_aggregation (300): 유니크 컬럼/파일 집계 및 LLM 배치 준비

Phase 2 (LLM-based 의미 분석):
- file_grouping (350): 파일 그룹핑 전략 결정 + 검증 (NEW!)
- file_classification (400): 파일 분류 - metadata vs data
- column_classification (420): 컬럼 역할 분류 + parameter 생성
- metadata_semantic (500): 메타데이터 파일 분석 및 data_dictionary 추출
- parameter_semantic (600): parameter 의미 분석 + dictionary 매칭
- directory_pattern (700): 디렉토리 파일명 패턴 분석

Phase 3 (LLM-based 관계 추론):
- entity_identification (800): Entity 식별 - row_represents, entity_identifier
- relationship_inference (900): 테이블 간 FK 관계 추론 + Neo4j 3-Level Ontology

Phase 4 (LLM-based 온톨로지 강화):
- ontology_enhancement (1000): Concept Hierarchy, Semantic Edges, Medical Terms
"""

# 각 노드 파일 임포트 시 @register_node 데코레이터가 자동으로 NodeRegistry에 등록
from src.agents.nodes.directory_catalog import DirectoryCatalogNode
from src.agents.nodes.catalog import FileCatalogNode
from src.agents.nodes.file_grouping_prep import FileGroupingPrepNode  # [250] Rule-based
from src.agents.nodes.aggregator import SchemaAggregationNode
from src.agents.nodes.file_grouping import FileGroupingNode  # [350] LLM-based - NEW!
from src.agents.nodes.file_classification import FileClassificationNode  # folder
from src.agents.nodes.column_classification import ColumnClassificationNode  # folder
from src.agents.nodes.metadata_semantic import MetadataSemanticNode  # folder
from src.agents.nodes.parameter_semantic import ParameterSemanticNode  # folder (renamed from data_semantic)
from src.agents.nodes.directory_pattern import DirectoryPatternNode  # folder
from src.agents.nodes.entity_identification import EntityIdentificationNode  # folder
from src.agents.nodes.relationship_inference import RelationshipInferenceNode  # folder
from src.agents.nodes.ontology_enhancement import OntologyEnhancementNode  # folder


__all__ = [
    "DirectoryCatalogNode",
    "FileCatalogNode",
    "FileGroupingPrepNode",  # [250]
    "SchemaAggregationNode",
    "FileGroupingNode",  # [350] - NEW!
    "FileClassificationNode",
    "ColumnClassificationNode",
    "MetadataSemanticNode",
    "ParameterSemanticNode",
    "DirectoryPatternNode",
    "EntityIdentificationNode",
    "RelationshipInferenceNode",
    "OntologyEnhancementNode",
]
