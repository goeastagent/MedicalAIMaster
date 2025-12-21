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
        self.database = os.getenv("NEO4J_DATABASE", "neo4j") # 기본값 추가
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
        Neo4j에서 테이블 간 관계 및 계층 정보를 조회
        """
        if not self.driver:
            return {"relationships": [], "hierarchy": [], "warning": "Neo4j driver not initialized"}
        
        context = {
            "relationships": [],
            "hierarchy": []
        }
        
        try:
            with self.driver.session(database=self.database) as session:
                # 1. 관계 조회 (수정됨: 실제 IndexingAgent가 생성하는 구조에 맞춤)
                # 가정: (:Table)-[:HAS_RELATION]->(:Table) 또는 유사 구조
                # 정확한 라벨/타입 확인을 위해 포괄적인 쿼리 사용
                rel_query = """
                MATCH (a:Table)-[r]->(b:Table)
                RETURN 
                    a.name as source, 
                    b.name as target, 
                    type(r) as type, 
                    r.source_column as s_col, 
                    r.target_column as t_col,
                    r.confidence as confidence
                LIMIT 100
                """
                results = session.run(rel_query)
                for record in results:
                    context["relationships"].append({
                        "source": record["source"],
                        "target": record["target"],
                        "type": record["type"],
                        "source_col": record["s_col"],
                        "target_col": record["t_col"],
                        "confidence": record.get("confidence")
                    })
                
                # 2. 계층 조회 (수정됨: Entity 계층 구조)
                # 가정: (:Entity) 노드가 level 속성을 가짐
                hier_query = """
                MATCH (n:Entity) 
                RETURN 
                    n.name as name, 
                    n.level as level, 
                    n.anchor_column as anchor 
                ORDER BY n.level
                """
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

