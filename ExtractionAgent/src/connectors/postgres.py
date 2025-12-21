import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

class PostgresConnector:
    """PostgreSQL 연결 및 데이터 조회를 담당하는 클래스 (Read-only 권장)"""
    
    def __init__(self):
        self.host = os.getenv("POSTGRES_HOST", "localhost")
        self.port = os.getenv("POSTGRES_PORT", "5432")
        self.dbname = os.getenv("POSTGRES_DB", "medical_data")
        self.user = os.getenv("POSTGRES_USER", "postgres")
        self.password = os.getenv("POSTGRES_PASSWORD", "")

    def get_connection(self):
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password
        )

    def get_schema_info(self) -> List[Dict[str, Any]]:
        """DB의 모든 테이블 및 컬럼 정보를 조회"""
        query = """
        SELECT 
            table_name, 
            column_name, 
            data_type,
            is_nullable
        FROM 
            information_schema.columns 
        WHERE 
            table_schema = 'public'
        ORDER BY 
            table_name, ordinal_position;
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query)
                return cur.fetchall()

    def execute_query(self, sql: str) -> List[Dict[str, Any]]:
        """SQL 쿼리를 실행하고 결과를 반환 (SELECT 전용)"""
        # 보안을 위해 간단한 검사 (실제 환경에서는 더 강력한 방어 필요)
        forbidden_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER"]
        if any(keyword in sql.upper() for keyword in forbidden_keywords):
            raise ValueError("실행이 금지된 SQL 키워드가 포함되어 있습니다.")

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql)
                return cur.fetchall()

