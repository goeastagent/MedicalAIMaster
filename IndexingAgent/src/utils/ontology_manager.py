"""
온톨로지 저장/로드/병합 관리자 (Neo4j + PostgreSQL 하이브리드)

Dataset-First Architecture:
- 모든 노드에 dataset_id 속성 추가
- 데이터셋별로 독립적인 온톨로지 관리
- 같은 이름의 Concept도 데이터셋별로 구분

역할 분리:
- Neo4j: 그래프 구조 (Concept, Table, Relationships, Hierarchy)
- PostgreSQL: 복잡한 문서형 데이터 (ontology_column_metadata - JSONB)

스키마 관리:
- 스키마 정의는 src/database/schema_ontology.py에서 통합 관리
- ontology_column_metadata: 데이터셋 기반 컬럼 메타데이터 (JSONB)
- table_entities: 테이블별 Entity Understanding
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from src.database.neo4j_connection import Neo4jConnection
from src.database.connection import get_db_manager
from src.database.schema_ontology import ensure_ontology_schema, OntologySchemaManager

logger = logging.getLogger(__name__)


class OntologyManager:
    """
    온톨로지 지식 베이스 관리자 (Neo4j 기반)
    
    Dataset-First Architecture:
    - 모든 엔티티는 dataset_id로 구분됨
    - load()/save()는 특정 데이터셋의 온톨로지만 처리
    - load_all()로 전체 온톨로지 조회 가능
    """
    
    def __init__(self, db_path: str = "data/processed/ontology_db.json"):
        # db_path는 하위 호환성을 위해 남겨두지만 실제로는 사용하지 않음
        self.neo4j = Neo4jConnection()
        self.pg = get_db_manager()  # PostgreSQL for ontology_column_metadata
        self.ontology = self._create_empty_ontology()
        self.current_dataset_id: Optional[str] = None  # 현재 작업 중인 데이터셋
        
        # PostgreSQL 온톨로지 스키마 초기화 (schema_ontology.py에서 관리)
        self._ensure_ontology_tables()
        
        # 스키마 매니저 (CRUD 작업용)
        self._schema_manager = OntologySchemaManager()
    
    def _ensure_ontology_tables(self):
        """PostgreSQL에 온톨로지 테이블 생성 (schema_ontology.py 사용)"""
        try:
            ensure_ontology_schema()
        except Exception as e:
            logger.warning(f"온톨로지 테이블 생성 실패 (무시됨): {e}")
    
    def _load_column_metadata_from_pg(self, dataset_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """PostgreSQL에서 ontology_column_metadata 로드 (schema_ontology 사용)"""
        try:
            return self._schema_manager.load_column_metadata(dataset_id)
        except Exception as e:
            logger.warning(f"ontology_column_metadata 로드 실패: {e}")
            return {}
    
    def _save_column_metadata_to_pg(self, column_metadata: Dict, dataset_id: str):
        """PostgreSQL에 ontology_column_metadata 저장 (schema_ontology 사용)"""
        if not column_metadata:
            return
        
        try:
            self._schema_manager.save_column_metadata(column_metadata, dataset_id)
        except Exception as e:
            logger.error(f"ontology_column_metadata 저장 실패: {e}")
            raise

    # =========================================================================
    # Table Entity Methods (NEW - Entity Understanding)
    # =========================================================================
    
    def _load_table_entities_from_pg(self, dataset_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """PostgreSQL에서 table_entities 로드 (schema_ontology 사용)"""
        try:
            return self._schema_manager.load_table_entities(dataset_id)
        except Exception as e:
            logger.warning(f"table_entities 로드 실패: {e}")
            return {}
    
    def _save_table_entities_to_pg(self, table_entities: Dict, dataset_id: str):
        """PostgreSQL에 table_entities 저장 (schema_ontology 사용)"""
        if not table_entities:
            return
        
        try:
            self._schema_manager.save_table_entities(table_entities, dataset_id)
        except Exception as e:
            logger.error(f"table_entities 저장 실패: {e}")
            raise

    def save_table_entity(self, table_name: str, entity_info: Dict[str, Any], dataset_id: Optional[str] = None):
        """
        개별 테이블의 Entity 정보 저장
        
        Args:
            table_name: 테이블명
            entity_info: EntityUnderstanding 형태의 dict
            dataset_id: 데이터셋 ID (없으면 current_dataset_id 사용)
        """
        ds_id = dataset_id or self.current_dataset_id or "default"
        
        # 메모리 업데이트
        if "table_entities" not in self.ontology:
            self.ontology["table_entities"] = {}
        self.ontology["table_entities"][table_name] = entity_info
        
        # PostgreSQL 저장
        self._save_table_entities_to_pg({table_name: entity_info}, ds_id)
        
        # Neo4j에도 Table 노드 업데이트
        try:
            with self.neo4j.get_session() as session:
                session.run("""
                    MERGE (t:Table {name: $table_name, dataset_id: $dataset_id})
                    SET t.row_represents = $row_represents,
                        t.row_represents_kr = $row_represents_kr,
                        t.entity_identifier = $entity_identifier,
                        t.hierarchy_explanation = $hierarchy_explanation,
                        t.entity_confidence = $confidence,
                        t.updated_at = datetime()
                """, 
                    table_name=table_name,
                    dataset_id=ds_id,
                    row_represents=entity_info.get("row_represents"),
                    row_represents_kr=entity_info.get("row_represents_kr"),
                    entity_identifier=entity_info.get("entity_identifier"),
                    hierarchy_explanation=entity_info.get("hierarchy_explanation", "")[:500],
                    confidence=entity_info.get("confidence", 0.0)
                )
                
                # Linkable Columns를 LINKS_TO 관계로 저장
                for lc in entity_info.get("linkable_columns", []):
                    col_name = lc.get("column_name")
                    represents = lc.get("represents_entity")
                    relation_type = lc.get("relation_type", "reference")
                    
                    session.run("""
                        MERGE (col:Column {name: $col_name, table: $table_name, dataset_id: $dataset_id})
                        SET col.represents_entity = $represents,
                            col.relation_type = $relation_type,
                            col.is_primary_identifier = $is_primary
                    """,
                        col_name=col_name,
                        table_name=table_name,
                        dataset_id=ds_id,
                        represents=represents,
                        relation_type=relation_type,
                        is_primary=lc.get("is_primary_identifier", False)
                    )
                    
        except Exception as e:
            logger.warning(f"Neo4j Table Entity 저장 실패: {e}")

    def get_table_entity(self, table_name: str, dataset_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """테이블의 Entity 정보 조회"""
        ds_id = dataset_id or self.current_dataset_id
        
        # 메모리에서 먼저 확인
        if self.ontology.get("table_entities", {}).get(table_name):
            return self.ontology["table_entities"][table_name]
        
        # PostgreSQL에서 조회
        table_entities = self._load_table_entities_from_pg(ds_id)
        return table_entities.get(table_name)
        
    def load(self, dataset_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Neo4j에서 온톨로지를 로드하여 메모리 상의 딕셔너리로 재구성
        
        Dataset-First Architecture:
        - dataset_id가 지정되면 해당 데이터셋의 온톨로지만 로드
        - dataset_id가 None이면 전체 로드 (하위 호환성)
        
        Args:
            dataset_id: 로드할 데이터셋 ID (None이면 전체)
        
        Returns:
            온톨로지 딕셔너리
        """
        self.current_dataset_id = dataset_id
        
        # 데이터셋 필터 조건
        dataset_filter = ""
        if dataset_id:
            dataset_filter = f"AND c.dataset_id = '{dataset_id}'"
            self.ontology["dataset_id"] = dataset_id
        
        try:
            # 1. Definitions (Concepts) 로드 - original_definition + enriched_definition
            query_concepts = f"""
                MATCH (c:Concept) 
                WHERE c.name IS NOT NULL {dataset_filter.replace('c.', 'c.')}
                RETURN c.name as name, 
                       c.original_definition as original_definition,
                       c.enriched_definition as enriched_definition,
                       c.analysis_context as analysis_context,
                       c.dataset_id as dataset_id
            """
            results = self.neo4j.execute_query(query_concepts)
            
            # definitions: 기본적으로 enriched_definition 우선, 없으면 original_definition
            # definitions_detail: 상세 정보 (원본, enriched, context 모두 포함)
            self.ontology["definitions_detail"] = {}
            
            for record in results:
                name = record["name"]
                original = record["original_definition"]
                enriched = record["enriched_definition"]
                context = record["analysis_context"]
                
                # 기본 definitions: enriched가 있으면 enriched, 없으면 original
                self.ontology["definitions"][name] = enriched or original
                
                # 상세 정보 저장
                self.ontology["definitions_detail"][name] = {
                    "original_definition": original,
                    "enriched_definition": enriched,
                    "analysis_context": context
                }

            # 2. Hierarchy 로드
            query_hier = f"""
                MATCH (c:Concept) 
                WHERE c.level IS NOT NULL {dataset_filter}
                RETURN c
            """
            results = self.neo4j.execute_query(query_hier)
            
            # 초기화
            self.ontology["hierarchy"] = []
            
            for record in results:
                node = record["c"]
                self.ontology["hierarchy"].append({
                    "entity_name": node.get("name"),
                    "level": node.get("level"),
                    "anchor_column": node.get("anchor_column"),
                    "confidence": node.get("confidence", 0),
                    "dataset_id": node.get("dataset_id")
                })
            # 레벨 정렬
            self.ontology["hierarchy"].sort(key=lambda x: x.get("level", 99))

            # 3. Relationships 로드 (Table 노드 간 관계)
            rel_filter = ""
            if dataset_id:
                rel_filter = f"WHERE s.dataset_id = '{dataset_id}'"
            
            query_rels = f"""
                MATCH (s:Table)-[r]->(t:Table)
                {rel_filter}
                RETURN s.name as source, t.name as target, type(r) as type, 
                       properties(r) as props, s.dataset_id as dataset_id
            """
            results = self.neo4j.execute_query(query_rels)
            
            # 초기화
            self.ontology["relationships"] = []
            
            for record in results:
                props = record["props"]
                rel_data = {
                    "source_table": record["source"], 
                    "target_table": record["target"],
                    "relation_type": record["type"],
                    "source_column": props.get("source_column", ""),
                    "target_column": props.get("target_column", ""),
                    "confidence": props.get("confidence", 0),
                    "dataset_id": record.get("dataset_id")
                }
                self.ontology["relationships"].append(rel_data)

            # 4. Column Hierarchy 로드 (CHILD_OF 관계)
            hierarchy_filter = ""
            if dataset_id:
                hierarchy_filter = f"WHERE child.dataset_id = '{dataset_id}'"
            
            query_col_hierarchy = f"""
                MATCH (child:Column)-[r:CHILD_OF]->(parent:Column)
                {hierarchy_filter}
                RETURN child.name as child_col, child.table as table_name,
                       parent.name as parent_col,
                       r.cardinality as cardinality, r.hierarchy_type as hierarchy_type,
                       r.reasoning as reasoning, child.dataset_id as dataset_id
            """
            results = self.neo4j.execute_query(query_col_hierarchy)
            
            self.ontology["column_hierarchy"] = []
            for record in results:
                self.ontology["column_hierarchy"].append({
                    "table_name": record.get("table_name", "unknown"),
                    "child_column": record.get("child_col"),
                    "parent_column": record.get("parent_col"),
                    "cardinality": record.get("cardinality", "N:1"),
                    "hierarchy_type": record.get("hierarchy_type", "unknown"),
                    "reasoning": record.get("reasoning", ""),
                    "dataset_id": record.get("dataset_id")
                })

            # 5. Column Metadata 로드 (PostgreSQL JSONB에서)
            self.ontology["column_metadata"] = self._load_column_metadata_from_pg(dataset_id)

            # 6. Table Entities 로드 (NEW - Entity Understanding)
            self.ontology["table_entities"] = self._load_table_entities_from_pg(dataset_id)

            dataset_label = f" (dataset: {dataset_id})" if dataset_id else " (all datasets)"
            print(f"✅ [Ontology] Neo4j 데이터 로드 완료{dataset_label}")
            print(f"   - 용어: {len(self.ontology.get('definitions', {}))}개")
            print(f"   - 관계: {len(self.ontology.get('relationships', []))}개")
            print(f"   - 컬럼 계층: {len(self.ontology.get('column_hierarchy', []))}개")
            print(f"   - 컬럼 메타: {len(self.ontology.get('column_metadata', {}))}개 테이블")
            print(f"   - Entity 정보: {len(self.ontology.get('table_entities', {}))}개 테이블")
            
            return self.ontology

        except Exception as e:
            print(f"⚠️ [Ontology] Neo4j 로드 실패 (또는 데이터 없음): {e}")
            return self.ontology

    def save(self, ontology: Dict[str, Any], dataset_id: Optional[str] = None):
        """
        메모리의 온톨로지를 Neo4j에 동기화 (MERGE 사용)
        
        Dataset-First Architecture:
        - 모든 노드에 dataset_id 속성 추가
        - dataset_id로 노드를 구분하여 데이터셋별 독립성 보장
        
        Args:
            ontology: 저장할 온톨로지 딕셔너리
            dataset_id: 데이터셋 ID (None이면 ontology에서 추출 또는 current_dataset_id 사용)
        """
        self.ontology = ontology  # 메모리 업데이트
        
        # dataset_id 결정
        if dataset_id is None:
            dataset_id = ontology.get("dataset_id") or self.current_dataset_id or "default"
        
        self.current_dataset_id = dataset_id
        
        print(f"💾 [Ontology] Neo4j 저장 시작... (dataset: {dataset_id})")
        
        try:
            with self.neo4j.get_session() as session:
                # 1. Definitions -> Concept 노드 생성 (dataset_id 포함)
                # original_definition: 메타데이터 파일 원본
                # enriched_definition: LLM 분석 결과 (별도 메서드로 업데이트)
                for name, definition in ontology.get("definitions", {}).items():
                    session.run("""
                        MERGE (c:Concept {name: $name, dataset_id: $dataset_id})
                        SET c.original_definition = $definition,
                            c.last_updated = datetime()
                    """, name=name, definition=definition, dataset_id=dataset_id)
                
                # 2. Hierarchy -> 노드 속성 업데이트
                for h in ontology.get("hierarchy", []):
                    session.run("""
                        MERGE (c:Concept {name: $name, dataset_id: $dataset_id})
                        SET c.level = $level,
                            c.anchor_column = $anchor,
                            c.confidence = coalesce($conf, c.confidence)
                    """, name=h["entity_name"], level=h["level"], 
                         anchor=h.get("anchor_column"), conf=h.get("confidence"),
                         dataset_id=dataset_id)

                # 3. Relationships -> Table 노드 생성 후 엣지 생성
                for rel in ontology.get("relationships", []):
                    # 관계 타입 정제 (공백 제거, 대문자화)
                    rel_type = rel["relation_type"].upper().replace(" ", "_")
                    
                    # Dataset-First: Table 노드에도 dataset_id 추가
                    query = f"""
                        MERGE (s:Table {{name: $source, dataset_id: $dataset_id}})
                        MERGE (t:Table {{name: $target, dataset_id: $dataset_id}})
                        MERGE (s)-[r:`{rel_type}`]->(t)
                        SET r.source_column = $src_col,
                            r.target_column = $tgt_col,
                            r.confidence = $conf,
                            r.updated_at = datetime()
                    """
                    session.run(query, 
                        source=rel["source_table"],
                        target=rel["target_table"],
                        src_col=rel.get("source_column"),
                        tgt_col=rel.get("target_column"),
                        conf=rel.get("confidence", 0),
                        dataset_id=dataset_id
                    )

                # 4. Column Hierarchy -> CHILD_OF 관계 저장 (Intra-table hierarchy)
                for hierarchy in ontology.get("column_hierarchy", []):
                    table_name = hierarchy.get("table_name", "unknown")
                    child_col = hierarchy.get("child_column")
                    parent_col = hierarchy.get("parent_column")
                    cardinality = hierarchy.get("cardinality", "N:1")
                    hierarchy_type = hierarchy.get("hierarchy_type", "unknown")
                    reasoning = hierarchy.get("reasoning", "")
                    
                    # Column 노드 생성 및 CHILD_OF 관계 생성
                    session.run("""
                        MERGE (child:Column {name: $child_col, table: $table_name, dataset_id: $dataset_id})
                        MERGE (parent:Column {name: $parent_col, table: $table_name, dataset_id: $dataset_id})
                        MERGE (child)-[r:CHILD_OF]->(parent)
                        SET r.cardinality = $cardinality,
                            r.hierarchy_type = $hierarchy_type,
                            r.reasoning = $reasoning,
                            r.updated_at = datetime()
                        """, 
                        child_col=child_col,
                        parent_col=parent_col,
                        table_name=table_name,
                        cardinality=cardinality,
                        hierarchy_type=hierarchy_type,
                        reasoning=reasoning[:500] if reasoning else "",  # Neo4j 문자열 길이 제한
                        dataset_id=dataset_id
                    )
                
                if ontology.get("column_hierarchy"):
                    print(f"   - Column Hierarchy: {len(ontology['column_hierarchy'])}개 CHILD_OF 관계 저장")

                print(f"✅ [Ontology] Neo4j 저장(동기화) 완료 (dataset: {dataset_id})")
            
            # 4. Column Metadata -> PostgreSQL JSONB로 저장 (Neo4j 대신)
            if ontology.get("column_metadata"):
                self._save_column_metadata_to_pg(ontology["column_metadata"], dataset_id)
                print(f"✅ [Ontology] PostgreSQL column_metadata 저장 완료")
            
            # 5. Table Entities -> PostgreSQL + Neo4j로 저장 (NEW)
            if ontology.get("table_entities"):
                self._save_table_entities_to_pg(ontology["table_entities"], dataset_id)
                
                # Neo4j Table 노드에도 entity 정보 업데이트
                for table_name, entity_info in ontology["table_entities"].items():
                    session.run("""
                        MERGE (t:Table {name: $table_name, dataset_id: $dataset_id})
                        SET t.row_represents = $row_represents,
                            t.row_represents_kr = $row_represents_kr,
                            t.entity_identifier = $entity_identifier,
                            t.entity_confidence = $confidence,
                            t.updated_at = datetime()
                    """,
                        table_name=table_name,
                        dataset_id=dataset_id,
                        row_represents=entity_info.get("row_represents"),
                        row_represents_kr=entity_info.get("row_represents_kr"),
                        entity_identifier=entity_info.get("entity_identifier"),
                        confidence=entity_info.get("confidence", 0.0)
                    )
                print(f"✅ [Ontology] Table Entities 저장 완료 ({len(ontology['table_entities'])}개)")

        except Exception as e:
            print(f"❌ [Ontology] Neo4j 저장 실패: {e}")
            # raise e # 필요 시 주석 해제하여 에러 전파

    def enrich_concept(
        self, 
        concept_name: str, 
        enriched_definition: str,
        analysis_context: Optional[str] = None,
        dataset_id: Optional[str] = None
    ):
        """
        Neo4j Concept 노드에 LLM 분석 결과(enriched_definition) 추가
        
        Args:
            concept_name: 컨셉 이름 (예: 'caseid')
            enriched_definition: LLM이 분석한 풍부한 설명
            analysis_context: 분석 근거 (예: "user_feedback: '수술ID'")
            dataset_id: 데이터셋 ID
        """
        dataset_id = dataset_id or self.current_dataset_id or "default"
        
        try:
            with self.neo4j.get_session() as session:
                session.run("""
                    MERGE (c:Concept {name: $name, dataset_id: $dataset_id})
                    SET c.enriched_definition = $enriched_def,
                        c.analysis_context = $context,
                        c.enriched_at = datetime()
                """, 
                    name=concept_name,
                    enriched_def=enriched_definition,
                    context=analysis_context or "",
                    dataset_id=dataset_id
                )
            print(f"   ✅ [Neo4j] Concept '{concept_name}' enriched with LLM analysis")
        except Exception as e:
            print(f"   ⚠️ [Neo4j] Failed to enrich concept '{concept_name}': {e}")

    def enrich_concepts_batch(
        self,
        enrichments: List[Dict[str, str]],
        dataset_id: Optional[str] = None
    ):
        """
        여러 Concept을 한번에 enrich (배치 처리)
        
        Args:
            enrichments: [{"name": "caseid", "enriched_definition": "...", "analysis_context": "..."}]
            dataset_id: 데이터셋 ID
        """
        dataset_id = dataset_id or self.current_dataset_id or "default"
        
        try:
            with self.neo4j.get_session() as session:
                for item in enrichments:
                    session.run("""
                        MERGE (c:Concept {name: $name, dataset_id: $dataset_id})
                        SET c.enriched_definition = $enriched_def,
                            c.analysis_context = $context,
                            c.enriched_at = datetime()
                    """, 
                        name=item["name"],
                        enriched_def=item.get("enriched_definition", ""),
                        context=item.get("analysis_context", ""),
                        dataset_id=dataset_id
                    )
            print(f"   ✅ [Neo4j] {len(enrichments)} Concepts enriched with LLM analysis")
        except Exception as e:
            print(f"   ⚠️ [Neo4j] Failed to enrich concepts: {e}")

    def merge(self, new_knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """
        기존 온톨로지 + 새 지식 병합 (증분 업데이트)
        
        Args:
            new_knowledge: 새로 추가할 지식
        
        Returns:
            병합된 온톨로지
        """
        if not self.ontology:
            self.ontology = self._create_empty_ontology()
        
        # 1. Definitions 병합
        if "definitions" in new_knowledge:
            self.ontology["definitions"].update(new_knowledge["definitions"])
        
        # 2. Relationships 병합
        if "relationships" in new_knowledge:
            existing_rels = {
                self._rel_key(r): r 
                for r in self.ontology.get("relationships", [])
            }
            
            for new_rel in new_knowledge["relationships"]:
                key = self._rel_key(new_rel)
                if key not in existing_rels:
                    existing_rels[key] = new_rel
                else:
                    if new_rel.get("confidence", 0) > existing_rels[key].get("confidence", 0):
                        existing_rels[key] = new_rel
            
            self.ontology["relationships"] = list(existing_rels.values())
        
        # 3. Hierarchy 병합
        if "hierarchy" in new_knowledge:
            self._merge_hierarchy(new_knowledge["hierarchy"])
        
        # 4. File Tags 병합 (Neo4j 저장 로직에는 현재 포함 안 됨, 필요 시 추가)
        if "file_tags" in new_knowledge:
            if "file_tags" not in self.ontology:
                self.ontology["file_tags"] = {}
            self.ontology["file_tags"].update(new_knowledge["file_tags"])
        
        # 5. Column Metadata 병합 (NEW)
        if "column_metadata" in new_knowledge:
            if "column_metadata" not in self.ontology:
                self.ontology["column_metadata"] = {}
            
            for table_name, columns in new_knowledge["column_metadata"].items():
                if table_name not in self.ontology["column_metadata"]:
                    self.ontology["column_metadata"][table_name] = {}
                
                # 컬럼별로 병합 (confidence가 높은 것 우선)
                for col_name, col_info in columns.items():
                    existing = self.ontology["column_metadata"][table_name].get(col_name)
                    if not existing or col_info.get("confidence", 0) > existing.get("confidence", 0):
                        self.ontology["column_metadata"][table_name][col_name] = col_info
        
        # DB 저장
        self.save(self.ontology)
        
        return self.ontology
    
    def _rel_key(self, relationship: Dict) -> tuple:
        """관계 중복 체크를 위한 키 생성"""
        return (
            relationship.get("source_table", ""),
            relationship.get("target_table", ""),
            relationship.get("source_column", ""),
            relationship.get("target_column", "")
        )
    
    def _merge_hierarchy(self, new_hierarchy: List[Dict]):
        """계층 구조 병합"""
        if "hierarchy" not in self.ontology:
            self.ontology["hierarchy"] = []
        
        existing_entities = {h["entity_name"]: h for h in self.ontology["hierarchy"]}
        
        for new_level in new_hierarchy:
            entity = new_level["entity_name"]
            if entity not in existing_entities:
                self.ontology["hierarchy"].append(new_level)
                existing_entities[entity] = new_level
            else:
                if new_level.get("confidence", 0) > existing_entities[entity].get("confidence", 0):
                    # 기존 제거 후 추가 (리스트 갱신)
                    self.ontology["hierarchy"] = [
                        h for h in self.ontology["hierarchy"]
                        if h["entity_name"] != entity
                    ]
                    self.ontology["hierarchy"].append(new_level)
                    existing_entities[entity] = new_level # 맵도 갱신
        
        self.ontology["hierarchy"].sort(key=lambda x: x.get("level", 99))
    
    def _create_empty_ontology(self, dataset_id: Optional[str] = None) -> Dict[str, Any]:
        """빈 온톨로지 구조 생성"""
        return {
            "version": "2.2",  # Dataset-First + Entity Understanding
            "dataset_id": dataset_id,  # 소속 데이터셋
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "definitions": {},  # 기본 (enriched 우선, 없으면 original)
            "definitions_detail": {},  # {name: {original_definition, enriched_definition, analysis_context}}
            "relationships": [],
            "hierarchy": [],
            "file_tags": {},
            "column_metadata": {},  # table_name -> {col_name -> metadata}
            # NEW: Entity Understanding (Primary Key 대체)
            "table_entities": {},  # table_name -> EntityUnderstanding 형태
            "metadata": {
                "total_tables": 0,
                "total_definitions": 0,
                "total_relationships": 0,
                "total_columns": 0
            }
        }
    
    def set_dataset(self, dataset_id: str):
        """현재 작업 데이터셋 설정"""
        self.current_dataset_id = dataset_id
        if self.ontology.get("dataset_id") != dataset_id:
            # 새 데이터셋으로 전환 - 온톨로지 초기화 후 로드
            self.ontology = self._create_empty_ontology(dataset_id)
            self.load(dataset_id)
    
    def get_dataset_list(self) -> List[str]:
        """등록된 모든 데이터셋 ID 목록 조회"""
        try:
            query = """
                MATCH (c:Concept)
                WHERE c.dataset_id IS NOT NULL
                RETURN DISTINCT c.dataset_id as dataset_id
                UNION
                MATCH (t:Table)
                WHERE t.dataset_id IS NOT NULL
                RETURN DISTINCT t.dataset_id as dataset_id
            """
            results = self.neo4j.execute_query(query)
            return list(set([r["dataset_id"] for r in results if r["dataset_id"]]))
        except Exception as e:
            print(f"⚠️ [Ontology] 데이터셋 목록 조회 실패: {e}")
            return []
    
    def export_summary(self) -> str:
        """온톨로지 요약 출력"""
        if not self.ontology:
            return "온톨로지 없음"
        
        summary = []
        summary.append("\n" + "="*60)
        summary.append("📚 Ontology Summary (from Neo4j)")
        summary.append("="*60)
        
        # Definitions
        defs = self.ontology.get("definitions", {})
        summary.append(f"\n🔤 Definitions: {len(defs)}개")
        if defs:
            for i, (key, val) in enumerate(list(defs.items())[:3]):
                summary.append(f"   {i+1}. {key}: {val[:50]}...")
        
        # Relationships
        rels = self.ontology.get("relationships", [])
        summary.append(f"\n🔗 Relationships: {len(rels)}개")
        if rels:
            for i, rel in enumerate(rels[:3]):
                summary.append(
                    f"   {i+1}. {rel['source_table']}.{rel['source_column']} "
                    f"→ {rel['target_table']}.{rel['target_column']} ({rel['relation_type']})"
                )
        
        # Hierarchy
        hier = self.ontology.get("hierarchy", [])
        summary.append(f"\n🏗️  Hierarchy: {len(hier)}개 레벨")
        if hier:
            for h in hier:
                summary.append(
                    f"   L{h['level']}: {h['entity_name']} ({h.get('anchor_column', 'N/A')})"
                )
        
        summary.append("="*60)
        return "\n".join(summary)


# 전역 싱글톤 인스턴스
_global_ontology_manager = None

def get_ontology_manager() -> OntologyManager:
    """전역 온톨로지 매니저 반환"""
    global _global_ontology_manager
    if _global_ontology_manager is None:
        _global_ontology_manager = OntologyManager()
    return _global_ontology_manager
