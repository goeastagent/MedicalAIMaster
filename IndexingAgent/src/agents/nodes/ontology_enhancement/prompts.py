# src/agents/nodes/ontology_enhancement/prompts.py
"""
Ontology Enhancement 프롬프트

Neo4j 온톨로지 확장을 위한 다중 LLM 프롬프트:
1. concept_hierarchy: ConceptCategory → SubCategory 세분화
2. semantic_edges: Parameter 간 의미 관계
3. medical_terms: SNOMED-CT, LOINC 매핑
4. cross_table: 테이블 간 시맨틱 관계
"""

from src.agents.prompts import MultiPromptTemplate
from src.models.llm_responses import (
    SubCategoryResult,
    SemanticEdge,
    MedicalTermMapping,
    CrossTableSemantic,
)


class OntologyEnhancementPrompts(MultiPromptTemplate):
    """
    Ontology Enhancement 다중 프롬프트
    
    4가지 Task에 대한 프롬프트를 관리합니다.
    """
    
    name = "ontology_enhancement"
    
    # Task 정의
    tasks = {
        "concept_hierarchy": {
            "response_model": SubCategoryResult,
            "response_wrapper_key": "subcategories",
            "is_list_response": True,
        },
        "semantic_edges": {
            "response_model": SemanticEdge,
            "response_wrapper_key": "edges",
            "is_list_response": True,
        },
        "medical_terms": {
            "response_model": MedicalTermMapping,
            "response_wrapper_key": "mappings",
            "is_list_response": True,
        },
        "cross_table": {
            "response_model": CrossTableSemantic,
            "response_wrapper_key": "semantics",
            "is_list_response": True,
        },
    }
    
    # =========================================================================
    # Task 1: Concept Hierarchy
    # =========================================================================
    
    CONCEPT_HIERARCHY_SYSTEM = "You are a Medical Data Expert analyzing clinical data concepts."
    
    CONCEPT_HIERARCHY_TASK = """Analyze the following concept categories and their parameters.
Propose meaningful subcategories to organize parameters better."""
    
    CONCEPT_HIERARCHY_CONTEXT = """[Current Concept Categories]
{concept_categories}"""
    
    CONCEPT_HIERARCHY_RULES = [
        "Only create subcategories when there are 3+ parameters that fit naturally",
        "Subcategory names should be specific and medically meaningful",
        "Each parameter should belong to exactly one subcategory",
        "Not all categories need subcategories",
    ]
    
    CONCEPT_HIERARCHY_OUTPUT = """{
  "subcategories": [
    {
      "parent_category": "string - Parent concept category name",
      "subcategory_name": "string - Meaningful subcategory name",
      "parameters": ["string array - Parameter keys belonging to this subcategory"],
      "confidence": "float (0.0-1.0) - Confidence score",
      "reasoning": "string - Explanation for grouping"
    }
  ]
}

If no meaningful subcategories can be created: {"subcategories": []}"""
    
    # =========================================================================
    # Task 2: Semantic Edges
    # =========================================================================
    
    SEMANTIC_EDGES_SYSTEM = "You are a Medical Data Expert analyzing relationships between clinical parameters."
    
    SEMANTIC_EDGES_TASK = "Identify semantic relationships between the following parameters."
    
    SEMANTIC_EDGES_CONTEXT = """[Parameters]
{parameters}

[Relationship Types]
- DERIVED_FROM: Parameter A is calculated/derived from Parameter B
  Example: bmi DERIVED_FROM height, bmi DERIVED_FROM weight
- RELATED_TO: Parameters are medically/clinically related
  Example: sbp RELATED_TO dbp (both blood pressures)
- OPPOSITE_OF: Parameters represent opposite concepts (rare)"""
    
    SEMANTIC_EDGES_RULES = [
        "Only include relationships with high confidence (≥0.8)",
        "DERIVED_FROM should be factually correct (mathematical derivation)",
        "RELATED_TO should be clinically meaningful, not just co-occurrence",
    ]
    
    SEMANTIC_EDGES_OUTPUT = """{
  "edges": [
    {
      "source_parameter": "string - Source parameter key",
      "target_parameter": "string - Target parameter key",
      "relationship_type": "string - DERIVED_FROM | RELATED_TO | OPPOSITE_OF",
      "confidence": "float (0.0-1.0) - Confidence score",
      "reasoning": "string - Explanation"
    }
  ]
}

If no relationships found: {"edges": []}"""
    
    # =========================================================================
    # Task 3: Medical Term Mapping
    # =========================================================================
    
    MEDICAL_TERMS_SYSTEM = "You are a Medical Terminology Expert."
    
    MEDICAL_TERMS_TASK = "Map the following clinical parameters to standard medical terminologies."
    
    MEDICAL_TERMS_CONTEXT = """[Parameters to Map]
{parameters}

[Target Terminologies]
1. SNOMED-CT: Clinical concepts (provide concept ID and preferred term)
2. LOINC: Lab and clinical observations (provide code and name)
3. ICD-10: Diagnoses (only if applicable, e.g., for conditions)"""
    
    MEDICAL_TERMS_RULES = [
        "Only include mappings you are confident about (≥0.8)",
        "Use actual SNOMED-CT concept IDs (numeric)",
        "Use actual LOINC codes (format: XXXXX-X)",
        "Leave null if no appropriate mapping exists",
        "Provide reasoning for each mapping decision",
    ]
    
    MEDICAL_TERMS_OUTPUT = """{
  "mappings": [
    {
      "parameter_key": "string - Parameter key to map",
      "snomed_code": "string or null - SNOMED-CT concept ID",
      "snomed_name": "string or null - SNOMED-CT preferred term",
      "loinc_code": "string or null - LOINC code (XXXXX-X format)",
      "loinc_name": "string or null - LOINC name",
      "icd10_code": "string or null - ICD-10 code (if applicable)",
      "icd10_name": "string or null - ICD-10 name",
      "confidence": "float (0.0-1.0) - Confidence score",
      "reasoning": "string - Explanation for mapping"
    }
  ]
}"""
    
    # =========================================================================
    # Task 4: Cross-table Semantics
    # =========================================================================
    
    CROSS_TABLE_SYSTEM = "You are a Medical Data Expert analyzing relationships between columns across different tables."
    
    CROSS_TABLE_TASK = "Identify columns that represent the same or similar concepts across different tables."
    
    CROSS_TABLE_CONTEXT = """[Tables and Columns]
{tables_info}"""
    
    CROSS_TABLE_RULES = [
        "Look for semantic equivalence, not just name matching",
        "Consider unit differences (e.g., hemoglobin in g/dL vs mg/L)",
        "Only include high-confidence relationships (≥0.8)",
    ]
    
    CROSS_TABLE_OUTPUT = """{
  "semantics": [
    {
      "source_table": "string - Source table name",
      "source_column": "string - Source column name",
      "target_table": "string - Target table name",
      "target_column": "string - Target column name",
      "relationship_type": "string - SAME_CONCEPT | SEMANTICALLY_SIMILAR",
      "confidence": "float (0.0-1.0) - Confidence score",
      "reasoning": "string - Explanation"
    }
  ]
}

If no cross-table relationships found: {"semantics": []}"""
    
    # =========================================================================
    # Build Methods
    # =========================================================================
    
    @classmethod
    def build_concept_hierarchy(cls, concept_categories: str) -> str:
        """Task 1: Concept Hierarchy 프롬프트 빌드"""
        parts = [
            f"[Role]\n{cls.CONCEPT_HIERARCHY_SYSTEM}",
            f"\n[Task]\n{cls.CONCEPT_HIERARCHY_TASK}",
            f"\n{cls.CONCEPT_HIERARCHY_CONTEXT.format(concept_categories=concept_categories)}",
            "\n[Rules]",
            *[f"- {rule}" for rule in cls.CONCEPT_HIERARCHY_RULES],
            f"\n[Output Format]\nReturn ONLY valid JSON (no markdown):\n{cls.CONCEPT_HIERARCHY_OUTPUT}",
        ]
        return "\n".join(parts)
    
    @classmethod
    def build_semantic_edges(cls, parameters: str) -> str:
        """Task 2: Semantic Edges 프롬프트 빌드"""
        parts = [
            f"[Role]\n{cls.SEMANTIC_EDGES_SYSTEM}",
            f"\n[Task]\n{cls.SEMANTIC_EDGES_TASK}",
            f"\n{cls.SEMANTIC_EDGES_CONTEXT.format(parameters=parameters)}",
            "\n[Rules]",
            *[f"- {rule}" for rule in cls.SEMANTIC_EDGES_RULES],
            f"\n[Output Format]\nReturn ONLY valid JSON (no markdown):\n{cls.SEMANTIC_EDGES_OUTPUT}",
        ]
        return "\n".join(parts)
    
    @classmethod
    def build_medical_terms(cls, parameters: str) -> str:
        """Task 3: Medical Terms 프롬프트 빌드"""
        parts = [
            f"[Role]\n{cls.MEDICAL_TERMS_SYSTEM}",
            f"\n[Task]\n{cls.MEDICAL_TERMS_TASK}",
            f"\n{cls.MEDICAL_TERMS_CONTEXT.format(parameters=parameters)}",
            "\n[Rules]",
            *[f"- {rule}" for rule in cls.MEDICAL_TERMS_RULES],
            f"\n[Output Format]\nReturn ONLY valid JSON (no markdown):\n{cls.MEDICAL_TERMS_OUTPUT}",
        ]
        return "\n".join(parts)
    
    @classmethod
    def build_cross_table(cls, tables_info: str) -> str:
        """Task 4: Cross-table 프롬프트 빌드"""
        parts = [
            f"[Role]\n{cls.CROSS_TABLE_SYSTEM}",
            f"\n[Task]\n{cls.CROSS_TABLE_TASK}",
            f"\n{cls.CROSS_TABLE_CONTEXT.format(tables_info=tables_info)}",
            "\n[Rules]",
            *[f"- {rule}" for rule in cls.CROSS_TABLE_RULES],
            f"\n[Output Format]\nReturn ONLY valid JSON (no markdown):\n{cls.CROSS_TABLE_OUTPUT}",
        ]
        return "\n".join(parts)

