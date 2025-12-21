import os
from typing import List, Dict, Any, Optional
from ExtractionAgent.src.config import Config

# Neo4j 드라이버가 설치되어 있어야 함: pip install neo4j
try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

class Neo4jConnector:
    """Neo4j 온톨로지 정보를 조회하는 클래스"""
    
    def __init__(self):
        self.uri = Config.NEO4J_URI
        self.user = Config.NEO4J_USER
        self.password = Config.NEO4J_PASSWORD
        self.database = Config.NEO4J_DATABASE
        self.driver = None
        
        if GraphDatabase:
            try:
                self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
                # 연결 확인
                self.driver.verify_connectivity()
                print(f"✅ Neo4j Connected: {self.uri}")
            except Exception as e:
                print(f"⚠️ Neo4j 연결 실패: {e}")

    def close(self):
        if self.driver:
            self.driver.close()

    def get_ontology_context(self) -> Dict[str, Any]:
        """
        Neo4j에서 온톨로지 정보(Definitions, Relationships, Hierarchy)를 조회
        """
        if not self.driver:
            return {
                "definitions": {},
                "relationships": [], 
                "hierarchy": [], 
                "warning": "Neo4j driver not initialized"
            }
        
        context = {
            "definitions": {},
            "relationships": [],
            "hierarchy": []
        }
        
        try:
            with self.driver.session(database=self.database) as session:
                # 1. Definitions 조회
                # 가정: (:Concept) 노드가 name, definition 속성을 가짐
                def_query = "MATCH (c:Concept) WHERE c.definition IS NOT NULL RETURN c.name as name, c.definition as definition"
                results = session.run(def_query)
                for record in results:
                    context["definitions"][record["name"]] = record["definition"]

                # 2. 관계 조회
                # 가정: (:Concept)-[:HAS_RELATION]->(:Concept) 또는 (:Table)-... 구조일 수 있음.
                # IndexingAgent의 OntologyManager.save() 로직을 보면 Concept 노드 간의 관계임.
                rel_query = """
                MATCH (s:Concept)-[r]->(t:Concept)
                RETURN 
                    s.name as source, 
                    t.name as target, 
                    type(r) as type, 
                    r.source_column as s_col, 
                    r.target_column as t_col,
                    r.confidence as confidence
                LIMIT 200
                """
                results = session.run(rel_query)
                for record in results:
                    context["relationships"].append({
                        "source_table": record["source"],
                        "target_table": record["target"],
                        "relation_type": record["type"],
                        "source_column": record["s_col"],
                        "target_column": record["t_col"],
                        "confidence": record.get("confidence", 0)
                    })
                
                # 3. 계층 조회
                hier_query = """
                MATCH (c:Concept) 
                WHERE c.level IS NOT NULL
                RETURN 
                    c.name as name, 
                    c.level as level, 
                    c.anchor_column as anchor,
                    c.confidence as confidence
                ORDER BY c.level
                """
                results = session.run(hier_query)
                for record in results:
                    context["hierarchy"].append({
                        "entity_name": record["name"],
                        "level": record["level"],
                        "anchor_column": record["anchor"],
                        "confidence": record.get("confidence", 0)
                    })
                    
        except Exception as e:
            print(f"⚠️ Neo4j 쿼리 중 에러 발생: {e}")
            
        return context
