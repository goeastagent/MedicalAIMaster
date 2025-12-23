"""
온톨로지 저장/로드/병합 관리자 (Neo4j 기반)

기존 JSON 파일 기반에서 Neo4j 그래프 데이터베이스로 전환됨.
"""

import json
import logging
from typing import Dict, Any, List
from datetime import datetime
from src.database.neo4j_connection import Neo4jConnection

logger = logging.getLogger(__name__)

class OntologyManager:
    """온톨로지 지식 베이스 관리자 (Neo4j 기반)"""
    
    def __init__(self, db_path: str = "data/processed/ontology_db.json"):
        # db_path는 하위 호환성을 위해 남겨두지만 실제로는 사용하지 않음 (또는 마이그레이션 용도)
        self.neo4j = Neo4jConnection()
        self.ontology = self._create_empty_ontology()
        
    def load(self) -> Dict[str, Any]:
        """
        Neo4j에서 온톨로지를 로드하여 메모리 상의 딕셔너리로 재구성
        (기존 코드와의 호환성을 위해 딕셔너리 구조 유지)
        
        Returns:
            온톨로지 딕셔너리
        """
        try:
            # 1. Definitions (Concepts) 로드
            query_concepts = "MATCH (c:Concept) RETURN c.name as name, c.definition as definition"
            results = self.neo4j.execute_query(query_concepts)
            
            for record in results:
                self.ontology["definitions"][record["name"]] = record["definition"]

            # 2. Hierarchy 로드
            query_hier = "MATCH (c:Concept) WHERE c.level IS NOT NULL RETURN c"
            results = self.neo4j.execute_query(query_hier)
            
            # 초기화
            self.ontology["hierarchy"] = []
            
            for record in results:
                node = record["c"]
                self.ontology["hierarchy"].append({
                    "entity_name": node.get("name"),
                    "level": node.get("level"),
                    "anchor_column": node.get("anchor_column"),
                    "confidence": node.get("confidence", 0)
                })
            # 레벨 정렬
            self.ontology["hierarchy"].sort(key=lambda x: x.get("level", 99))

            # 3. Relationships 로드 (Table 노드 간 관계)
            query_rels = """
            MATCH (s:Table)-[r]->(t:Table)
            RETURN s.name as source, t.name as target, type(r) as type, properties(r) as props
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
                    "confidence": props.get("confidence", 0)
                }
                self.ontology["relationships"].append(rel_data)

            # 4. Column Metadata 로드 (NEW)
            query_cols = """
            MATCH (c:Column)
            RETURN c.table_name as table_name, c.original_name as original_name,
                   c.full_name as full_name, c.description as description,
                   c.description_kr as description_kr, c.data_type as data_type,
                   c.unit as unit, c.typical_range as typical_range,
                   c.is_pii as is_pii, c.confidence as confidence
            """
            results = self.neo4j.execute_query(query_cols)
            
            # 초기화
            self.ontology["column_metadata"] = {}
            
            for record in results:
                table_name = record.get("table_name", "unknown")
                col_name = record.get("original_name", "unknown")
                
                if table_name not in self.ontology["column_metadata"]:
                    self.ontology["column_metadata"][table_name] = {}
                
                self.ontology["column_metadata"][table_name][col_name] = {
                    "original_name": col_name,
                    "full_name": record.get("full_name"),
                    "description": record.get("description"),
                    "description_kr": record.get("description_kr"),
                    "data_type": record.get("data_type"),
                    "unit": record.get("unit"),
                    "typical_range": record.get("typical_range"),
                    "is_pii": record.get("is_pii", False),
                    "confidence": record.get("confidence", 0)
                }

            print("✅ [Ontology] Neo4j 데이터 로드 완료")
            print(f"   - 용어: {len(self.ontology.get('definitions', {}))}개")
            print(f"   - 관계: {len(self.ontology.get('relationships', []))}개")
            print(f"   - 컬럼 메타: {len(self.ontology.get('column_metadata', {}))}개 테이블")
            
            return self.ontology

        except Exception as e:
            print(f"⚠️ [Ontology] Neo4j 로드 실패 (또는 데이터 없음): {e}")
            return self.ontology

    def save(self, ontology: Dict[str, Any]):
        """
        메모리의 온톨로지를 Neo4j에 동기화 (MERGE 사용)
        
        Args:
            ontology: 저장할 온톨로지 딕셔너리
        """
        self.ontology = ontology # 메모리 업데이트
        
        print("💾 [Ontology] Neo4j 저장 시작...")
        
        try:
            with self.neo4j.get_session() as session:
                # 1. Definitions -> Concept 노드 생성
                for name, definition in ontology.get("definitions", {}).items():
                    session.run("""
                        MERGE (c:Concept {name: $name})
                        SET c.definition = $definition,
                            c.last_updated = datetime()
                    """, name=name, definition=definition)
                
                # 2. Hierarchy -> 노드 속성 업데이트
                for h in ontology.get("hierarchy", []):
                    session.run("""
                        MERGE (c:Concept {name: $name})
                        SET c.level = $level,
                            c.anchor_column = $anchor,
                            c.confidence = coalesce($conf, c.confidence)
                    """, name=h["entity_name"], level=h["level"], 
                         anchor=h.get("anchor_column"), conf=h.get("confidence"))

                # 3. Relationships -> Table 노드 생성 후 엣지 생성
                for rel in ontology.get("relationships", []):
                    # 관계 타입 정제 (공백 제거, 대문자화)
                    rel_type = rel["relation_type"].upper().replace(" ", "_")
                    
                    # ⭐ [FIX] Table 노드를 먼저 생성/확인 후 관계 설정
                    # Concept 노드가 아닌 Table 노드 사용
                    query = f"""
                        MERGE (s:Table {{name: $source}})
                        MERGE (t:Table {{name: $target}})
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
                        conf=rel.get("confidence", 0)
                    )

                # 4. Column Metadata -> Column 노드 생성 (NEW)
                for table_name, columns in ontology.get("column_metadata", {}).items():
                    for col_name, col_info in columns.items():
                        session.run("""
                            MERGE (col:Column {table_name: $table_name, original_name: $original_name})
                            SET col.full_name = $full_name,
                                col.description = $description,
                                col.description_kr = $description_kr,
                                col.data_type = $data_type,
                                col.unit = $unit,
                                col.typical_range = $typical_range,
                                col.is_pii = $is_pii,
                                col.confidence = $confidence,
                                col.last_updated = datetime()
                        """, 
                            table_name=table_name,
                            original_name=col_name,
                            full_name=col_info.get("full_name"),
                            description=col_info.get("description"),
                            description_kr=col_info.get("description_kr"),
                            data_type=col_info.get("data_type"),
                            unit=col_info.get("unit"),
                            typical_range=col_info.get("typical_range"),
                            is_pii=col_info.get("is_pii", False),
                            confidence=col_info.get("confidence", 0)
                        )

                print("✅ [Ontology] Neo4j 저장(동기화) 완료")

        except Exception as e:
            print(f"❌ [Ontology] Neo4j 저장 실패: {e}")
            # raise e # 필요 시 주석 해제하여 에러 전파

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
    
    def _create_empty_ontology(self) -> Dict[str, Any]:
        """빈 온톨로지 구조 생성"""
        return {
            "version": "1.1",  # Version bump for column_metadata support
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "definitions": {},
            "relationships": [],
            "hierarchy": [],
            "file_tags": {},
            "column_metadata": {},  # NEW: table_name -> {col_name -> metadata}
            "metadata": {
                "total_tables": 0,
                "total_definitions": 0,
                "total_relationships": 0,
                "total_columns": 0
            }
        }
    
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
