# src/database/repositories/base.py
"""
Repository 베이스 클래스

모든 Repository가 상속받는 공통 기능:
- DB 연결 관리
- 공통 쿼리 헬퍼
- 트랜잭션 관리
"""

from typing import Any, List, Dict, Optional, Tuple
from abc import ABC
from ..connection import get_db_manager


class BaseRepository(ABC):
    """
    Repository 베이스 클래스
    
    모든 Repository는 이 클래스를 상속받아 공통 DB 연결을 사용합니다.
    """
    
    def __init__(self, db_manager=None):
        """
        Args:
            db_manager: DatabaseManager 인스턴스 (None이면 싱글톤 사용)
        """
        self.db = db_manager or get_db_manager()
    
    def _get_cursor(self):
        """커서 반환 (편의 메서드)"""
        conn = self.db.get_connection()
        return conn, conn.cursor()
    
    def _execute_query(
        self, 
        query: str, 
        params: Tuple = None,
        fetch: str = "all"  # "all", "one", "none"
    ) -> Any:
        """
        쿼리 실행 헬퍼
        
        Args:
            query: SQL 쿼리
            params: 쿼리 파라미터
            fetch: "all" = fetchall, "one" = fetchone, "none" = execute only
        
        Returns:
            쿼리 결과
        """
        conn, cursor = self._get_cursor()
        
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            if fetch == "all":
                return cursor.fetchall()
            elif fetch == "one":
                return cursor.fetchone()
            else:
                return None
        except Exception as e:
            print(f"[{self.__class__.__name__}] Query error: {e}")
            raise
    
    def _execute_many(self, query: str, params_list: List[Tuple]) -> int:
        """
        여러 행 삽입/업데이트 헬퍼
        
        Args:
            query: SQL 쿼리
            params_list: 파라미터 리스트
        
        Returns:
            영향받은 행 수
        """
        conn, cursor = self._get_cursor()
        
        try:
            cursor.executemany(query, params_list)
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            print(f"[{self.__class__.__name__}] Batch query error: {e}")
            raise
    
    def _commit(self):
        """커밋"""
        self.db.get_connection().commit()
    
    def _rollback(self):
        """롤백"""
        self.db.get_connection().rollback()
    
    @staticmethod
    def _parse_json_field(value: Any) -> Dict:
        """
        JSONB 필드 파싱 헬퍼
        
        PostgreSQL JSONB 필드가 이미 dict로 반환되는 경우와
        문자열로 반환되는 경우를 모두 처리
        """
        import json
        
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return {}

