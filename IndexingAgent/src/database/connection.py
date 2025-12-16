# src/database/connection.py
"""
PostgreSQL 데이터베이스 연결 관리자

복합 PK, FK Cascade 등 완전한 기능 지원
"""

import os
from typing import Optional


class DatabaseManager:
    """PostgreSQL 데이터베이스 연결 및 관리"""
    
    def __init__(self):
        """
        환경변수에서 PostgreSQL 연결 정보 로드
        
        필요한 환경변수:
        - POSTGRES_HOST (기본값: localhost)
        - POSTGRES_PORT (기본값: 5432)
        - POSTGRES_DB (기본값: medical_data)
        - POSTGRES_USER (기본값: postgres)
        - POSTGRES_PASSWORD (기본값: 빈 문자열)
        """
        self.db_host = os.getenv("POSTGRES_HOST", "localhost")
        self.db_port = os.getenv("POSTGRES_PORT", "5432")
        self.db_name = os.getenv("POSTGRES_DB", "medical_data")
        self.db_user = os.getenv("POSTGRES_USER", "postgres")
        self.db_password = os.getenv("POSTGRES_PASSWORD", "")
        
        self.connection = None
    
    def connect(self):
        """PostgreSQL 연결"""
        try:
            import psycopg2
        except ImportError:
            raise ImportError(
                "psycopg2가 설치되지 않았습니다.\n"
                "pip install psycopg2-binary"
            )
        
        try:
            self.connection = psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password
            )
            # autocommit 비활성화 (트랜잭션 제어)
            self.connection.autocommit = False
            
            return self.connection
            
        except Exception as e:
            raise ConnectionError(
                f"PostgreSQL 연결 실패: {e}\n"
                f"연결 정보: {self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}\n"
                ".env 파일의 POSTGRES_* 설정을 확인하세요."
            )
    
    def get_connection(self):
        """연결 반환 (없으면 생성)"""
        if self.connection is None:
            return self.connect()
        return self.connection
    
    def get_sqlalchemy_engine(self):
        """
        SQLAlchemy 엔진 반환 (pandas to_sql용)
        
        Returns:
            sqlalchemy.engine.Engine
        """
        try:
            from sqlalchemy import create_engine
        except ImportError:
            raise ImportError("sqlalchemy가 필요합니다. pip install sqlalchemy")
        
        # PostgreSQL 연결 문자열
        conn_str = f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        
        return create_engine(conn_str)
    
    def close(self):
        """연결 종료"""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def execute(self, query: str, params: tuple = None):
        """쿼리 실행"""
        conn = self.get_connection()
        if params:
            return conn.execute(query, params)
        else:
            return conn.execute(query)
    
    def commit(self):
        """커밋"""
        if self.connection:
            self.connection.commit()
    
    def table_exists(self, table_name: str) -> bool:
        """테이블 존재 여부 확인"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = %s
            )
        """, (table_name,))
        
        return cursor.fetchone()[0]
    
    def get_table_info(self, table_name: str):
        """테이블 정보 조회 (컬럼 리스트)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        
        return cursor.fetchall()


# 전역 싱글톤
_global_db_manager = None

def get_db_manager() -> DatabaseManager:
    """전역 DB 매니저 반환"""
    global _global_db_manager
    if _global_db_manager is None:
        _global_db_manager = DatabaseManager()
    return _global_db_manager

