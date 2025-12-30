# src/agents/nodes/ontology_enhancement.py
"""
Phase 10: Ontology Enhancement Node

Phase 9에서 구축한 3-Level 온톨로지를 LLM을 활용해 확장/강화합니다.

Tasks:
1. Concept Hierarchy: ConceptCategory를 SubCategory로 세분화
2. Semantic Edges: Parameter 간 의미 관계 (DERIVED_FROM, RELATED_TO)
3. Medical Term Mapping: SNOMED-CT, LOINC 등 표준 용어 매핑
4. Cross-table Semantics: 테이블 간 숨겨진 시맨틱 관계
"""

import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Set

from ..state import AgentState
from ..models.llm_responses import (
    SubCategoryResult,
    ConceptHierarchyResponse,
    SemanticEdge,
    SemanticEdgesResponse,
    MedicalTermMapping,
    MedicalTermResponse,
    CrossTableSemantic,
    CrossTableResponse,
    Phase10Result,
)
from src.database.connection import get_db_manager
from src.database.schema_ontology import OntologySchemaManager
from src.utils.llm_client import get_llm_client
from src.config import Phase10Config, LLMConfig, Neo4jConfig


# =============================================================================
# LLM Prompts
# =============================================================================

CONCEPT_HIERARCHY_PROMPT = """You are a Medical Data Expert analyzing clinical data concepts.

[Task]
Analyze the following concept categories and their parameters.
Propose meaningful subcategories to organize parameters better.

[Current Concept Categories]
{concept_categories}

[Rules]
1. Only create subcategories when there are 3+ parameters that fit naturally
2. Subcategory names should be specific and medically meaningful
3. Each parameter should belong to exactly one subcategory
4. Not all categories need subcategories

[Output Format]
Return ONLY valid JSON (no markdown):
{{
  "subcategories": [
    {{
      "parent_category": "Vitals",
      "subcategory_name": "Cardiovascular",
      "parameters": ["hr", "sbp", "dbp", "map"],
      "confidence": 0.95,
      "reasoning": "Heart rate and blood pressures are cardiovascular parameters"
    }},
    {{
      "parent_category": "Vitals",
      "subcategory_name": "Respiratory",
      "parameters": ["rr", "spo2", "etco2"],
      "confidence": 0.92,
      "reasoning": "Respiratory rate and oxygen-related parameters"
    }}
  ]
}}

If no meaningful subcategories can be created:
{{"subcategories": []}}
"""

SEMANTIC_EDGES_PROMPT = """You are a Medical Data Expert analyzing relationships between clinical parameters.

[Task]
Identify semantic relationships between the following parameters.

[Parameters]
{parameters}

[Relationship Types]
- DERIVED_FROM: Parameter A is calculated/derived from Parameter B
  Example: bmi DERIVED_FROM height, bmi DERIVED_FROM weight
- RELATED_TO: Parameters are medically/clinically related
  Example: sbp RELATED_TO dbp (both blood pressures)
- OPPOSITE_OF: Parameters represent opposite concepts (rare)

[Rules]
1. Only include relationships with high confidence (≥0.8)
2. DERIVED_FROM should be factually correct (mathematical derivation)
3. RELATED_TO should be clinically meaningful, not just co-occurrence

[Output Format]
Return ONLY valid JSON (no markdown):
{{
  "edges": [
    {{
      "source_parameter": "bmi",
      "target_parameter": "height",
      "relationship_type": "DERIVED_FROM",
      "confidence": 0.99,
      "reasoning": "BMI is calculated using height: BMI = weight / height^2"
    }},
    {{
      "source_parameter": "sbp",
      "target_parameter": "dbp",
      "relationship_type": "RELATED_TO",
      "confidence": 0.95,
      "reasoning": "Both are components of blood pressure measurement"
    }}
  ]
}}

If no relationships found:
{{"edges": []}}
"""

MEDICAL_TERM_PROMPT = """You are a Medical Terminology Expert.

[Task]
Map the following clinical parameters to standard medical terminologies.

[Parameters to Map]
{parameters}

[Target Terminologies]
1. SNOMED-CT: Clinical concepts (provide concept ID and preferred term)
2. LOINC: Lab and clinical observations (provide code and name)
3. ICD-10: Diagnoses (only if applicable, e.g., for conditions)

[Rules]
1. Only include mappings you are confident about (≥0.8)
2. Use actual SNOMED-CT concept IDs (numeric)
3. Use actual LOINC codes (format: XXXXX-X)
4. Leave null if no appropriate mapping exists

[Output Format]
Return ONLY valid JSON (no markdown):
{{
  "mappings": [
    {{
      "parameter_key": "hr",
      "snomed_code": "364075005",
      "snomed_name": "Heart rate",
      "loinc_code": "8867-4",
      "loinc_name": "Heart rate",
      "icd10_code": null,
      "icd10_name": null,
      "confidence": 0.95
    }},
    {{
      "parameter_key": "sbp",
      "snomed_code": "271649006",
      "snomed_name": "Systolic blood pressure",
      "loinc_code": "8480-6",
      "loinc_name": "Systolic blood pressure",
      "icd10_code": null,
      "icd10_name": null,
      "confidence": 0.95
    }}
  ]
}}
"""

CROSS_TABLE_PROMPT = """You are a Medical Data Expert analyzing relationships between columns across different tables.

[Task]
Identify columns that represent the same or similar concepts across different tables.

[Tables and Columns]
{tables_info}

[Rules]
1. Look for semantic equivalence, not just name matching
2. Consider unit differences (e.g., preop_hb in g/dL vs lab value)
3. Only include high-confidence relationships (≥0.8)

[Output Format]
Return ONLY valid JSON (no markdown):
{{
  "semantics": [
    {{
      "source_table": "clinical_data.csv",
      "source_column": "preop_hb",
      "target_table": "lab_data.csv",
      "target_column": "value",
      "relationship_type": "SAME_CONCEPT",
      "confidence": 0.85,
      "reasoning": "preop_hb is preoperative hemoglobin, which would be a lab value with name='Hb'"
    }}
  ]
}}

If no cross-table relationships found:
{{"semantics": []}}
"""


# =============================================================================
# Helper: Data Loading
# =============================================================================

def _load_concept_categories_with_parameters() -> Dict[str, List[Dict]]:
    """
    ConceptCategory와 해당 Parameter 목록 로드
    
    Returns:
        {"Vitals": [{"key": "hr", "name": "Heart Rate", "unit": "bpm"}, ...], ...}
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    concept_params = {}
    
    try:
        cursor.execute("""
            SELECT concept_category, original_name, semantic_name, unit
            FROM column_metadata
            WHERE concept_category IS NOT NULL
            ORDER BY concept_category, original_name
        """)
        
        for row in cursor.fetchall():
            concept, orig_name, sem_name, unit = row
            
            if concept not in concept_params:
                concept_params[concept] = []
            
            concept_params[concept].append({
                "key": orig_name,
                "name": sem_name or orig_name,
                "unit": unit
            })
    
    except Exception as e:
        print(f"❌ [Phase10] Error loading concepts: {e}")
    
    return concept_params


def _load_all_parameters() -> List[Dict[str, Any]]:
    """
    모든 Parameter 정보 로드
    
    Returns:
        [{"key": "hr", "name": "Heart Rate", "unit": "bpm", "concept": "Vitals"}, ...]
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    parameters = []
    seen_keys = set()
    
    try:
        cursor.execute("""
            SELECT original_name, semantic_name, unit, concept_category
            FROM column_metadata
            ORDER BY original_name
        """)
        
        for row in cursor.fetchall():
            orig_name, sem_name, unit, concept = row
            
            if orig_name not in seen_keys:
                seen_keys.add(orig_name)
                parameters.append({
                    "key": orig_name,
                    "name": sem_name or orig_name,
                    "unit": unit,
                    "concept": concept
                })
    
    except Exception as e:
        print(f"❌ [Phase10] Error loading parameters: {e}")
    
    return parameters


def _load_tables_with_columns() -> List[Dict[str, Any]]:
    """
    테이블별 컬럼 정보 로드
    
    Returns:
        [{"file_name": "...", "file_id": "...", "columns": [...]}, ...]
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    tables = []
    
    try:
        # 테이블 정보
        cursor.execute("""
            SELECT fc.file_id, fc.file_name
            FROM file_catalog fc
            WHERE fc.is_metadata = false
        """)
        
        table_rows = cursor.fetchall()
        
        for file_id, file_name in table_rows:
            # 컬럼 정보
            cursor.execute("""
                SELECT original_name, semantic_name, concept_category, unit
                FROM column_metadata
                WHERE file_id = %s
            """, (str(file_id),))
            
            columns = []
            for col_row in cursor.fetchall():
                orig, sem, concept, unit = col_row
                columns.append({
                    "original_name": orig,
                    "semantic_name": sem or orig,
                    "concept_category": concept,
                    "unit": unit
                })
            
            tables.append({
                "file_id": str(file_id),
                "file_name": file_name,
                "columns": columns
            })
    
    except Exception as e:
        print(f"❌ [Phase10] Error loading tables: {e}")
    
    return tables


# =============================================================================
# Task 1: Concept Hierarchy
# =============================================================================

def _build_concept_context(concept_params: Dict[str, List[Dict]]) -> str:
    """LLM용 concept context 생성"""
    lines = []
    
    for concept, params in sorted(concept_params.items()):
        lines.append(f"\n## {concept} ({len(params)} parameters)")
        for p in params[:15]:  # 최대 15개
            unit_str = f" ({p['unit']})" if p['unit'] else ""
            lines.append(f"  - {p['key']}: {p['name']}{unit_str}")
        if len(params) > 15:
            lines.append(f"  ... and {len(params) - 15} more")
    
    return "\n".join(lines)


def _enhance_concept_hierarchy(concept_params: Dict[str, List[Dict]]) -> Tuple[List[SubCategoryResult], int]:
    """
    Task 1: ConceptCategory → SubCategory 세분화
    
    Returns:
        (SubCategoryResult 목록, LLM 호출 횟수)
    """
    if not Phase10Config.ENABLE_CONCEPT_HIERARCHY:
        return [], 0
    
    if not concept_params:
        return [], 0
    
    llm_client = get_llm_client()
    context = _build_concept_context(concept_params)
    
    prompt = CONCEPT_HIERARCHY_PROMPT.format(concept_categories=context)
    
    print("   🤖 Calling LLM for concept hierarchy...")
    
    try:
        response = llm_client.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
        
        if response and 'subcategories' in response:
            results = []
            for subcat in response['subcategories']:
                results.append(SubCategoryResult(
                    parent_category=subcat.get('parent_category', ''),
                    subcategory_name=subcat.get('subcategory_name', ''),
                    parameters=subcat.get('parameters', []),
                    confidence=float(subcat.get('confidence', 0.0)),
                    reasoning=subcat.get('reasoning', '')
                ))
            return results, 1
    
    except Exception as e:
        print(f"   ❌ LLM call failed: {e}")
    
    return [], 1


# =============================================================================
# Task 2: Semantic Edges
# =============================================================================

def _build_parameters_context(parameters: List[Dict], batch_size: int = 30) -> List[str]:
    """LLM용 parameter context 배치 생성"""
    batches = []
    
    for i in range(0, len(parameters), batch_size):
        batch = parameters[i:i + batch_size]
        lines = []
        for p in batch:
            unit_str = f" ({p['unit']})" if p['unit'] else ""
            concept_str = f" [{p['concept']}]" if p['concept'] else ""
            lines.append(f"- {p['key']}: {p['name']}{unit_str}{concept_str}")
        batches.append("\n".join(lines))
    
    return batches


def _infer_semantic_relationships(parameters: List[Dict]) -> Tuple[List[SemanticEdge], int]:
    """
    Task 2: Parameter 간 의미 관계 추론
    
    Returns:
        (SemanticEdge 목록, LLM 호출 횟수)
    """
    if not Phase10Config.ENABLE_SEMANTIC_EDGES:
        return [], 0
    
    if not parameters:
        return [], 0
    
    llm_client = get_llm_client()
    batches = _build_parameters_context(parameters, Phase10Config.PARAMETER_BATCH_SIZE)
    
    all_edges = []
    llm_calls = 0
    
    for i, batch_context in enumerate(batches):
        print(f"   🤖 Semantic edges batch {i+1}/{len(batches)}...")
        
        prompt = SEMANTIC_EDGES_PROMPT.format(parameters=batch_context)
        
        try:
            response = llm_client.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
            llm_calls += 1
            
            if response and 'edges' in response:
                for edge in response['edges']:
                    all_edges.append(SemanticEdge(
                        source_parameter=edge.get('source_parameter', ''),
                        target_parameter=edge.get('target_parameter', ''),
                        relationship_type=edge.get('relationship_type', 'RELATED_TO'),
                        confidence=float(edge.get('confidence', 0.0)),
                        reasoning=edge.get('reasoning', '')
                    ))
        
        except Exception as e:
            print(f"   ❌ LLM call failed: {e}")
            llm_calls += 1
    
    return all_edges, llm_calls


# =============================================================================
# Task 3: Medical Term Mapping
# =============================================================================

def _map_medical_terms(parameters: List[Dict]) -> Tuple[List[MedicalTermMapping], int]:
    """
    Task 3: 표준 의학 용어 매핑
    
    Returns:
        (MedicalTermMapping 목록, LLM 호출 횟수)
    """
    if not Phase10Config.ENABLE_MEDICAL_TERMS:
        return [], 0
    
    if not parameters:
        return [], 0
    
    llm_client = get_llm_client()
    batches = _build_parameters_context(parameters, Phase10Config.MEDICAL_TERM_BATCH_SIZE)
    
    all_mappings = []
    llm_calls = 0
    
    for i, batch_context in enumerate(batches):
        print(f"   🤖 Medical terms batch {i+1}/{len(batches)}...")
        
        prompt = MEDICAL_TERM_PROMPT.format(parameters=batch_context)
        
        try:
            response = llm_client.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
            llm_calls += 1
            
            if response and 'mappings' in response:
                for mapping in response['mappings']:
                    all_mappings.append(MedicalTermMapping(
                        parameter_key=mapping.get('parameter_key', ''),
                        snomed_code=mapping.get('snomed_code'),
                        snomed_name=mapping.get('snomed_name'),
                        loinc_code=mapping.get('loinc_code'),
                        loinc_name=mapping.get('loinc_name'),
                        icd10_code=mapping.get('icd10_code'),
                        icd10_name=mapping.get('icd10_name'),
                        confidence=float(mapping.get('confidence', 0.0))
                    ))
        
        except Exception as e:
            print(f"   ❌ LLM call failed: {e}")
            llm_calls += 1
    
    return all_mappings, llm_calls


# =============================================================================
# Task 4: Cross-table Semantics
# =============================================================================

def _build_tables_context(tables: List[Dict]) -> str:
    """LLM용 tables context 생성"""
    lines = []
    
    for table in tables:
        lines.append(f"\n## {table['file_name']}")
        for col in table['columns'][:20]:  # 최대 20개
            concept_str = f" [{col['concept_category']}]" if col['concept_category'] else ""
            unit_str = f" ({col['unit']})" if col['unit'] else ""
            lines.append(f"  - {col['original_name']}: {col['semantic_name']}{unit_str}{concept_str}")
        if len(table['columns']) > 20:
            lines.append(f"  ... and {len(table['columns']) - 20} more")
    
    return "\n".join(lines)


def _find_cross_table_semantics(tables: List[Dict]) -> Tuple[List[CrossTableSemantic], int]:
    """
    Task 4: 테이블 간 시맨틱 관계 탐지
    
    Returns:
        (CrossTableSemantic 목록, LLM 호출 횟수)
    """
    if not Phase10Config.ENABLE_CROSS_TABLE:
        return [], 0
    
    if len(tables) < 2:
        return [], 0
    
    llm_client = get_llm_client()
    context = _build_tables_context(tables)
    
    prompt = CROSS_TABLE_PROMPT.format(tables_info=context)
    
    print("   🤖 Calling LLM for cross-table semantics...")
    
    try:
        response = llm_client.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
        
        if response and 'semantics' in response:
            results = []
            for sem in response['semantics']:
                results.append(CrossTableSemantic(
                    source_table=sem.get('source_table', ''),
                    source_column=sem.get('source_column', ''),
                    target_table=sem.get('target_table', ''),
                    target_column=sem.get('target_column', ''),
                    relationship_type=sem.get('relationship_type', 'SEMANTICALLY_SIMILAR'),
                    confidence=float(sem.get('confidence', 0.0)),
                    reasoning=sem.get('reasoning', '')
                ))
            return results, 1
    
    except Exception as e:
        print(f"   ❌ LLM call failed: {e}")
    
    return [], 1


# =============================================================================
# PostgreSQL Save
# =============================================================================

def _save_to_postgres(
    subcategories: List[SubCategoryResult],
    edges: List[SemanticEdge],
    mappings: List[MedicalTermMapping],
    cross_semantics: List[CrossTableSemantic],
    tables: List[Dict]
):
    """모든 결과를 PostgreSQL에 저장"""
    schema_manager = OntologySchemaManager()
    
    # Task 1: Subcategories
    if subcategories:
        subcat_dicts = [
            {
                "parent_category": s.parent_category,
                "subcategory_name": s.subcategory_name,
                "confidence": s.confidence,
                "reasoning": s.reasoning
            }
            for s in subcategories
        ]
        schema_manager.save_subcategories(subcat_dicts)
    
    # Task 2: Semantic Edges
    if edges:
        edge_dicts = [
            {
                "source_parameter": e.source_parameter,
                "target_parameter": e.target_parameter,
                "relationship_type": e.relationship_type,
                "confidence": e.confidence,
                "reasoning": e.reasoning
            }
            for e in edges
        ]
        schema_manager.save_semantic_edges(edge_dicts)
    
    # Task 3: Medical Terms
    if mappings:
        mapping_dicts = [
            {
                "parameter_key": m.parameter_key,
                "snomed_code": m.snomed_code,
                "snomed_name": m.snomed_name,
                "loinc_code": m.loinc_code,
                "loinc_name": m.loinc_name,
                "icd10_code": m.icd10_code,
                "icd10_name": m.icd10_name,
                "confidence": m.confidence
            }
            for m in mappings
        ]
        schema_manager.save_medical_term_mappings(mapping_dicts)
    
    # Task 4: Cross-table Semantics
    if cross_semantics:
        # file_name → file_id 매핑
        name_to_id = {t['file_name']: t['file_id'] for t in tables}
        
        cross_dicts = []
        for cs in cross_semantics:
            source_id = name_to_id.get(cs.source_table)
            target_id = name_to_id.get(cs.target_table)
            
            if source_id and target_id:
                cross_dicts.append({
                    "source_file_id": source_id,
                    "source_column": cs.source_column,
                    "target_file_id": target_id,
                    "target_column": cs.target_column,
                    "relationship_type": cs.relationship_type,
                    "confidence": cs.confidence,
                    "reasoning": cs.reasoning
                })
        
        if cross_dicts:
            schema_manager.save_cross_table_semantics(cross_dicts)


# =============================================================================
# Neo4j Sync
# =============================================================================

def _get_neo4j_driver():
    """Neo4j 드라이버 가져오기"""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            Neo4jConfig.URI,
            auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
        )
        driver.verify_connectivity()
        return driver
    except Exception as e:
        print(f"   ⚠️ Neo4j connection failed: {e}")
        return None


def _sync_subcategories_to_neo4j(driver, subcategories: List[SubCategoryResult]) -> int:
    """SubCategory 노드와 관계 생성"""
    if not driver or not subcategories:
        return 0
    
    count = 0
    with driver.session(database=Neo4jConfig.DATABASE) as session:
        for subcat in subcategories:
            try:
                # SubCategory 노드 생성
                session.run("""
                    MERGE (sc:SubCategory {name: $name})
                    SET sc.parent = $parent,
                        sc.confidence = $confidence
                """, {
                    "name": subcat.subcategory_name,
                    "parent": subcat.parent_category,
                    "confidence": subcat.confidence
                })
                
                # ConceptCategory → SubCategory 관계
                session.run("""
                    MATCH (c:ConceptCategory {name: $parent})
                    MATCH (sc:SubCategory {name: $name})
                    MERGE (c)-[:HAS_SUBCATEGORY]->(sc)
                """, {
                    "parent": subcat.parent_category,
                    "name": subcat.subcategory_name
                })
                
                # SubCategory → Parameter 관계
                for param_key in subcat.parameters:
                    session.run("""
                        MATCH (sc:SubCategory {name: $subcat_name})
                        MATCH (p:Parameter {key: $param_key})
                        MERGE (sc)-[:CONTAINS]->(p)
                    """, {
                        "subcat_name": subcat.subcategory_name,
                        "param_key": param_key
                    })
                
                count += 1
            except Exception as e:
                print(f"   ❌ Error creating SubCategory {subcat.subcategory_name}: {e}")
    
    return count


def _sync_semantic_edges_to_neo4j(driver, edges: List[SemanticEdge]) -> int:
    """Semantic Edge 관계 생성"""
    if not driver or not edges:
        return 0
    
    count = 0
    with driver.session(database=Neo4jConfig.DATABASE) as session:
        for edge in edges:
            try:
                # 관계 타입에 따라 다른 Cypher 실행
                session.run(f"""
                    MATCH (s:Parameter {{key: $source}})
                    MATCH (t:Parameter {{key: $target}})
                    MERGE (s)-[r:{edge.relationship_type}]->(t)
                    SET r.confidence = $confidence,
                        r.reasoning = $reasoning
                """, {
                    "source": edge.source_parameter,
                    "target": edge.target_parameter,
                    "confidence": edge.confidence,
                    "reasoning": edge.reasoning
                })
                count += 1
            except Exception as e:
                print(f"   ❌ Error creating edge {edge.source_parameter}->{edge.target_parameter}: {e}")
    
    return count


def _sync_medical_terms_to_neo4j(driver, mappings: List[MedicalTermMapping]) -> int:
    """MedicalTerm 노드와 MAPS_TO 관계 생성"""
    if not driver or not mappings:
        return 0
    
    count = 0
    with driver.session(database=Neo4jConfig.DATABASE) as session:
        for mapping in mappings:
            try:
                # SNOMED 매핑
                if mapping.snomed_code:
                    session.run("""
                        MERGE (mt:MedicalTerm {code: $code, system: 'SNOMED-CT'})
                        SET mt.name = $name
                        WITH mt
                        MATCH (p:Parameter {key: $param_key})
                        MERGE (p)-[:MAPS_TO]->(mt)
                    """, {
                        "code": mapping.snomed_code,
                        "name": mapping.snomed_name,
                        "param_key": mapping.parameter_key
                    })
                    count += 1
                
                # LOINC 매핑
                if mapping.loinc_code:
                    session.run("""
                        MERGE (mt:MedicalTerm {code: $code, system: 'LOINC'})
                        SET mt.name = $name
                        WITH mt
                        MATCH (p:Parameter {key: $param_key})
                        MERGE (p)-[:MAPS_TO]->(mt)
                    """, {
                        "code": mapping.loinc_code,
                        "name": mapping.loinc_name,
                        "param_key": mapping.parameter_key
                    })
                    count += 1
                    
            except Exception as e:
                print(f"   ❌ Error creating MedicalTerm for {mapping.parameter_key}: {e}")
    
    return count


def _sync_cross_table_to_neo4j(driver, cross_semantics: List[CrossTableSemantic], tables: List[Dict]) -> int:
    """Cross-table semantic 관계 생성"""
    if not driver or not cross_semantics:
        return 0
    
    # file_name → file_id 매핑
    name_to_id = {t['file_name']: t['file_id'] for t in tables}
    
    count = 0
    with driver.session(database=Neo4jConfig.DATABASE) as session:
        for cs in cross_semantics:
            source_id = name_to_id.get(cs.source_table)
            target_id = name_to_id.get(cs.target_table)
            
            if not source_id or not target_id:
                continue
            
            try:
                session.run(f"""
                    MATCH (s:RowEntity {{file_id: $source_id}})
                    MATCH (t:RowEntity {{file_id: $target_id}})
                    MERGE (s)-[r:{cs.relationship_type}]->(t)
                    SET r.source_column = $source_col,
                        r.target_column = $target_col,
                        r.confidence = $confidence,
                        r.reasoning = $reasoning
                """, {
                    "source_id": source_id,
                    "target_id": target_id,
                    "source_col": cs.source_column,
                    "target_col": cs.target_column,
                    "confidence": cs.confidence,
                    "reasoning": cs.reasoning
                })
                count += 1
            except Exception as e:
                print(f"   ❌ Error creating cross-table semantic: {e}")
    
    return count


def _sync_to_neo4j(
    subcategories: List[SubCategoryResult],
    edges: List[SemanticEdge],
    mappings: List[MedicalTermMapping],
    cross_semantics: List[CrossTableSemantic],
    tables: List[Dict]
) -> Dict[str, int]:
    """Neo4j 전체 동기화"""
    stats = {
        "subcategory_nodes": 0,
        "medical_term_nodes": 0,
        "semantic_edges": 0,
        "cross_table_edges": 0
    }
    
    if not Phase10Config.NEO4J_ENABLED:
        print("   ℹ️ Neo4j sync is disabled")
        return stats
    
    driver = _get_neo4j_driver()
    if not driver:
        print("   ⚠️ Skipping Neo4j sync (connection failed)")
        return stats
    
    try:
        print("   📊 Syncing enhancements to Neo4j...")
        
        stats["subcategory_nodes"] = _sync_subcategories_to_neo4j(driver, subcategories)
        print(f"      ✓ SubCategory nodes: {stats['subcategory_nodes']}")
        
        stats["semantic_edges"] = _sync_semantic_edges_to_neo4j(driver, edges)
        print(f"      ✓ Semantic edges: {stats['semantic_edges']}")
        
        stats["medical_term_nodes"] = _sync_medical_terms_to_neo4j(driver, mappings)
        print(f"      ✓ MedicalTerm nodes: {stats['medical_term_nodes']}")
        
        stats["cross_table_edges"] = _sync_cross_table_to_neo4j(driver, cross_semantics, tables)
        print(f"      ✓ Cross-table edges: {stats['cross_table_edges']}")
        
    finally:
        driver.close()
    
    return stats


# =============================================================================
# Main Node
# =============================================================================

def phase10_ontology_enhancement_node(state: AgentState) -> Dict[str, Any]:
    """
    Phase 10: Ontology Enhancement
    
    1. Concept Hierarchy: ConceptCategory를 SubCategory로 세분화
    2. Semantic Edges: Parameter 간 의미 관계 추론
    3. Medical Term Mapping: SNOMED-CT, LOINC 매핑
    4. Cross-table Semantics: 테이블 간 시맨틱 관계 탐지
    
    Returns:
        - phase10_result: Phase10Result 형태
        - ontology_subcategories: SubCategoryResult 목록
        - semantic_edges: SemanticEdge 목록
        - medical_term_mappings: MedicalTermMapping 목록
        - cross_table_semantics: CrossTableSemantic 목록
    """
    print("\n" + "="*60)
    print("🌳 Phase 10: Ontology Enhancement")
    print("="*60)
    
    started_at = datetime.now().isoformat()
    total_llm_calls = 0
    
    # 스키마 확인
    schema_manager = OntologySchemaManager()
    schema_manager.create_tables()
    
    # =========================================================================
    # Task 1: Concept Hierarchy
    # =========================================================================
    print("\n📁 Task 1: Concept Hierarchy")
    concept_params = _load_concept_categories_with_parameters()
    print(f"   Loaded {len(concept_params)} concept categories")
    
    subcategories, llm1 = _enhance_concept_hierarchy(concept_params)
    total_llm_calls += llm1
    print(f"   ✅ Created {len(subcategories)} subcategories")
    
    # =========================================================================
    # Task 2: Semantic Edges
    # =========================================================================
    print("\n🔗 Task 2: Semantic Edges")
    parameters = _load_all_parameters()
    print(f"   Loaded {len(parameters)} unique parameters")
    
    edges, llm2 = _infer_semantic_relationships(parameters)
    total_llm_calls += llm2
    
    derived_from = sum(1 for e in edges if e.relationship_type == 'DERIVED_FROM')
    related_to = sum(1 for e in edges if e.relationship_type == 'RELATED_TO')
    print(f"   ✅ Created {len(edges)} semantic edges (DERIVED_FROM: {derived_from}, RELATED_TO: {related_to})")
    
    # =========================================================================
    # Task 3: Medical Term Mapping
    # =========================================================================
    print("\n🏥 Task 3: Medical Term Mapping")
    mappings, llm3 = _map_medical_terms(parameters)
    total_llm_calls += llm3
    
    snomed_count = sum(1 for m in mappings if m.snomed_code)
    loinc_count = sum(1 for m in mappings if m.loinc_code)
    print(f"   ✅ Created {len(mappings)} mappings (SNOMED: {snomed_count}, LOINC: {loinc_count})")
    
    # =========================================================================
    # Task 4: Cross-table Semantics
    # =========================================================================
    print("\n🔄 Task 4: Cross-table Semantics")
    tables = _load_tables_with_columns()
    print(f"   Loaded {len(tables)} tables")
    
    cross_semantics, llm4 = _find_cross_table_semantics(tables)
    total_llm_calls += llm4
    print(f"   ✅ Found {len(cross_semantics)} cross-table semantics")
    
    # =========================================================================
    # Save to PostgreSQL
    # =========================================================================
    print("\n💾 Saving to PostgreSQL...")
    _save_to_postgres(subcategories, edges, mappings, cross_semantics, tables)
    
    # =========================================================================
    # Sync to Neo4j
    # =========================================================================
    print("\n📊 Syncing to Neo4j...")
    neo4j_stats = _sync_to_neo4j(subcategories, edges, mappings, cross_semantics, tables)
    neo4j_synced = sum(neo4j_stats.values()) > 0
    
    # =========================================================================
    # Summary
    # =========================================================================
    high_conf_subcats = sum(1 for s in subcategories if s.confidence >= Phase10Config.CONFIDENCE_THRESHOLD)
    
    print("\n" + "-"*60)
    print("📊 Phase 10 Summary:")
    print(f"   Task 1 - Subcategories: {len(subcategories)} (high conf: {high_conf_subcats})")
    print(f"   Task 2 - Semantic Edges: {len(edges)} (DERIVED: {derived_from}, RELATED: {related_to})")
    print(f"   Task 3 - Medical Terms: {len(mappings)} (SNOMED: {snomed_count}, LOINC: {loinc_count})")
    print(f"   Task 4 - Cross-table: {len(cross_semantics)}")
    print(f"   LLM calls: {total_llm_calls}")
    print(f"   Neo4j synced: {neo4j_synced}")
    
    # 결과 생성
    completed_at = datetime.now().isoformat()
    
    phase10_result = Phase10Result(
        subcategories_created=len(subcategories),
        subcategories_high_conf=high_conf_subcats,
        semantic_edges_created=len(edges),
        derived_from_edges=derived_from,
        related_to_edges=related_to,
        medical_terms_mapped=len(mappings),
        snomed_mappings=snomed_count,
        loinc_mappings=loinc_count,
        cross_table_semantics=len(cross_semantics),
        neo4j_subcategory_nodes=neo4j_stats['subcategory_nodes'],
        neo4j_medical_term_nodes=neo4j_stats['medical_term_nodes'],
        neo4j_semantic_edges=neo4j_stats['semantic_edges'],
        neo4j_cross_table_edges=neo4j_stats['cross_table_edges'],
        llm_calls=total_llm_calls,
        neo4j_synced=neo4j_synced,
        started_at=started_at,
        completed_at=completed_at
    )
    
    return {
        "phase10_result": phase10_result.model_dump(),
        "ontology_subcategories": [s.model_dump() for s in subcategories],
        "semantic_edges": [e.model_dump() for e in edges],
        "medical_term_mappings": [m.model_dump() for m in mappings],
        "cross_table_semantics": [cs.model_dump() for cs in cross_semantics]
    }

