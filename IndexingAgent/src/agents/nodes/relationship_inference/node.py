# src/agents/nodes/relationship_inference/node.py
"""
Relationship Inference + Neo4j Node

테이블 간 FK 관계를 추론하고 Neo4j에 3-Level Ontology를 구축합니다.

주요 기능:
1. FK 관계 추론 (LLM)
2. PostgreSQL table_relationships 저장
3. Neo4j 3-Level Ontology 구축:
   - Level 1: RowEntity (테이블)
   - Level 2: ConceptCategory (개념 그룹)
   - Level 3: Parameter (컬럼)
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Set

from ...state import AgentState
from ...models.llm_responses import (
    TableRelationship,
    RelationshipInferenceResponse,
    RelationshipInferenceResult,
)
from ...base import BaseNode, LLMMixin, DatabaseMixin, Neo4jMixin
from ...registry import register_node
from src.database import OntologySchemaManager
from src.database.repositories import ParameterRepository
from src.config import RelationshipInferenceConfig, LLMConfig, Neo4jConfig
from .prompts import RelationshipInferencePrompt


@register_node
class RelationshipInferenceNode(BaseNode, LLMMixin, DatabaseMixin, Neo4jMixin):
    """
    Relationship Inference + Neo4j Node (LLM-based)
    
    테이블 간 FK 관계를 추론하고 Neo4j에 3-Level Ontology를 구축합니다.
    
    주요 기능:
    1. FK 관계 추론 (LLM)
    2. PostgreSQL table_relationships 저장
    3. Neo4j 3-Level Ontology 구축
    
    Input (from state):
        - entity_identification_result: 이전 단계 완료 정보
        - data_files: 데이터 파일 목록
    
    Output:
        - relationship_inference_result: RelationshipInferenceResult 형태
        - table_relationships: TableRelationship 목록
    """
    
    name = "relationship_inference"
    description = "테이블 간 FK 관계 추론 + Neo4j 온톨로지"
    order = 900
    requires_llm = True
    
    # 프롬프트 클래스 연결
    prompt_class = RelationshipInferencePrompt
    
    # =============================================================================
    # Data Loading (Using Repository Pattern)
    # =============================================================================
    
    def _load_tables_with_entity_and_columns(self) -> List[Dict[str, Any]]:
        """
        table_entities + column_metadata + file_catalog 조인 로드
        
        Uses: EntityRepository.get_tables_with_entities(include_semantic=True)
        
        Returns:
            [
                {
                    "file_id": "uuid",
                    "file_name": "clinical_data.csv",
                    "row_represents": "surgery",
                    "entity_identifier": "caseid",
                    "row_count": 6388,
                    "filename_values": {"caseid": 1234},
                    "columns": [...]
                },
                ...
            ]
        """
        try:
            return self.entity_repo.get_tables_with_entities(include_semantic=True)
        except Exception as e:
            self.log(f"❌ Error loading tables: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _find_shared_columns(self, tables: List[Dict]) -> List[Dict[str, Any]]:
        """
        테이블 간 공유 컬럼 찾기 (rule-based FK 후보)
        
        filename_values도 가상 컬럼으로 취급하여 FK 후보에 포함
        """
        column_to_tables = {}
        
        for table in tables:
            file_name = table['file_name']
            row_count = table['row_count']
            
            # 1. 일반 컬럼
            for col in table['columns']:
                col_name = col['original_name']
                unique_count = col['unique_count']
                
                if col_name not in column_to_tables:
                    column_to_tables[col_name] = []
                
                column_to_tables[col_name].append({
                    "file_name": file_name,
                    "unique_count": unique_count,
                    "row_count": row_count,
                    "source": "column"
                })
            
            # 2. filename_values의 키도 가상 컬럼으로 추가
            filename_values = table.get('filename_values', {})
            if filename_values:
                for fv_key, fv_value in filename_values.items():
                    if fv_key not in column_to_tables:
                        column_to_tables[fv_key] = []
                    
                    # 중복 방지
                    already_exists = any(
                        t['file_name'] == file_name 
                        for t in column_to_tables[fv_key]
                    )
                    if not already_exists:
                        column_to_tables[fv_key].append({
                            "file_name": file_name,
                            "unique_count": 1,
                            "row_count": row_count,
                            "source": "filename",
                            "extracted_value": fv_value
                        })
        
        # 2개 이상 테이블에 존재하는 컬럼만 반환
        shared = []
        for col_name, table_list in column_to_tables.items():
            if len(table_list) >= 2:
                shared.append({
                    "column_name": col_name,
                    "tables": table_list
                })
        
        return shared
    
    # =============================================================================
    # LLM Context Building
    # =============================================================================
    
    def _build_tables_context(self, tables: List[Dict]) -> str:
        """LLM용 테이블 정보 context 생성"""
        lines = []
        
        for table in tables:
            lines.append(f"\n## {table['file_name']}")
            lines.append(f"- row_represents: {table['row_represents']}")
            lines.append(f"- entity_identifier: {table['entity_identifier'] or '(none)'}")
            lines.append(f"- row_count: {table['row_count']:,}")
            
            # filename_values 표시
            filename_values = table.get('filename_values', {})
            if filename_values:
                lines.append(f"- filename_values (extracted from filename): {filename_values}")
            
            # FK 후보 컬럼만 표시 (identifier role 또는 FK 패턴/개념)
            fk_candidates = [c for c in table['columns'] 
                            if c.get('column_role') == 'identifier'
                            or c.get('concept_category') in RelationshipInferenceConfig.FK_CANDIDATE_CONCEPTS
                            or any(p in (c['original_name'] or '') for p in RelationshipInferenceConfig.FK_CANDIDATE_PATTERNS)]
            
            if fk_candidates:
                lines.append("- FK candidate columns:")
                for col in fk_candidates:
                    unique_str = f"unique: {col['unique_count']:,}" if col['unique_count'] else "unique: ?"
                    role_str = f"🔑" if col.get('column_role') == 'identifier' else ""
                    concept_str = col.get('concept_category') or col.get('column_role') or '-'
                    lines.append(f"    - {col['original_name']} {role_str}({concept_str}) [{unique_str}]")
        
        return "\n".join(lines)
    
    def _build_shared_columns_context(self, shared: List[Dict]) -> str:
        """LLM용 공유 컬럼 정보 context 생성"""
        if not shared:
            return "(No shared columns found)"
        
        lines = []
        for item in shared:
            col_name = item['column_name']
            tables = item['tables']
            
            lines.append(f"\n- {col_name}:")
            for t in tables:
                unique_str = f"{t['unique_count']:,}" if t['unique_count'] else "?"
                source = t.get('source', 'column')
                source_str = " [from filename]" if source == 'filename' else ""
                
                if source == 'filename' and 'extracted_value' in t:
                    lines.append(f"    - {t['file_name']}: value={t['extracted_value']}, rows={t['row_count']:,}{source_str}")
                else:
                    lines.append(f"    - {t['file_name']}: unique={unique_str}, rows={t['row_count']:,}{source_str}")
        
        return "\n".join(lines)
    
    # =============================================================================
    # LLM Call
    # =============================================================================
    
    def _call_llm_for_relationships(
        self,
        tables: List[Dict],
        shared: List[Dict]
    ) -> Tuple[List[TableRelationship], int]:
        """
        LLM을 호출하여 FK 관계 추론
        
        Returns:
            (관계 목록, LLM 호출 횟수)
        """
        if not tables or len(tables) < 2:
            return [], 0
        
        if not shared:
            self.log("ℹ️ No shared columns - skipping LLM call", indent=1)
            return [], 0
        
        tables_context = self._build_tables_context(tables)
        shared_context = self._build_shared_columns_context(shared)
        
        # PromptTemplate을 사용하여 프롬프트 빌드
        prompt = self.prompt_class.build(
            tables_context=tables_context,
            shared_columns=shared_context
        )
        
        self.log("📤 Calling LLM for relationship inference...", indent=1)
        
        llm_calls = 0
        results = []
        
        for attempt in range(RelationshipInferenceConfig.MAX_RETRIES):
            try:
                response = self.call_llm_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
                llm_calls += 1
                
                if response and 'relationships' in response:
                    for rel_data in response['relationships']:
                        rel = TableRelationship(
                            source_table=rel_data.get('source_table', ''),
                            target_table=rel_data.get('target_table', ''),
                            source_column=rel_data.get('source_column', ''),
                            target_column=rel_data.get('target_column', ''),
                            relationship_type=rel_data.get('relationship_type', 'foreign_key'),
                            cardinality=rel_data.get('cardinality', '1:N'),
                            confidence=float(rel_data.get('confidence', 0.0)),
                            reasoning=rel_data.get('reasoning', '')
                        )
                        results.append(rel)
                    
                    return results, llm_calls
                else:
                    self.log(f"⚠️ Invalid LLM response, attempt {attempt + 1}", indent=1)
                    
            except Exception as e:
                self.log(f"❌ LLM call failed (attempt {attempt + 1}): {e}", indent=1)
                if attempt < RelationshipInferenceConfig.MAX_RETRIES - 1:
                    time.sleep(RelationshipInferenceConfig.RETRY_DELAY_SECONDS)
        
        return results, llm_calls
    
    # =============================================================================
    # PostgreSQL Save
    # =============================================================================
    
    def _save_relationships_to_postgres(
        self,
        relationships: List[TableRelationship],
        tables: List[Dict]
    ) -> int:
        """
        FK 관계를 table_relationships 테이블에 저장
        
        Returns:
            저장된 관계 수
        """
        if not relationships:
            return 0
        
        # file_name → file_id 매핑
        name_to_id = {t['file_name']: t['file_id'] for t in tables}
        
        rel_dicts = []
        for rel in relationships:
            source_id = name_to_id.get(rel.source_table)
            target_id = name_to_id.get(rel.target_table)
            
            if not source_id or not target_id:
                self.log(f"⚠️ Table not found: {rel.source_table} or {rel.target_table}", indent=1)
                continue
            
            rel_dicts.append({
                "source_file_id": source_id,
                "target_file_id": target_id,
                "source_column": rel.source_column,
                "target_column": rel.target_column,
                "relationship_type": rel.relationship_type,
                "cardinality": rel.cardinality,
                "confidence": rel.confidence,
                "reasoning": rel.reasoning
            })
        
        if rel_dicts:
            self.entity_repo.save_relationships(rel_dicts)
        
        return len(rel_dicts)
    
    # =============================================================================
    # Neo4j Sync (Using Neo4jMixin)
    # =============================================================================
    
    def _create_row_entity_nodes(self, driver, tables: List[Dict]) -> int:
        """Level 1: RowEntity 노드 생성"""
        if not driver:
            return 0
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for table in tables:
                try:
                    session.run("""
                        MERGE (e:RowEntity {file_name: $file_name})
                        SET e.file_id = $file_id,
                            e.name = $row_represents,
                            e.identifier_column = $entity_identifier,
                            e.row_count = $row_count
                    """, {
                        "file_id": table['file_id'],
                        "file_name": table['file_name'],
                        "row_represents": table['row_represents'],
                        "entity_identifier": table['entity_identifier'],
                        "row_count": table['row_count']
                    })
                    count += 1
                except Exception as e:
                    self.log(f"❌ Error creating RowEntity {table['file_name']}: {e}", indent=2)
        
        return count
    
    def _create_concept_category_nodes(self, driver, all_params: List[Dict]) -> int:
        """Level 2: ConceptCategory 노드 생성 (parameter 테이블 기반)"""
        if not driver:
            return 0
        
        concepts: Set[str] = set()
        for param in all_params:
            if param.get('concept'):
                concepts.add(param['concept'])
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for concept in concepts:
                try:
                    session.run("""
                        MERGE (c:ConceptCategory {name: $name})
                    """, {"name": concept})
                    count += 1
                except Exception as e:
                    self.log(f"❌ Error creating ConceptCategory {concept}: {e}", indent=2)
        
        return count
    
    def _create_parameter_nodes(self, driver, all_params: List[Dict]) -> int:
        """Level 3: Parameter 노드 생성 (parameter 테이블 기반, identifier 포함)"""
        if not driver:
            return 0
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for param in all_params:
                try:
                    session.run("""
                        MERGE (p:Parameter {key: $key})
                        SET p.name = $name,
                            p.unit = $unit,
                            p.concept = $concept,
                            p.is_identifier = $is_identifier
                    """, {
                        "key": param['key'],
                        "name": param['name'],
                        "unit": param['unit'],
                        "concept": param['concept'],
                        "is_identifier": param.get('is_identifier', False)
                    })
                    count += 1
                except Exception as e:
                    self.log(f"❌ Error creating Parameter {param['key']}: {e}", indent=2)
        
        return count
    
    def _create_links_to_edges(self, driver, relationships: List[TableRelationship], tables: List[Dict]) -> int:
        """RowEntity 간 FK 관계 (LINKS_TO) 생성"""
        if not driver or not relationships:
            return 0
        
        valid_names = {t['file_name'] for t in tables}
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for rel in relationships:
                if rel.source_table not in valid_names or rel.target_table not in valid_names:
                    continue
                
                try:
                    session.run("""
                        MATCH (s:RowEntity {file_name: $source_name})
                        MATCH (t:RowEntity {file_name: $target_name})
                        MERGE (s)-[r:LINKS_TO]->(t)
                        SET r.source_column = $source_column,
                            r.target_column = $target_column,
                            r.cardinality = $cardinality,
                            r.confidence = $confidence
                    """, {
                        "source_name": rel.source_table,
                        "target_name": rel.target_table,
                        "source_column": rel.source_column,
                        "target_column": rel.target_column,
                        "cardinality": rel.cardinality,
                        "confidence": rel.confidence
                    })
                    count += 1
                except Exception as e:
                    self.log(f"❌ Error creating LINKS_TO: {e}", indent=2)
        
        return count
    
    def _create_has_concept_edges(self, driver, tables: List[Dict]) -> int:
        """RowEntity → ConceptCategory (HAS_CONCEPT) 엣지 생성"""
        if not driver:
            return 0
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for table in tables:
                concepts = set(col['concept_category'] for col in table['columns'] if col['concept_category'])
                
                for concept in concepts:
                    try:
                        session.run("""
                            MATCH (e:RowEntity {file_name: $file_name})
                            MATCH (c:ConceptCategory {name: $concept})
                            MERGE (e)-[:HAS_CONCEPT]->(c)
                        """, {
                            "file_name": table['file_name'],
                            "concept": concept
                        })
                        count += 1
                    except Exception as e:
                        self.log(f"❌ Error creating HAS_CONCEPT: {e}", indent=2)
        
        return count
    
    def _create_contains_edges(self, driver, all_params: List[Dict]) -> int:
        """ConceptCategory → Parameter (CONTAINS) 엣지 생성 (parameter 테이블 기반)"""
        if not driver:
            return 0
        
        concept_to_params: Dict[str, Set[str]] = {}
        for param in all_params:
            concept = param.get('concept')
            if concept:
                if concept not in concept_to_params:
                    concept_to_params[concept] = set()
                concept_to_params[concept].add(param['key'])
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for concept, param_keys in concept_to_params.items():
                for key in param_keys:
                    try:
                        session.run("""
                            MATCH (c:ConceptCategory {name: $concept})
                            MATCH (p:Parameter {key: $key})
                            MERGE (c)-[:CONTAINS]->(p)
                        """, {
                            "concept": concept,
                            "key": key
                        })
                        count += 1
                    except Exception as e:
                        self.log(f"❌ Error creating CONTAINS: {e}", indent=2)
        
        return count
    
    def _create_has_column_edges(self, driver, tables: List[Dict]) -> int:
        """RowEntity → Parameter (HAS_COLUMN) 엣지 생성"""
        if not driver:
            return 0
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for table in tables:
                for col in table['columns']:
                    try:
                        session.run("""
                            MATCH (e:RowEntity {file_name: $file_name})
                            MATCH (p:Parameter {key: $key})
                            MERGE (e)-[:HAS_COLUMN]->(p)
                        """, {
                            "file_name": table['file_name'],
                            "key": col['original_name']
                        })
                        count += 1
                    except Exception as e:
                        self.log(f"❌ Error creating HAS_COLUMN: {e}", indent=2)
        
        return count
    
    def _load_filename_column_mappings(self) -> Dict[str, Dict[str, Any]]:
        """
        directory_catalog에서 filename_columns 매핑 정보 로드
        
        Uses: DirectoryRepository.get_filename_column_mappings()
        """
        return self.directory_repo.get_filename_column_mappings()
    
    def _create_filename_value_edges(self, driver, tables: List[Dict]) -> int:
        """filename_values에서 추출된 값을 Parameter 노드와 FILENAME_VALUE 관계로 연결"""
        if not driver:
            return 0
        
        dir_mappings = self._load_filename_column_mappings()
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for table in tables:
                filename_values = table.get('filename_values', {})
                if not filename_values:
                    continue
                
                file_name = table.get('file_name', '')
                
                for key, value in filename_values.items():
                    matched_info = None
                    semantic_role = "extracted_value"
                    confidence = 0.8
                    reasoning = "Extracted from filename pattern"
                    
                    for dir_name, col_map in dir_mappings.items():
                        if key in col_map:
                            matched_info = col_map[key]
                            break
                    
                    if matched_info:
                        matched_column = matched_info.get('matched_column') or key  # None 방지
                        confidence = matched_info.get('match_confidence', 0.8)
                        reasoning = matched_info.get('match_reasoning', reasoning)
                    else:
                        matched_column = key
                    
                    # semantic_role 결정 (matched_column은 항상 문자열)
                    matched_lower = matched_column.lower()
                    if 'id' in matched_lower or 'case' in matched_lower:
                        semantic_role = "case_identifier"
                    elif 'subject' in matched_lower or 'patient' in matched_lower:
                        semantic_role = "subject_identifier"
                    elif 'date' in matched_lower or 'time' in matched_lower:
                        semantic_role = "temporal_identifier"
                    else:
                        semantic_role = "identifier"
                    
                    try:
                        session.run("""
                            MATCH (e:RowEntity {file_name: $file_name})
                            MATCH (p:Parameter {key: $param_key})
                            MERGE (e)-[r:FILENAME_VALUE]->(p)
                            SET r.value = $value,
                                r.semantic_role = $semantic_role,
                                r.source = 'filename',
                                r.confidence = $confidence,
                                r.reasoning = $reasoning
                        """, {
                            "file_name": file_name,
                            "param_key": matched_column,
                            "value": value,
                            "semantic_role": semantic_role,
                            "confidence": confidence,
                            "reasoning": reasoning
                        })
                        count += 1
                        
                    except Exception as e:
                        self.log(f"⚠️ Error creating FILENAME_VALUE for {file_name}.{key}: {e}", indent=2)
        
        return count
    
    def _sync_to_neo4j(
        self,
        tables: List[Dict],
        relationships: List[TableRelationship]
    ) -> Dict[str, int]:
        """Neo4j 전체 동기화 (Neo4jMixin 사용)"""
        stats = {
            "row_entity_nodes": 0,
            "concept_category_nodes": 0,
            "parameter_nodes": 0,
            "edges_links_to": 0,
            "edges_has_concept": 0,
            "edges_contains": 0,
            "edges_has_column": 0,
            "edges_filename_value": 0
        }
        
        if not RelationshipInferenceConfig.NEO4J_ENABLED:
            self.log("ℹ️ Neo4j sync is disabled", indent=1)
            return stats
        
        driver = self.neo4j_driver  # Neo4jMixin 사용
        if not driver:
            self.log("⚠️ Skipping Neo4j sync (connection failed)", indent=1)
            return stats
        
        try:
            self.log("📊 Creating Neo4j nodes and edges...", indent=1)
            
            # parameter 테이블에서 모든 파라미터를 한 번만 로드 (group_common 포함)
            param_repo = ParameterRepository()
            all_params = param_repo.get_all_parameters_for_ontology()
            self.log(f"✓ Loaded {len(all_params)} parameters from DB", indent=2)
            
            # Level 1: RowEntity
            stats["row_entity_nodes"] = self._create_row_entity_nodes(driver, tables)
            self.log(f"✓ RowEntity nodes: {stats['row_entity_nodes']}", indent=2)
            
            # Level 2: ConceptCategory (parameter 테이블 기반)
            stats["concept_category_nodes"] = self._create_concept_category_nodes(driver, all_params)
            self.log(f"✓ ConceptCategory nodes: {stats['concept_category_nodes']}", indent=2)
            
            # Level 3: Parameter (parameter 테이블 기반)
            stats["parameter_nodes"] = self._create_parameter_nodes(driver, all_params)
            self.log(f"✓ Parameter nodes: {stats['parameter_nodes']}", indent=2)
            
            # Edges
            stats["edges_links_to"] = self._create_links_to_edges(driver, relationships, tables)
            self.log(f"✓ LINKS_TO edges: {stats['edges_links_to']}", indent=2)
            
            stats["edges_has_concept"] = self._create_has_concept_edges(driver, tables)
            self.log(f"✓ HAS_CONCEPT edges: {stats['edges_has_concept']}", indent=2)
            
            # CONTAINS (parameter 테이블 기반)
            stats["edges_contains"] = self._create_contains_edges(driver, all_params)
            self.log(f"✓ CONTAINS edges: {stats['edges_contains']}", indent=2)
            
            stats["edges_has_column"] = self._create_has_column_edges(driver, tables)
            self.log(f"✓ HAS_COLUMN edges: {stats['edges_has_column']}", indent=2)
            
            stats["edges_filename_value"] = self._create_filename_value_edges(driver, tables)
            self.log(f"✓ FILENAME_VALUE edges: {stats['edges_filename_value']}", indent=2)
            
        finally:
            self.close_neo4j()  # Neo4jMixin 사용
        
        return stats
    
    # =============================================================================
    # Main Execute
    # =============================================================================
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Relationship Inference + Neo4j Sync 실행
        
        1. table_entities + column_metadata 로드
        2. 공유 컬럼 탐지 (FK 후보)
        3. LLM으로 FK 관계 추론
        4. PostgreSQL table_relationships 저장
        5. Neo4j 3-Level Ontology 구축
        """
        started_at = datetime.now().isoformat()
        
        # 1. 스키마 확인
        schema_manager = OntologySchemaManager()
        schema_manager.create_tables()
        
        # 2. 테이블 정보 로드
        self.log("📥 Loading tables with entity and column info...")
        tables = self._load_tables_with_entity_and_columns()
        
        if not tables:
            self.log("⚠️ No tables found (run previous step first)")
            return {
                "relationship_inference_result": RelationshipInferenceResult(
                    started_at=started_at,
                    completed_at=datetime.now().isoformat()
                ).model_dump(),
                "table_relationships": []
            }
        
        self.log(f"✅ Loaded {len(tables)} tables", indent=1)
        for t in tables:
            self.log(f"- {t['file_name']} ({t['row_represents']}, {len(t['columns'])} columns)", indent=2)
        
        # 3. 공유 컬럼 찾기
        self.log("🔍 Finding shared columns...")
        shared_columns = self._find_shared_columns(tables)
        self.log(f"✅ Found {len(shared_columns)} shared columns", indent=1)
        for sc in shared_columns[:5]:
            self.log(f"- {sc['column_name']} (in {len(sc['tables'])} tables)", indent=2)
        
        # 4. LLM으로 FK 관계 추론
        self.log("🤖 Inferring relationships with LLM...")
        relationships, llm_calls = self._call_llm_for_relationships(tables, shared_columns)
        self.log(f"✅ Found {len(relationships)} relationships (LLM calls: {llm_calls})", indent=1)
        
        # 5. PostgreSQL 저장
        self.log("💾 Saving to PostgreSQL...")
        saved_count = self._save_relationships_to_postgres(relationships, tables)
        self.log(f"✅ Saved {saved_count} relationships", indent=1)
        
        # 6. Neo4j 동기화
        self.log("📊 Syncing to Neo4j...")
        neo4j_stats = self._sync_to_neo4j(tables, relationships)
        neo4j_synced = sum(neo4j_stats.values()) > 0
        
        # 7. 결과 통계
        high_conf = sum(1 for r in relationships if r.confidence >= RelationshipInferenceConfig.CONFIDENCE_THRESHOLD)
        
        # 8. 결과 출력
        self.log(f"Relationships found: {len(relationships)}", indent=1)
        self.log(f"High confidence (≥{RelationshipInferenceConfig.CONFIDENCE_THRESHOLD}): {high_conf}", indent=1)
        self.log(f"LLM calls: {llm_calls}", indent=1)
        
        if relationships:
            self.log("🔗 Relationships:")
            for rel in relationships:
                conf_emoji = "🟢" if rel.confidence >= RelationshipInferenceConfig.CONFIDENCE_THRESHOLD else "🟡"
                self.log(f"{conf_emoji} {rel.source_table} → {rel.target_table}", indent=1)
                self.log(f"{rel.source_column} → {rel.target_column} ({rel.cardinality})", indent=2)
                self.log(f"confidence: {rel.confidence:.2f}", indent=2)
        
        if neo4j_synced:
            self.log("📊 Neo4j Graph:")
            self.log(f"RowEntity nodes: {neo4j_stats['row_entity_nodes']}", indent=1)
            self.log(f"ConceptCategory nodes: {neo4j_stats['concept_category_nodes']}", indent=1)
            self.log(f"Parameter nodes: {neo4j_stats['parameter_nodes']}", indent=1)
            self.log(f"LINKS_TO edges: {neo4j_stats['edges_links_to']}", indent=1)
            self.log(f"HAS_CONCEPT edges: {neo4j_stats['edges_has_concept']}", indent=1)
            self.log(f"CONTAINS edges: {neo4j_stats['edges_contains']}", indent=1)
            self.log(f"HAS_COLUMN edges: {neo4j_stats['edges_has_column']}", indent=1)
        
        # 9. 결과 반환
        completed_at = datetime.now().isoformat()
        
        phase_result = RelationshipInferenceResult(
            relationships_found=len(relationships),
            relationships_high_conf=high_conf,
            row_entity_nodes=neo4j_stats['row_entity_nodes'],
            concept_category_nodes=neo4j_stats['concept_category_nodes'],
            parameter_nodes=neo4j_stats['parameter_nodes'],
            edges_links_to=neo4j_stats['edges_links_to'],
            edges_has_concept=neo4j_stats['edges_has_concept'],
            edges_contains=neo4j_stats['edges_contains'],
            edges_has_column=neo4j_stats['edges_has_column'],
            llm_calls=llm_calls,
            neo4j_synced=neo4j_synced,
            started_at=started_at,
            completed_at=completed_at
        )
        
        return {
            "relationship_inference_result": phase_result.model_dump(),
            "table_relationships": [r.model_dump() for r in relationships]
        }
    
    @classmethod
    def run_standalone(cls) -> Dict[str, Any]:
        """
        단독 실행용 메서드 (테스트용)
        
        Returns:
            실행 결과 state
        """
        node = cls()
        return node({})

