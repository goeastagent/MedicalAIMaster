import logging
import os
from neo4j import GraphDatabase
from src.config import Neo4jConfig

logger = logging.getLogger(__name__)

class Neo4jConnection:
    """
    Neo4j 데이터베이스 연결 관리 (Singleton)
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Neo4jConnection, cls).__new__(cls)
            cls._instance._driver = None
        return cls._instance

    def connect(self):
        """Neo4j 드라이버 연결"""
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(
                    Neo4jConfig.URI,
                    auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
                )
                self.verify_connection()
                logger.info("✅ Neo4j Connected Successfully")
            except Exception as e:
                logger.error(f"❌ Failed to connect to Neo4j: {e}")
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

    def get_session(self):
        """세션 생성"""
        if self._driver is None:
            self.connect()
        return self._driver.session(database=Neo4jConfig.DATABASE)

    def execute_query(self, query, parameters=None, db=None):
        """단일 쿼리 실행 및 결과 반환"""
        if self._driver is None:
            self.connect()
            
        with self._driver.session(database=db or Neo4jConfig.DATABASE) as session:
            result = session.run(query, parameters)
            # 결과를 리스트로 변환 (주의: 대량 데이터 시 메모리 이슈 가능)
            return [record for record in result]
            
# 전역 싱글톤 인스턴스 (필요 시 사용)
def get_neo4j_connection():
    return Neo4jConnection()

