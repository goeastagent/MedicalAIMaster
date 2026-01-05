# src/agents/nodes/ontology_enhancement/node.py
"""
Ontology Enhancement Node

이전 단계에서 구축한 3-Level 온톨로지를 LLM을 활용해 확장/강화합니다.

Tasks:
1. Concept Hierarchy: ConceptCategory를 SubCategory로 세분화
2. Semantic Edges: Parameter 간 의미 관계 (DERIVED_FROM, RELATED_TO)
3. Medical Term Mapping: SNOMED-CT, LOINC 등 표준 용어 매핑
4. Cross-table Semantics: 테이블 간 숨겨진 시맨틱 관계
"""

from datetime import datetime
from typing import Dict, List, Any, Tuple

from ...models.llm_responses import (
    SubCategoryResult,
    SemanticEdge,
    MedicalTermMapping,
    CrossTableSemantic,
    OntologyEnhancementResult,
)
from ...base import BaseNode, LLMMixin, DatabaseMixin, Neo4jMixin
from ...registry import register_node
from shared.database import OntologySchemaManager, OntologyRepository
from src.config import OntologyEnhancementConfig
from shared.config import LLMConfig, Neo4jConfig
from .prompts import OntologyEnhancementPrompts


@register_node
class OntologyEnhancementNode(BaseNode, LLMMixin, DatabaseMixin, Neo4jMixin):
    """
    Ontology Enhancement Node (LLM-based)
    
    Neo4j 온톨로지를 확장/강화합니다:
    1. Concept Hierarchy: ConceptCategory를 SubCategory로 세분화
    2. Semantic Edges: Parameter 간 의미 관계
    3. Medical Term Mapping: SNOMED-CT, LOINC 매핑
    4. Cross-table Semantics: 테이블 간 숨겨진 시맨틱 관계
    
    Output:
        - ontology_enhancement_result: OntologyEnhancementResult 형태
        - ontology_subcategories: SubCategoryResult 목록
        - semantic_edges: SemanticEdge 목록
        - medical_term_mappings: MedicalTermMapping 목록
        - cross_table_semantics: CrossTableSemantic 목록
    """
    
    name = "ontology_enhancement"
    description = "온톨로지 확장 (계층화, 의미관계, 용어매핑)"
    order = 1000
    requires_llm = True
    
    # 프롬프트 클래스 연결
    prompt_class = OntologyEnhancementPrompts
    
    # =============================================================================
    # Data Loading (Using Repository Pattern)
    # =============================================================================
    
    def _load_concept_categories_with_parameters(self) -> Dict[str, List[Dict]]:
        """
        ConceptCategory와 해당 Parameter 목록 로드
        
        Uses: ParameterRepository.get_parameters_by_concept()
        
        Returns:
            {"Vitals": [{"key": "hr", "name": "Heart Rate", "unit": "bpm"}, ...], ...}
        """
        try:
            return self.parameter_repo.get_parameters_by_concept()
        except Exception as e:
            self.log(f"❌ Error loading concepts: {e}")
            return {}
    
    def _load_all_parameters(self) -> List[Dict[str, Any]]:
        """
        모든 Parameter 정보 로드 (중복 제거)
        
        Uses: ParameterRepository.get_all_parameters_for_ontology()
        
        Returns:
            [{"key": "hr", "name": "Heart Rate", "unit": "bpm", "concept": "Vitals"}, ...]
        """
        try:
            return self.parameter_repo.get_all_parameters_for_ontology()
        except Exception as e:
            self.log(f"❌ Error loading parameters: {e}")
            return []
    
    def _load_tables_with_columns(self) -> List[Dict[str, Any]]:
        """
        테이블별 컬럼 정보 로드 (semantic 정보 포함)
        
        Uses: 
          - FileRepository.get_data_files_with_details()
          - ColumnRepository.get_columns_with_semantic()
        
        Returns:
            [{"file_name": "...", "file_id": "...", "columns": [...]}, ...]
        """
        tables = []
        
        try:
            # 데이터 파일 목록 조회
            data_files = self.file_repo.get_data_files_with_details()
            
            for f in data_files:
                file_id = f['file_id']
                
                # 컬럼 정보 조회 (parameter와 JOIN됨)
                columns = self.column_repo.get_columns_with_semantic(file_id)
                
                tables.append({
                    "file_id": file_id,
                    "file_name": f['file_name'],
                    "columns": columns
                })
        
        except Exception as e:
            self.log(f"❌ Error loading tables: {e}")
        
        return tables
    
    # =============================================================================
    # Task 1: Concept Hierarchy
    # =============================================================================
    
    def _build_concept_context(self, concept_params: Dict[str, List[Dict]]) -> str:
        """LLM용 concept context 생성"""
        lines = []
        
        for concept, params in sorted(concept_params.items()):
            lines.append(f"\n## {concept} ({len(params)} parameters)")
            for p in params[:15]:
                unit_str = f" ({p['unit']})" if p['unit'] else ""
                lines.append(f"  - {p['key']}: {p['name']}{unit_str}")
            if len(params) > 15:
                lines.append(f"  ... and {len(params) - 15} more")
        
        return "\n".join(lines)
    
    def _enhance_concept_hierarchy(self, concept_params: Dict[str, List[Dict]]) -> Tuple[List[SubCategoryResult], int]:
        """Task 1: ConceptCategory → SubCategory 세분화"""
        if not OntologyEnhancementConfig.ENABLE_CONCEPT_HIERARCHY:
            return [], 0
        
        if not concept_params:
            return [], 0
        
        context = self._build_concept_context(concept_params)
        prompt = self.prompt_class.build_concept_hierarchy(concept_categories=context)
        
        self.log("🤖 Calling LLM for concept hierarchy...", indent=1)
        
        try:
            response = self.call_llm_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
            
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
            self.log(f"❌ LLM call failed: {e}", indent=1)
        
        return [], 1
    
    # =============================================================================
    # Task 2: Semantic Edges
    # =============================================================================
    
    def _build_parameters_context(self, parameters: List[Dict], batch_size: int = 30) -> List[str]:
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
    
    def _infer_semantic_relationships(self, parameters: List[Dict]) -> Tuple[List[SemanticEdge], int]:
        """Task 2: Parameter 간 의미 관계 추론"""
        if not OntologyEnhancementConfig.ENABLE_SEMANTIC_EDGES:
            return [], 0
        
        if not parameters:
            return [], 0
        
        batches = self._build_parameters_context(parameters, OntologyEnhancementConfig.PARAMETER_BATCH_SIZE)
        
        all_edges = []
        llm_calls = 0
        
        for i, batch_context in enumerate(batches):
            self.log(f"🤖 Semantic edges batch {i+1}/{len(batches)}...", indent=1)
            
            prompt = self.prompt_class.build_semantic_edges(parameters=batch_context)
            
            try:
                response = self.call_llm_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
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
                self.log(f"❌ LLM call failed: {e}", indent=1)
                llm_calls += 1
        
        return all_edges, llm_calls
    
    # =============================================================================
    # Task 3: Medical Term Mapping
    # =============================================================================
    
    def _map_medical_terms(self, parameters: List[Dict]) -> Tuple[List[MedicalTermMapping], int]:
        """Task 3: 표준 의학 용어 매핑"""
        if not OntologyEnhancementConfig.ENABLE_MEDICAL_TERMS:
            return [], 0
        
        if not parameters:
            return [], 0
        
        batches = self._build_parameters_context(parameters, OntologyEnhancementConfig.MEDICAL_TERM_BATCH_SIZE)
        
        all_mappings = []
        llm_calls = 0
        
        for i, batch_context in enumerate(batches):
            self.log(f"🤖 Medical terms batch {i+1}/{len(batches)}...", indent=1)
            
            prompt = self.prompt_class.build_medical_terms(parameters=batch_context)
            
            try:
                response = self.call_llm_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
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
                            confidence=float(mapping.get('confidence', 0.0)),
                            reasoning=mapping.get('reasoning', '')
                        ))
            
            except Exception as e:
                self.log(f"❌ LLM call failed: {e}", indent=1)
                llm_calls += 1
        
        return all_mappings, llm_calls
    
    # =============================================================================
    # Task 4: Cross-table Semantics
    # =============================================================================
    
    def _build_tables_context_for_cross(self, tables: List[Dict]) -> str:
        """LLM용 tables context 생성"""
        lines = []
        
        for table in tables:
            lines.append(f"\n## {table['file_name']}")
            for col in table['columns'][:20]:
                concept_str = f" [{col['concept_category']}]" if col['concept_category'] else ""
                unit_str = f" ({col['unit']})" if col['unit'] else ""
                lines.append(f"  - {col['original_name']}: {col['semantic_name']}{unit_str}{concept_str}")
            if len(table['columns']) > 20:
                lines.append(f"  ... and {len(table['columns']) - 20} more")
        
        return "\n".join(lines)
    
    def _find_cross_table_semantics(self, tables: List[Dict]) -> Tuple[List[CrossTableSemantic], int]:
        """Task 4: 테이블 간 시맨틱 관계 탐지"""
        if not OntologyEnhancementConfig.ENABLE_CROSS_TABLE:
            return [], 0
        
        if len(tables) < 2:
            return [], 0
        
        context = self._build_tables_context_for_cross(tables)
        prompt = self.prompt_class.build_cross_table(tables_info=context)
        
        self.log("🤖 Calling LLM for cross-table semantics...", indent=1)
        
        try:
            response = self.call_llm_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
            
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
            self.log(f"❌ LLM call failed: {e}", indent=1)
        
        return [], 1
    
    # =============================================================================
    # PostgreSQL Save
    # =============================================================================
    
    def _save_to_postgres(
        self,
        subcategories: List[SubCategoryResult],
        edges: List[SemanticEdge],
        mappings: List[MedicalTermMapping],
        cross_semantics: List[CrossTableSemantic],
        tables: List[Dict]
    ):
        """모든 결과를 PostgreSQL에 저장"""
        repo = OntologyRepository()
        
        # Task 1: Subcategories
        if subcategories:
            subcat_dicts = [{
                "parent_category": s.parent_category,
                "subcategory_name": s.subcategory_name,
                "confidence": s.confidence,
                "reasoning": s.reasoning
            } for s in subcategories]
            repo.save_subcategories(subcat_dicts)
        
        # Task 2: Semantic Edges
        if edges:
            edge_dicts = [{
                "source_parameter": e.source_parameter,
                "target_parameter": e.target_parameter,
                "relationship_type": e.relationship_type,
                "confidence": e.confidence,
                "reasoning": e.reasoning
            } for e in edges]
            repo.save_semantic_edges(edge_dicts)
        
        # Task 3: Medical Terms
        if mappings:
            mapping_dicts = [{
                "parameter_key": m.parameter_key,
                "snomed_code": m.snomed_code,
                "snomed_name": m.snomed_name,
                "loinc_code": m.loinc_code,
                "loinc_name": m.loinc_name,
                "icd10_code": m.icd10_code,
                "icd10_name": m.icd10_name,
                "confidence": m.confidence,
                "reasoning": m.reasoning
            } for m in mappings]
            repo.save_medical_term_mappings(mapping_dicts)
        
        # Task 4: Cross-table Semantics
        if cross_semantics:
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
                repo.save_cross_table_semantics(cross_dicts)
    
    # =============================================================================
    # Neo4j Sync (Using Neo4jMixin)
    # =============================================================================
    
    def _sync_subcategories_to_neo4j(self, driver, subcategories: List[SubCategoryResult]) -> int:
        """SubCategory 노드와 관계 생성"""
        if not driver or not subcategories:
            return 0
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for subcat in subcategories:
                try:
                    session.run("""
                        MERGE (sc:SubCategory {name: $name})
                        SET sc.parent = $parent,
                            sc.confidence = $confidence
                    """, {
                        "name": subcat.subcategory_name,
                        "parent": subcat.parent_category,
                        "confidence": subcat.confidence
                    })
                    
                    session.run("""
                        MATCH (c:ConceptCategory {name: $parent})
                        MATCH (sc:SubCategory {name: $name})
                        MERGE (c)-[:HAS_SUBCATEGORY]->(sc)
                    """, {
                        "parent": subcat.parent_category,
                        "name": subcat.subcategory_name
                    })
                    
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
                    self.log(f"❌ Error creating SubCategory {subcat.subcategory_name}: {e}", indent=2)
        
        return count
    
    def _sync_semantic_edges_to_neo4j(self, driver, edges: List[SemanticEdge]) -> int:
        """Semantic Edge 관계 생성"""
        if not driver or not edges:
            return 0
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for edge in edges:
                try:
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
                    self.log(f"❌ Error creating edge {edge.source_parameter}->{edge.target_parameter}: {e}", indent=2)
        
        return count
    
    def _sync_medical_terms_to_neo4j(self, driver, mappings: List[MedicalTermMapping]) -> int:
        """MedicalTerm 노드와 MAPS_TO 관계 생성"""
        if not driver or not mappings:
            return 0
        
        count = 0
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            for mapping in mappings:
                try:
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
                    self.log(f"❌ Error creating MedicalTerm for {mapping.parameter_key}: {e}", indent=2)
        
        return count
    
    def _sync_cross_table_to_neo4j(self, driver, cross_semantics: List[CrossTableSemantic], tables: List[Dict]) -> int:
        """Cross-table semantic 관계 생성"""
        if not driver or not cross_semantics:
            return 0
        
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
                    self.log(f"❌ Error creating cross-table semantic: {e}", indent=2)
        
        return count
    
    def _sync_to_neo4j(
        self,
        subcategories: List[SubCategoryResult],
        edges: List[SemanticEdge],
        mappings: List[MedicalTermMapping],
        cross_semantics: List[CrossTableSemantic],
        tables: List[Dict]
    ) -> Dict[str, int]:
        """Neo4j 전체 동기화 (Neo4jMixin 사용)"""
        stats = {
            "subcategory_nodes": 0,
            "medical_term_nodes": 0,
            "semantic_edges": 0,
            "cross_table_edges": 0
        }
        
        if not OntologyEnhancementConfig.NEO4J_ENABLED:
            self.log("ℹ️ Neo4j sync is disabled", indent=1)
            return stats
        
        driver = self.neo4j_driver  # Neo4jMixin 사용
        if not driver:
            self.log("⚠️ Skipping Neo4j sync (connection failed)", indent=1)
            return stats
        
        try:
            self.log("📊 Syncing enhancements to Neo4j...", indent=1)
            
            stats["subcategory_nodes"] = self._sync_subcategories_to_neo4j(driver, subcategories)
            self.log(f"✓ SubCategory nodes: {stats['subcategory_nodes']}", indent=2)
            
            stats["semantic_edges"] = self._sync_semantic_edges_to_neo4j(driver, edges)
            self.log(f"✓ Semantic edges: {stats['semantic_edges']}", indent=2)
            
            stats["medical_term_nodes"] = self._sync_medical_terms_to_neo4j(driver, mappings)
            self.log(f"✓ MedicalTerm nodes: {stats['medical_term_nodes']}", indent=2)
            
            stats["cross_table_edges"] = self._sync_cross_table_to_neo4j(driver, cross_semantics, tables)
            self.log(f"✓ Cross-table edges: {stats['cross_table_edges']}", indent=2)
            
        finally:
            self.close_neo4j()  # Neo4jMixin 사용
        
        return stats
    
    # =============================================================================
    # Main Execute
    # =============================================================================
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ontology Enhancement 실행
        
        1. Concept Hierarchy: ConceptCategory를 SubCategory로 세분화
        2. Semantic Edges: Parameter 간 의미 관계 추론
        3. Medical Term Mapping: SNOMED-CT, LOINC 매핑
        4. Cross-table Semantics: 테이블 간 시맨틱 관계 탐지
        """
        started_at = datetime.now().isoformat()
        total_llm_calls = 0
        
        # 스키마 확인
        schema_manager = OntologySchemaManager()
        schema_manager.create_tables()
        
        # =========================================================================
        # Task 1: Concept Hierarchy
        # =========================================================================
        self.log("📁 Task 1: Concept Hierarchy")
        concept_params = self._load_concept_categories_with_parameters()
        self.log(f"Loaded {len(concept_params)} concept categories", indent=1)
        
        subcategories, llm1 = self._enhance_concept_hierarchy(concept_params)
        total_llm_calls += llm1
        self.log(f"✅ Created {len(subcategories)} subcategories", indent=1)
        
        # =========================================================================
        # Task 2: Semantic Edges
        # =========================================================================
        self.log("🔗 Task 2: Semantic Edges")
        parameters = self._load_all_parameters()
        self.log(f"Loaded {len(parameters)} unique parameters", indent=1)
        
        edges, llm2 = self._infer_semantic_relationships(parameters)
        total_llm_calls += llm2
        
        derived_from = sum(1 for e in edges if e.relationship_type == 'DERIVED_FROM')
        related_to = sum(1 for e in edges if e.relationship_type == 'RELATED_TO')
        self.log(f"✅ Created {len(edges)} semantic edges (DERIVED_FROM: {derived_from}, RELATED_TO: {related_to})", indent=1)
        
        # =========================================================================
        # Task 3: Medical Term Mapping
        # =========================================================================
        self.log("🏥 Task 3: Medical Term Mapping")
        mappings, llm3 = self._map_medical_terms(parameters)
        total_llm_calls += llm3
        
        snomed_count = sum(1 for m in mappings if m.snomed_code)
        loinc_count = sum(1 for m in mappings if m.loinc_code)
        self.log(f"✅ Created {len(mappings)} mappings (SNOMED: {snomed_count}, LOINC: {loinc_count})", indent=1)
        
        # =========================================================================
        # Task 4: Cross-table Semantics
        # =========================================================================
        self.log("🔄 Task 4: Cross-table Semantics")
        tables = self._load_tables_with_columns()
        self.log(f"Loaded {len(tables)} tables", indent=1)
        
        cross_semantics, llm4 = self._find_cross_table_semantics(tables)
        total_llm_calls += llm4
        self.log(f"✅ Found {len(cross_semantics)} cross-table semantics", indent=1)
        
        # =========================================================================
        # Save to PostgreSQL
        # =========================================================================
        self.log("💾 Saving to PostgreSQL...")
        self._save_to_postgres(subcategories, edges, mappings, cross_semantics, tables)
        
        # =========================================================================
        # Sync to Neo4j
        # =========================================================================
        self.log("📊 Syncing to Neo4j...")
        neo4j_stats = self._sync_to_neo4j(subcategories, edges, mappings, cross_semantics, tables)
        neo4j_synced = sum(neo4j_stats.values()) > 0
        
        # =========================================================================
        # Summary
        # =========================================================================
        high_conf_subcats = sum(1 for s in subcategories if s.confidence >= OntologyEnhancementConfig.CONFIDENCE_THRESHOLD)
        
        self.log(f"Task 1 - Subcategories: {len(subcategories)} (high conf: {high_conf_subcats})", indent=1)
        self.log(f"Task 2 - Semantic Edges: {len(edges)} (DERIVED: {derived_from}, RELATED: {related_to})", indent=1)
        self.log(f"Task 3 - Medical Terms: {len(mappings)} (SNOMED: {snomed_count}, LOINC: {loinc_count})", indent=1)
        self.log(f"Task 4 - Cross-table: {len(cross_semantics)}", indent=1)
        self.log(f"LLM calls: {total_llm_calls}", indent=1)
        self.log(f"Neo4j synced: {neo4j_synced}", indent=1)
        
        # 결과 생성
        completed_at = datetime.now().isoformat()
        
        phase_result = OntologyEnhancementResult(
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
            "ontology_enhancement_result": phase_result.model_dump(),
            "ontology_subcategories": [s.model_dump() for s in subcategories],
            "semantic_edges": [e.model_dump() for e in edges],
            "medical_term_mappings": [m.model_dump() for m in mappings],
            "cross_table_semantics": [cs.model_dump() for cs in cross_semantics]
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

