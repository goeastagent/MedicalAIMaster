import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Neo4j 드라이버가 설치되어 있어야 함: pip install neo4j
try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

load_dotenv()

class Neo4jConnector:
    """Neo4j 온톨로지 정보를 조회하는 클래스"""
    
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "password")
        self.driver = None
        
        if GraphDatabase:
            try:
                self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            except Exception as e:
                print(f"⚠️ Neo4j 연결 실패: {e}")

    def close(self):
        if self.driver:
            self.driver.close()

    def get_ontology_context(self) -> Dict[str, Any]:
        """
        Neo4j에서 테이블 간 관계 및 계층 정보를 조회
        현재는 예시 쿼리를 반환하도록 구현
        """
        if not self.driver:
            return {"relationships": [], "hierarchy": [], "warning": "Neo4j driver not initialized"}

        # 실제 구현 시에는 Cypher 쿼리를 통해 관계 정보를 가져옴
        # 예: MATCH (t1:Table)-[r:CONNECTED_TO]->(t2:Table) RETURN t1.name, r.type, t2.name
        
        context = {
            "relationships": [],
            "hierarchy": []
        }
        
        try:
            with self.driver.session() as session:
                # 1. 관계 조회 예시
                rel_query = "MATCH (a:Table)-[r:RELATION]->(b:Table) RETURN a.name as source, b.name as target, r.type as type, r.source_col as s_col, r.target_col as t_col"
                results = session.run(rel_query)
                for record in results:
                    context["relationships"].append({
                        "source": record["source"],
                        "target": record["target"],
                        "type": record["type"],
                        "source_col": record["s_col"],
                        "target_col": record["t_col"]
                    })
                
                # 2. 계층 조회 예시
                hier_query = "MATCH (n:Entity) RETURN n.name as name, n.level as level, n.anchor as anchor ORDER BY n.level"
                results = session.run(hier_query)
                for record in results:
                    context["hierarchy"].append({
                        "name": record["name"],
                        "level": record["level"],
                        "anchor": record["anchor"]
                    })
        except Exception as e:
            print(f"⚠️ Neo4j 쿼리 중 에러 발생: {e}")
            
        return context

