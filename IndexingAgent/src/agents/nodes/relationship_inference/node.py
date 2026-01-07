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

import time
from datetime import datetime
from typing import Dict, List, Any, Tuple, Set

from ...models.llm_responses import (
    TableRelationship,
    RelationshipInferenceResult,
)
from ...base import BaseNode, LLMMixin, DatabaseMixin, Neo4jMixin
from ...registry import register_node
from shared.database import OntologySchemaManager
from shared.database.repositories import ParameterRepository, FileGroupRepository
from src.config import RelationshipInferenceConfig, IndexingConfig
from shared.config import LLMConfig, Neo4jConfig
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
        LLM을 호출하여 FK 관계 추론 (배치 처리)
        
        테이블 수가 MAX_TABLES_PER_BATCH를 초과하면 배치로 나눠서 처리합니다.
        
        Returns:
            (관계 목록, LLM 호출 횟수)
        """
        if not tables or len(tables) < 2:
            return [], 0
        
        if not shared:
            self.log("ℹ️ No shared columns - skipping LLM call", indent=1)
            return [], 0
        
        max_tables = RelationshipInferenceConfig.MAX_TABLES_PER_BATCH
        
        # 배치가 필요한지 확인
        if len(tables) <= max_tables:
            # 단일 배치로 처리
            return self._call_llm_for_batch(tables, shared)
        
        # 배치 처리 필요
        self.log(f"📦 Splitting {len(tables)} tables into batches of {max_tables}...", indent=1)
        
        all_results = []
        total_llm_calls = 0
        
        # 테이블을 배치로 분할
        table_batches = [tables[i:i + max_tables] for i in range(0, len(tables), max_tables)]
        
        for batch_idx, table_batch in enumerate(table_batches):
            self.log(f"📤 Batch {batch_idx + 1}/{len(table_batches)} ({len(table_batch)} tables)...", indent=1)
            
            # 이 배치에 해당하는 파일들의 이름 집합
            batch_file_names = {t['file_name'] for t in table_batch}
            
            # 공유 컬럼 중 이 배치에 해당하는 것만 필터링
            batch_shared = self._filter_shared_for_batch(shared, batch_file_names)
            
            if not batch_shared:
                self.log(f"   ℹ️ No shared columns in this batch, skipping", indent=1)
                continue
            
            # 배치별 LLM 호출
            batch_results, batch_calls = self._call_llm_for_batch(table_batch, batch_shared)
            all_results.extend(batch_results)
            total_llm_calls += batch_calls
            
            self.log(f"   ✅ Found {len(batch_results)} relationships", indent=1)
        
        # 중복 관계 제거
        unique_results = self._deduplicate_relationships(all_results)
        
        return unique_results, total_llm_calls
    
    def _filter_shared_for_batch(
        self,
        shared: List[Dict],
        batch_file_names: Set[str]
    ) -> List[Dict]:
        """배치에 해당하는 파일들만 포함하도록 공유 컬럼 필터링"""
        filtered = []
        
        for item in shared:
            # 이 컬럼을 공유하는 테이블 중 배치에 속하는 것만 필터링
            batch_tables = [t for t in item['tables'] if t['file_name'] in batch_file_names]
            
            # 2개 이상 테이블이 공유해야 FK 후보
            if len(batch_tables) >= 2:
                filtered.append({
                    "column_name": item['column_name'],
                    "tables": batch_tables
                })
        
        return filtered
    
    def _deduplicate_relationships(
        self,
        relationships: List[TableRelationship]
    ) -> List[TableRelationship]:
        """중복 관계 제거 (source-target-column 조합 기준)"""
        seen = set()
        unique = []
        
        for rel in relationships:
            key = (rel.source_table, rel.target_table, rel.source_column, rel.target_column)
            if key not in seen:
                seen.add(key)
                unique.append(rel)
        
        return unique
    
    def _call_llm_for_batch(
        self,
        tables: List[Dict],
        shared: List[Dict]
    ) -> Tuple[List[TableRelationship], int]:
        """
        단일 배치에 대해 LLM 호출
        
        Returns:
            (관계 목록, LLM 호출 횟수)
        """
        tables_context = self._build_tables_context(tables)
        shared_context = self._build_shared_columns_context(shared)
        
        # PromptTemplate을 사용하여 프롬프트 빌드
        prompt = self.prompt_class.build(
            tables_context=tables_context,
            shared_columns=shared_context
        )
        
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
                    self.log(f"   ⚠️ Invalid LLM response, attempt {attempt + 1}", indent=2)
                    
            except Exception as e:
                self.log(f"   ❌ LLM call failed (attempt {attempt + 1}): {e}", indent=2)
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
        """Level 1: RowEntity 노드 생성 - UNWIND 배치 처리"""
        if not driver or not tables:
            return 0
        
        batch_data = [
            {
                "file_id": table['file_id'],
                "file_name": table['file_name'],
                "row_represents": table['row_represents'],
                "entity_identifier": table['entity_identifier'],
                "row_count": table['row_count']
            }
            for table in tables
        ]
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                result = session.run("""
                    UNWIND $batch AS row
                    MERGE (e:RowEntity {file_name: row.file_name})
                    SET e.file_id = row.file_id,
                        e.name = row.row_represents,
                        e.identifier_column = row.entity_identifier,
                        e.row_count = row.row_count
                    RETURN count(*) as cnt
                """, {"batch": batch_data})
                return result.single()["cnt"]
        except Exception as e:
            self.log(f"❌ Error creating RowEntity nodes: {e}", indent=2)
            return 0
    
    def _create_concept_category_nodes(self, driver, all_params: List[Dict]) -> int:
        """Level 2: ConceptCategory 노드 생성 - UNWIND 배치 처리"""
        if not driver:
            return 0
        
        concepts = list({param['concept'] for param in all_params if param.get('concept')})
        if not concepts:
            return 0
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                result = session.run("""
                    UNWIND $concepts AS name
                    MERGE (c:ConceptCategory {name: name})
                    RETURN count(*) as cnt
                """, {"concepts": concepts})
                return result.single()["cnt"]
        except Exception as e:
            self.log(f"❌ Error creating ConceptCategory nodes: {e}", indent=2)
            return 0
    
    def _create_parameter_nodes(self, driver, all_params: List[Dict]) -> int:
        """Level 3: Parameter 노드 생성 - UNWIND 배치 처리"""
        if not driver or not all_params:
            return 0
        
        batch_data = [
            {
                "key": param['key'],
                "name": param['name'],
                "unit": param['unit'],
                "concept": param['concept'],
                "is_identifier": param.get('is_identifier', False)
            }
            for param in all_params
        ]
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                result = session.run("""
                    UNWIND $batch AS row
                    MERGE (p:Parameter {key: row.key})
                    SET p.name = row.name,
                        p.unit = row.unit,
                        p.concept = row.concept,
                        p.is_identifier = row.is_identifier
                    RETURN count(*) as cnt
                """, {"batch": batch_data})
                return result.single()["cnt"]
        except Exception as e:
            self.log(f"❌ Error creating Parameter nodes: {e}", indent=2)
            return 0
    
    def _create_links_to_edges(self, driver, relationships: List[TableRelationship], tables: List[Dict]) -> int:
        """RowEntity 간 FK 관계 (LINKS_TO) 생성 - UNWIND 배치 처리"""
        if not driver or not relationships:
            return 0
        
        valid_names = {t['file_name'] for t in tables}
        
        batch_data = [
            {
                "source_name": rel.source_table,
                "target_name": rel.target_table,
                "source_column": rel.source_column,
                "target_column": rel.target_column,
                "cardinality": rel.cardinality,
                "confidence": rel.confidence
            }
            for rel in relationships
            if rel.source_table in valid_names and rel.target_table in valid_names
        ]
        
        if not batch_data:
            return 0
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                result = session.run("""
                    UNWIND $batch AS row
                    MATCH (s:RowEntity {file_name: row.source_name})
                    MATCH (t:RowEntity {file_name: row.target_name})
                    MERGE (s)-[r:LINKS_TO]->(t)
                    SET r.source_column = row.source_column,
                        r.target_column = row.target_column,
                        r.cardinality = row.cardinality,
                        r.confidence = row.confidence
                    RETURN count(*) as cnt
                """, {"batch": batch_data})
                return result.single()["cnt"]
        except Exception as e:
            self.log(f"❌ Error creating LINKS_TO edges: {e}", indent=2)
            return 0
    
    def _create_has_concept_edges(self, driver, tables: List[Dict]) -> int:
        """RowEntity → ConceptCategory (HAS_CONCEPT) 엣지 생성 - UNWIND 배치 처리"""
        if not driver:
            return 0
        
        # 배치 데이터 수집 (중복 제거)
        edges_set = set()
        for table in tables:
            concepts = {col['concept_category'] for col in table['columns'] if col['concept_category']}
            for concept in concepts:
                edges_set.add((table['file_name'], concept))
        
        if not edges_set:
            return 0
        
        batch_data = [{"file_name": fn, "concept": c} for fn, c in edges_set]
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                result = session.run("""
                    UNWIND $batch AS row
                    MATCH (e:RowEntity {file_name: row.file_name})
                    MATCH (c:ConceptCategory {name: row.concept})
                    MERGE (e)-[:HAS_CONCEPT]->(c)
                    RETURN count(*) as cnt
                """, {"batch": batch_data})
                return result.single()["cnt"]
        except Exception as e:
            self.log(f"❌ Error creating HAS_CONCEPT edges: {e}", indent=2)
            return 0
    
    def _create_contains_edges(self, driver, all_params: List[Dict]) -> int:
        """ConceptCategory → Parameter (CONTAINS) 엣지 생성 - UNWIND 배치 처리"""
        if not driver:
            return 0
        
        # 배치 데이터 수집
        batch_data = [
            {"concept": param['concept'], "key": param['key']}
            for param in all_params
            if param.get('concept')
        ]
        
        if not batch_data:
            return 0
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                result = session.run("""
                    UNWIND $batch AS row
                    MATCH (c:ConceptCategory {name: row.concept})
                    MATCH (p:Parameter {key: row.key})
                    MERGE (c)-[:CONTAINS]->(p)
                    RETURN count(*) as cnt
                """, {"batch": batch_data})
                return result.single()["cnt"]
        except Exception as e:
            self.log(f"❌ Error creating CONTAINS edges: {e}", indent=2)
            return 0
    
    def _create_has_column_edges(self, driver, tables: List[Dict]) -> int:
        """RowEntity → Parameter (HAS_COLUMN) 엣지 생성 - UNWIND 배치 처리 (대량 최적화)"""
        if not driver:
            return 0
        
        # 모든 엣지 데이터를 한 번에 수집
        batch_data = []
        for table in tables:
            file_name = table['file_name']
            for col in table['columns']:
                batch_data.append({
                    "file_name": file_name,
                    "key": col['original_name']
                })
        
        if not batch_data:
            return 0
        
        # 대량 데이터는 청크로 나눠서 처리 (메모리 효율성)
        CHUNK_SIZE = 5000
        total_count = 0
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                for i in range(0, len(batch_data), CHUNK_SIZE):
                    chunk = batch_data[i:i + CHUNK_SIZE]
                    result = session.run("""
                        UNWIND $batch AS row
                        MATCH (e:RowEntity {file_name: row.file_name})
                        MATCH (p:Parameter {key: row.key})
                        MERGE (e)-[:HAS_COLUMN]->(p)
                        RETURN count(*) as cnt
                    """, {"batch": chunk})
                    total_count += result.single()["cnt"]
            return total_count
        except Exception as e:
            self.log(f"❌ Error creating HAS_COLUMN edges: {e}", indent=2)
            return 0
    
    def _load_filename_column_mappings(self) -> Dict[str, Dict[str, Any]]:
        """
        directory_catalog에서 filename_columns 매핑 정보 로드
        
        Uses: DirectoryRepository.get_filename_column_mappings()
        """
        return self.directory_repo.get_filename_column_mappings()
    
    def _create_filename_value_edges(self, driver, tables: List[Dict]) -> int:
        """filename_values에서 추출된 값을 Parameter 노드와 FILENAME_VALUE 관계로 연결 - UNWIND 배치 처리"""
        if not driver:
            return 0
        
        dir_mappings = self._load_filename_column_mappings()
        
        # 배치 데이터 수집
        batch_data = []
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
                    matched_column = matched_info.get('matched_column') or key
                    confidence = matched_info.get('match_confidence', 0.8)
                    reasoning = matched_info.get('match_reasoning', reasoning)
                else:
                    matched_column = key
                
                # semantic_role 결정
                matched_lower = matched_column.lower()
                if 'id' in matched_lower or 'case' in matched_lower:
                    semantic_role = "case_identifier"
                elif 'subject' in matched_lower or 'patient' in matched_lower:
                    semantic_role = "subject_identifier"
                elif 'date' in matched_lower or 'time' in matched_lower:
                    semantic_role = "temporal_identifier"
                else:
                    semantic_role = "identifier"
                
                batch_data.append({
                    "file_name": file_name,
                    "param_key": matched_column,
                    "value": str(value) if value is not None else "",
                    "semantic_role": semantic_role,
                    "confidence": confidence,
                    "reasoning": reasoning
                })
        
        if not batch_data:
            return 0
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                result = session.run("""
                    UNWIND $batch AS row
                    MATCH (e:RowEntity {file_name: row.file_name})
                    MATCH (p:Parameter {key: row.param_key})
                    MERGE (e)-[r:FILENAME_VALUE]->(p)
                    SET r.value = row.value,
                        r.semantic_role = row.semantic_role,
                        r.source = 'filename',
                        r.confidence = row.confidence,
                        r.reasoning = row.reasoning
                    RETURN count(*) as cnt
                """, {"batch": batch_data})
                return result.single()["cnt"]
        except Exception as e:
            self.log(f"❌ Error creating FILENAME_VALUE edges: {e}", indent=2)
            return 0
    
    # =========================================================================
    # FileGroup 노드 및 엣지 (Q2: group_common 파라미터 지원)
    # =========================================================================
    
    def _create_file_group_nodes(self, driver) -> int:
        """FileGroup 노드 생성 - UNWIND 배치 처리"""
        if not driver:
            return 0
        
        group_repo = FileGroupRepository()
        groups = group_repo.get_all_groups(status='confirmed')
        
        if not groups:
            return 0
        
        batch_data = [
            {
                "group_id": str(group['group_id']),
                "name": group['group_name'],
                "file_count": group.get('file_count', 0),
                "row_represents": group.get('row_represents')
            }
            for group in groups
        ]
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                result = session.run("""
                    UNWIND $batch AS row
                    MERGE (fg:FileGroup {group_id: row.group_id})
                    SET fg.name = row.name,
                        fg.file_count = row.file_count,
                        fg.row_represents = row.row_represents
                    RETURN count(*) as cnt
                """, {"batch": batch_data})
                return result.single()["cnt"]
        except Exception as e:
            self.log(f"❌ Error creating FileGroup nodes: {e}", indent=2)
            return 0
    
    def _create_contains_file_edges(self, driver, tables: List[Dict]) -> int:
        """FileGroup → RowEntity (CONTAINS_FILE) 엣지 생성 - UNWIND 배치 처리"""
        if not driver:
            return 0
        
        # tables에서 group_id가 있는 파일들만 추출
        batch_data = [
            {"group_id": str(t['group_id']), "file_name": t['file_name']}
            for t in tables if t.get('group_id')
        ]
        
        if not batch_data:
            return 0
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                result = session.run("""
                    UNWIND $batch AS row
                    MATCH (fg:FileGroup {group_id: row.group_id})
                    MATCH (r:RowEntity {file_name: row.file_name})
                    MERGE (fg)-[:CONTAINS_FILE]->(r)
                    RETURN count(*) as cnt
                """, {"batch": batch_data})
                return result.single()["cnt"]
        except Exception as e:
            self.log(f"❌ Error creating CONTAINS_FILE edges: {e}", indent=2)
            return 0
    
    def _create_has_common_param_edges(self, driver) -> int:
        """FileGroup → Parameter (HAS_COMMON_PARAM) 엣지 생성 - UNWIND 배치 처리"""
        if not driver:
            return 0
        
        param_repo = ParameterRepository()
        group_params = param_repo.get_group_common_params_for_neo4j()
        
        if not group_params:
            return 0
        
        batch_data = [
            {"group_id": item['group_id'], "param_key": item['param_key']}
            for item in group_params
        ]
        
        try:
            with driver.session(database=Neo4jConfig.DATABASE) as session:
                result = session.run("""
                    UNWIND $batch AS row
                    MATCH (fg:FileGroup {group_id: row.group_id})
                    MATCH (p:Parameter {key: row.param_key})
                    MERGE (fg)-[:HAS_COMMON_PARAM]->(p)
                    RETURN count(*) as cnt
                """, {"batch": batch_data})
                return result.single()["cnt"]
        except Exception as e:
            self.log(f"❌ Error creating HAS_COMMON_PARAM edges: {e}", indent=2)
            return 0
    
    def _sync_to_neo4j(
        self,
        tables: List[Dict],
        relationships: List[TableRelationship]
    ) -> Dict[str, int]:
        """Neo4j 전체 동기화 (Neo4jMixin 사용)"""
        stats = {
            "row_entity_nodes": 0,
            "file_group_nodes": 0,
            "concept_category_nodes": 0,
            "parameter_nodes": 0,
            "edges_links_to": 0,
            "edges_has_concept": 0,
            "edges_contains": 0,
            "edges_has_column": 0,
            "edges_filename_value": 0,
            "edges_contains_file": 0,
            "edges_has_common_param": 0
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
            
            # ═══════════════════════════════════════════════════════════════
            # NODES
            # ═══════════════════════════════════════════════════════════════
            
            # Level 1: RowEntity (개별 파일/테이블)
            stats["row_entity_nodes"] = self._create_row_entity_nodes(driver, tables)
            self.log(f"✓ RowEntity nodes: {stats['row_entity_nodes']}", indent=2)
            
            # FileGroup (파일 그룹 - group_common 파라미터 지원)
            stats["file_group_nodes"] = self._create_file_group_nodes(driver)
            self.log(f"✓ FileGroup nodes: {stats['file_group_nodes']}", indent=2)
            
            # Level 2: ConceptCategory (parameter 테이블 기반)
            stats["concept_category_nodes"] = self._create_concept_category_nodes(driver, all_params)
            self.log(f"✓ ConceptCategory nodes: {stats['concept_category_nodes']}", indent=2)
            
            # Level 3: Parameter (parameter 테이블 기반)
            stats["parameter_nodes"] = self._create_parameter_nodes(driver, all_params)
            self.log(f"✓ Parameter nodes: {stats['parameter_nodes']}", indent=2)
            
            # ═══════════════════════════════════════════════════════════════
            # EDGES
            # ═══════════════════════════════════════════════════════════════
            
            # FK 관계: RowEntity → RowEntity
            stats["edges_links_to"] = self._create_links_to_edges(driver, relationships, tables)
            self.log(f"✓ LINKS_TO edges: {stats['edges_links_to']}", indent=2)
            
            # RowEntity → ConceptCategory
            stats["edges_has_concept"] = self._create_has_concept_edges(driver, tables)
            self.log(f"✓ HAS_CONCEPT edges: {stats['edges_has_concept']}", indent=2)
            
            # ConceptCategory → Parameter (parameter 테이블 기반)
            stats["edges_contains"] = self._create_contains_edges(driver, all_params)
            self.log(f"✓ CONTAINS edges: {stats['edges_contains']}", indent=2)
            
            # RowEntity → Parameter (column_name 기반)
            stats["edges_has_column"] = self._create_has_column_edges(driver, tables)
            self.log(f"✓ HAS_COLUMN edges: {stats['edges_has_column']}", indent=2)
            
            # RowEntity → Parameter (filename에서 추출된 값)
            stats["edges_filename_value"] = self._create_filename_value_edges(driver, tables)
            self.log(f"✓ FILENAME_VALUE edges: {stats['edges_filename_value']}", indent=2)
            
            # FileGroup → RowEntity (그룹에 속한 파일들)
            stats["edges_contains_file"] = self._create_contains_file_edges(driver, tables)
            self.log(f"✓ CONTAINS_FILE edges: {stats['edges_contains_file']}", indent=2)
            
            # FileGroup → Parameter (group_common 파라미터)
            stats["edges_has_common_param"] = self._create_has_common_param_edges(driver)
            self.log(f"✓ HAS_COMMON_PARAM edges: {stats['edges_has_common_param']}", indent=2)
            
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
        
        # 3. 이미 분석된 관계 확인 (스킵 로직)
        relationships = []
        llm_calls = 0
        skipped_relationships = False
        
        if not IndexingConfig.FORCE_REANALYZE:
            existing_count = self.entity_repo.get_relationship_count()
            if existing_count > 0:
                self.log(f"⏭️  Skipping LLM inference: {existing_count} relationships already exist", indent=1)
                skipped_relationships = True
                # 기존 관계를 로드하여 사용
                relationships = self._load_existing_relationships(tables)
        
        if not skipped_relationships:
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
        
        # 5. PostgreSQL 저장 (새로 추론한 경우에만)
        saved_count = 0
        if not skipped_relationships:
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
    
    # =========================================================================
    # Skip Already Analyzed
    # =========================================================================
    
    def _load_existing_relationships(
        self, 
        tables: List[Dict[str, Any]]
    ) -> List[TableRelationship]:
        """
        기존 table_relationships에서 관계 로드
        
        FORCE_REANALYZE=false이고 관계가 이미 있을 때 사용
        
        Args:
            tables: 테이블 정보 (file_name → file_id 매핑용)
        
        Returns:
            TableRelationship 목록
        """
        existing = self.entity_repo.get_relationships()
        
        relationships = []
        for rel in existing:
            relationships.append(TableRelationship(
                source_table=rel.get('source_name', ''),
                target_table=rel.get('target_name', ''),
                source_column=rel.get('source_column', ''),
                target_column=rel.get('target_column', ''),
                relationship_type=rel.get('relationship_type', 'foreign_key'),
                cardinality=rel.get('cardinality', '1:N'),
                confidence=rel.get('confidence', 0.0),
                reasoning=rel.get('reasoning', '')
            ))
        
        return relationships
    
    @classmethod
    def run_standalone(cls) -> Dict[str, Any]:
        """
        단독 실행용 메서드 (테스트용)
        
        Returns:
            실행 결과 state
        """
        node = cls()
        return node({})

