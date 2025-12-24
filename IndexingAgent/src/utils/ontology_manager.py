"""
온톨로지 저장/로드/병합 관리자 (Neo4j + PostgreSQL 하이브리드)

Dataset-First Architecture:
- 모든 노드에 dataset_id 속성 추가
- 데이터셋별로 독립적인 온톨로지 관리
- 같은 이름의 Concept도 데이터셋별로 구분

역할 분리:
- Neo4j: 그래프 구조 (Concept, Table, Relationships, Hierarchy)
- PostgreSQL: 복잡한 문서형 데이터 (column_metadata - JSONB)
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from src.database.neo4j_connection import Neo4jConnection
from src.database.connection import get_db_manager
from src.utils.naming import sanitize_for_neo4j_label

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
        self.pg = get_db_manager()  # PostgreSQL for column_metadata
        self.ontology = self._create_empty_ontology()
        self.current_dataset_id: Optional[str] = None  # 현재 작업 중인 데이터셋
        
        # PostgreSQL column_metadata 테이블 초기화
        self._ensure_column_metadata_table()
    
    def _ensure_column_metadata_table(self):
        """PostgreSQL에 column_metadata 테이블 생성 (없으면)"""
        try:
            conn = self.pg.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS column_metadata (
                    dataset_id TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    column_name TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (dataset_id, table_name, column_name)
                )
            """)
            
            # 인덱스 생성 (쿼리 성능 향상)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_column_metadata_dataset 
                ON column_metadata(dataset_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_column_metadata_table 
                ON column_metadata(dataset_id, table_name)
            """)
            
            conn.commit()
        except Exception as e:
            logger.warning(f"column_metadata 테이블 생성 실패: {e}")
    
    def _load_column_metadata_from_pg(self, dataset_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """PostgreSQL에서 column_metadata 로드"""
        column_metadata = {}
        
        try:
            conn = self.pg.get_connection()
            cursor = conn.cursor()
            
            if dataset_id:
                cursor.execute("""
                    SELECT table_name, column_name, metadata
                    FROM column_metadata
                    WHERE dataset_id = %s
                """, (dataset_id,))
            else:
                cursor.execute("""
                    SELECT table_name, column_name, metadata
                    FROM column_metadata
                """)
            
            for row in cursor.fetchall():
                table_name, col_name, metadata = row
                
                if table_name not in column_metadata:
                    column_metadata[table_name] = {}
                
                # JSONB는 자동으로 dict로 변환됨
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                
                column_metadata[table_name][col_name] = metadata
                
        except Exception as e:
            logger.warning(f"column_metadata 로드 실패: {e}")
        
        return column_metadata
    
    def _save_column_metadata_to_pg(self, column_metadata: Dict, dataset_id: str):
        """PostgreSQL에 column_metadata 저장 (UPSERT)"""
        if not column_metadata:
            return
        
        try:
            conn = self.pg.get_connection()
            cursor = conn.cursor()
            
            for table_name, columns in column_metadata.items():
                for col_name, col_info in columns.items():
                    # JSONB로 저장
                    metadata_json = json.dumps(col_info, ensure_ascii=False, default=str)
                    
                    cursor.execute("""
                        INSERT INTO column_metadata (dataset_id, table_name, column_name, metadata, updated_at)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (dataset_id, table_name, column_name)
                        DO UPDATE SET 
                            metadata = EXCLUDED.metadata,
                            updated_at = CURRENT_TIMESTAMP
                    """, (dataset_id, table_name, col_name, metadata_json))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"column_metadata 저장 실패: {e}")
            raise
    
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

            dataset_label = f" (dataset: {dataset_id})" if dataset_id else " (all datasets)"
            print(f"✅ [Ontology] Neo4j 데이터 로드 완료{dataset_label}")
            print(f"   - 용어: {len(self.ontology.get('definitions', {}))}개")
            print(f"   - 관계: {len(self.ontology.get('relationships', []))}개")
            print(f"   - 컬럼 계층: {len(self.ontology.get('column_hierarchy', []))}개")
            print(f"   - 컬럼 메타: {len(self.ontology.get('column_metadata', {}))}개 테이블")
            
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
            "version": "2.1",  # Dataset-First + Enriched Definitions
            "dataset_id": dataset_id,  # NEW: 소속 데이터셋
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "definitions": {},  # 기본 (enriched 우선, 없으면 original)
            "definitions_detail": {},  # NEW: {name: {original_definition, enriched_definition, analysis_context}}
            "relationships": [],
            "hierarchy": [],
            "file_tags": {},
            "column_metadata": {},  # table_name -> {col_name -> metadata}
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
