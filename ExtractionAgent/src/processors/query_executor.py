# src/query_executor.py
"""
SQL 쿼리 실행기

생성된 SQL을 실행하고 결과를 반환합니다.
"""

from typing import Dict, Any, List, Optional
import pandas as pd
from ExtractionAgent.src.database.postgres import PostgresConnector


class QueryExecutor:
    """SQL 쿼리 실행기"""
    
    def __init__(self):
        self.db_manager = PostgresConnector()
    
    def execute(self, sql: str, limit: int = None) -> Dict[str, Any]:
        """
        SQL 쿼리 실행
        
        Args:
            sql: 실행할 SQL 쿼리
            limit: 결과 행 수 제한 (None이면 제한 없음)
        
        Returns:
            {
                "success": True/False,
                "data": DataFrame or None,
                "row_count": int,
                "columns": List[str],
                "error": None or error message
            }
        """
        try:
            conn = self.db_manager.get_connection()
            
            # LIMIT 추가 (대용량 결과 방지)
            if limit and "LIMIT" not in sql.upper():
                sql_with_limit = f"{sql.rstrip(';')} LIMIT {limit}"
            else:
                sql_with_limit = sql
            
            # pandas로 실행 (편리함)
            df = pd.read_sql(sql_with_limit, conn)
            
            return {
                "success": True,
                "data": df,
                "row_count": len(df),
                "columns": list(df.columns),
                "error": None
            }
            
        except Exception as e:
            return {
                "success": False,
                "data": None,
                "row_count": 0,
                "columns": [],
                "error": str(e)
            }
    
    def execute_with_chunking(self, sql: str, chunk_size: int = 10000) -> Dict[str, Any]:
        """
        대용량 결과를 청크 단위로 처리
        
        Args:
            sql: 실행할 SQL 쿼리
            chunk_size: 청크 크기
        
        Returns:
            {
                "success": True/False,
                "chunks": List[DataFrame],
                "total_rows": int,
                "columns": List[str],
                "error": None or error message
            }
        """
        try:
            conn = self.db_manager.get_connection()
            
            # 전체 결과를 청크로 읽기
            chunks = []
            total_rows = 0
            
            for chunk_df in pd.read_sql(sql, conn, chunksize=chunk_size):
                chunks.append(chunk_df)
                total_rows += len(chunk_df)
            
            columns = list(chunks[0].columns) if chunks else []
            
            return {
                "success": True,
                "chunks": chunks,
                "total_rows": total_rows,
                "columns": columns,
                "error": None
            }
            
        except Exception as e:
            return {
                "success": False,
                "chunks": [],
                "total_rows": 0,
                "columns": [],
                "error": str(e)
            }
    
    def test_query(self, sql: str) -> Dict[str, Any]:
        """
        쿼리 테스트 (LIMIT 1로 실행하여 문법 검증)
        
        Args:
            sql: 테스트할 SQL 쿼리
        
        Returns:
            {"valid": True/False, "error": "..."}
        """
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            # EXPLAIN으로 문법 검증
            explain_sql = f"EXPLAIN {sql}"
            cursor.execute(explain_sql)
            cursor.fetchall()
            
            return {"valid": True, "error": None}
            
        except Exception as e:
            return {"valid": False, "error": str(e)}

