# shared/config/database.py
"""
Database Configuration

PostgreSQL 및 Neo4j 데이터베이스 연결 설정
"""
import os
from dotenv import load_dotenv

# .env 파일이 있다면 로드
load_dotenv()


class PostgresConfig:
    """PostgreSQL 데이터베이스 설정"""
    HOST = os.getenv("POSTGRES_HOST", "localhost")
    PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    USER = os.getenv("POSTGRES_USER", "postgres")
    PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
    DATABASE = os.getenv("POSTGRES_DATABASE", "medical_indexing")
    
    @classmethod
    def connection_string(cls) -> str:
        """psycopg2용 connection string 반환"""
        return f"host={cls.HOST} port={cls.PORT} dbname={cls.DATABASE} user={cls.USER} password={cls.PASSWORD}"


class Neo4jConfig:
    """Neo4j 데이터베이스 설정"""
    URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    USER = os.getenv("NEO4J_USER", "neo4j")
    PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
    DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
    
    # Neo4j 활성화 여부 (테스트 시 비활성화 가능)
    ENABLED: bool = os.getenv("NEO4J_ENABLED", "true").lower() == "true"

