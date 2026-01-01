# src/agents/nodes/ontology_enhancement/__init__.py
"""
Ontology Enhancement Node Package

Neo4j 온톨로지를 확장/강화:
1. Concept Hierarchy: ConceptCategory를 SubCategory로 세분화
2. Semantic Edges: Parameter 간 의미 관계
3. Medical Term Mapping: SNOMED-CT, LOINC 매핑
4. Cross-table Semantics: 테이블 간 숨겨진 시맨틱 관계
"""

from .node import OntologyEnhancementNode
from .prompts import OntologyEnhancementPrompts

__all__ = [
    "OntologyEnhancementNode",
    "OntologyEnhancementPrompts",
]

