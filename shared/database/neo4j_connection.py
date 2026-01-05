# shared/database/neo4j_connection.py
"""
Neo4j 데이터베이스 연결 관리자

Singleton 패턴으로 구현되어 애플리케이션 전체에서 하나의 연결만 사용합니다.
"""

import logging
from typing import Optional, List, Any

from neo4j import GraphDatabase
from shared.config import Neo4jConfig

logger = logging.getLogger(__name__)


class Neo4jConnection:
    """
    Neo4j 데이터베이스 연결 관리 (Singleton)
    
    Usage:
        # 방법 1: 클래스 직접 사용 (항상 같은 인스턴스 반환)
        neo4j = Neo4jConnection()
        
        # 방법 2: 헬퍼 함수 사용
        neo4j = get_neo4j_connection()
        
        # 쿼리 실행
        results = neo4j.execute_query("MATCH (n) RETURN n LIMIT 10")
        
        # 세션 직접 사용 (트랜잭션 제어 필요시)
        with neo4j.get_session() as session:
            session.run("CREATE (n:Node {name: $name})", name="test")
    """
    
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Neo4jConnection, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """초기화 (Singleton이므로 한 번만 실행)"""
        if Neo4jConnection._initialized:
            return
        
        self._driver = None
        Neo4jConnection._initialized = True

    def connect(self):
        """Neo4j 드라이버 연결"""
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(
                    Neo4jConfig.URI,
                    auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
                )
                self.verify_connection()
                logger.info(f"✅ Neo4j Connected: {Neo4jConfig.URI} (database: {Neo4jConfig.DATABASE})")
            except Exception as e:
                logger.error(f"❌ Neo4j 연결 실패: {e}")
                raise e

    def verify_connection(self):
        """연결 확인"""
        if self._driver:
            self._driver.verify_connectivity()

    def close(self):
        """연결 종료"""
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")

    def get_session(self):
        """
        세션 생성
        
        Returns:
            Neo4j Session (context manager로 사용 권장)
        """
        if self._driver is None:
            self.connect()
        return self._driver.session(database=Neo4jConfig.DATABASE)

    def execute_query(self, query: str, parameters: Optional[dict] = None, db: Optional[str] = None) -> List[Any]:
        """
        단일 쿼리 실행 및 결과 반환
        
        Args:
            query: Cypher 쿼리 문자열
            parameters: 쿼리 파라미터 (선택)
            db: 데이터베이스 이름 (선택, 기본값: Neo4jConfig.DATABASE)
        
        Returns:
            쿼리 결과 레코드 리스트
        
        Note:
            대량 데이터 조회 시 메모리 이슈가 발생할 수 있습니다.
            대량 처리가 필요한 경우 get_session()으로 세션을 직접 관리하세요.
        """
        if self._driver is None:
            self.connect()
            
        with self._driver.session(database=db or Neo4jConfig.DATABASE) as session:
            result = session.run(query, parameters)
            return [record for record in result]
    
    @classmethod
    def reset_instance(cls):
        """
        싱글톤 인스턴스 리셋 (테스트용)
        
        주의: 기존 연결이 닫히지 않으므로, 리셋 전에 close()를 호출해야 합니다.
        """
        if cls._instance and cls._instance._driver:
            cls._instance.close()
        cls._instance = None
        cls._initialized = False
        logger.debug("Neo4jConnection instance reset")


def get_neo4j_connection() -> Neo4jConnection:
    """
    전역 Neo4j 커넥션 반환 (Singleton)
    
    Returns:
        Neo4jConnection 인스턴스
    """
    return Neo4jConnection()
