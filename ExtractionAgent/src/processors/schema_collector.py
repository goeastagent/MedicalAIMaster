# src/schema_collector.py
"""
동적 스키마 정보 수집기

PostgreSQL의 information_schema를 조회하여 현재 DB의 모든 테이블과 컬럼 정보를 수집합니다.
"""

from typing import Dict, List, Any
from ExtractionAgent.src.database.postgres import PostgresConnector


class SchemaCollector:
    """동적 스키마 정보 수집기"""
    
    def __init__(self):
        self.db_manager = PostgresConnector()
        self._schema_cache = None
    
    def get_all_tables(self) -> List[str]:
        """
        모든 테이블 목록 조회
        
        Returns:
            테이블명 리스트
        """
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        return tables
    
    def get_table_columns(self, table_name: str) -> List[Dict[str, Any]]:
        """
        특정 테이블의 컬럼 정보 조회
        
        Args:
            table_name: 테이블명
        
        Returns:
            컬럼 정보 리스트 [{"name": "...", "type": "...", "nullable": True/False}]
        """
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        
        columns = []
        for row in cursor.fetchall():
            columns.append({
                "name": row[0],
                "type": row[1],
                "nullable": row[2] == 'YES',
                "default": row[3]
            })
        
        return columns
    
    def get_foreign_keys(self, table_name: str) -> List[Dict[str, Any]]:
        """
        특정 테이블의 외래키 정보 조회
        
        Args:
            table_name: 테이블명
        
        Returns:
            FK 정보 리스트 [{"column": "...", "references_table": "...", "references_column": "..."}]
        """
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_name = %s
            AND tc.table_schema = 'public'
        """, (table_name,))
        
        fks = []
        for row in cursor.fetchall():
            fks.append({
                "column": row[0],
                "references_table": row[1],
                "references_column": row[2]
            })
        
        return fks
    
    def get_primary_keys(self, table_name: str) -> List[str]:
        """
        특정 테이블의 Primary Key 컬럼 조회
        
        Args:
            table_name: 테이블명
        
        Returns:
            PK 컬럼명 리스트
        """
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
        """, (table_name,))
        
        pk_cols = [row[0] for row in cursor.fetchall()]
        return pk_cols
    
    def get_table_row_count(self, table_name: str) -> int:
        """
        테이블의 행 개수 조회
        
        Args:
            table_name: 테이블명
        
        Returns:
            행 개수
        """
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        return cursor.fetchone()[0]
    
    def collect_full_schema(self) -> Dict[str, Any]:
        """
        전체 스키마 정보 수집 (캐싱 지원)
        
        Returns:
            전체 스키마 정보 딕셔너리
        """
        if self._schema_cache is not None:
            return self._schema_cache
        
        tables = self.get_all_tables()
        schema_info = {
            "tables": {},
            "summary": {
                "total_tables": len(tables),
                "table_names": tables
            }
        }
        
        for table_name in tables:
            columns = self.get_table_columns(table_name)
            primary_keys = self.get_primary_keys(table_name)
            foreign_keys = self.get_foreign_keys(table_name)
            row_count = self.get_table_row_count(table_name)
            
            schema_info["tables"][table_name] = {
                "columns": columns,
                "primary_keys": primary_keys,
                "foreign_keys": foreign_keys,
                "row_count": row_count
            }
        
        self._schema_cache = schema_info
        return schema_info
    
    def format_schema_for_prompt(self, max_tables: int = None) -> str:
        """
        프롬프트에 포함할 수 있는 형태로 스키마 정보 포맷팅
        
        Args:
            max_tables: 최대 테이블 수 (None이면 전체)
        
        Returns:
            포맷팅된 스키마 문자열
        """
        schema = self.collect_full_schema()
        tables = schema["tables"]
        
        # 테이블 수 제한 (너무 많으면 일부만)
        if max_tables and len(tables) > max_tables:
            # 행 개수가 많은 테이블 우선 선택
            sorted_tables = sorted(
                tables.items(),
                key=lambda x: x[1]["row_count"],
                reverse=True
            )
            tables = dict(sorted_tables[:max_tables])
        
        lines = []
        lines.append("=" * 80)
        lines.append("DATABASE SCHEMA")
        lines.append("=" * 80)
        lines.append(f"\nTotal Tables: {schema['summary']['total_tables']}")
        lines.append("")
        
        for table_name, table_info in tables.items():
            lines.append(f"Table: {table_name}")
            lines.append(f"  Rows: {table_info['row_count']:,}")
            
            # Primary Keys
            if table_info["primary_keys"]:
                pk_str = ", ".join(table_info["primary_keys"])
                lines.append(f"  Primary Keys: {pk_str}")
            
            # Foreign Keys
            if table_info["foreign_keys"]:
                lines.append("  Foreign Keys:")
                for fk in table_info["foreign_keys"]:
                    lines.append(
                        f"    - {fk['column']} → {fk['references_table']}.{fk['references_column']}"
                    )
            
            # Columns
            lines.append("  Columns:")
            for col in table_info["columns"]:
                nullable = "NULL" if col["nullable"] else "NOT NULL"
                pk_mark = " [PK]" if col["name"] in table_info["primary_keys"] else ""
                lines.append(
                    f"    - {col['name']}: {col['type']} {nullable}{pk_mark}"
                )
            
            lines.append("")
        
        return "\n".join(lines)
    
    def clear_cache(self):
        """스키마 캐시 초기화"""
        self._schema_cache = None
    
    def get_sample_data(self, table_name: str, limit: int = 3) -> List[Dict[str, Any]]:
        """
        테이블의 샘플 데이터 조회
        
        Args:
            table_name: 테이블명
            limit: 샘플 행 개수
        
        Returns:
            샘플 데이터 리스트 [{"col1": val1, "col2": val2}, ...]
        """
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            # 테이블명 안전하게 인용 (SQL Injection 방지)
            cursor.execute(f'SELECT * FROM "{table_name}" LIMIT %s', (limit,))
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            print(f"샘플 데이터 조회 실패 ({table_name}): {e}")
            return []
    
    def format_sample_data_for_prompt(self, table_name: str, limit: int = 3) -> str:
        """
        테이블의 샘플 데이터를 프롬프트용으로 포맷팅
        
        Args:
            table_name: 테이블명
            limit: 샘플 행 개수
        
        Returns:
            포맷팅된 샘플 데이터 문자열
        """
        samples = self.get_sample_data(table_name, limit)
        
        if not samples:
            return f"  (No sample data available for {table_name})"
        
        # 컬럼명
        columns = list(samples[0].keys())
        
        # 헤더
        lines = []
        lines.append(f"  Sample data from '{table_name}':")
        
        # 테이블 형식으로 포맷팅 (간단한 형태)
        header = " | ".join(columns[:8])  # 최대 8개 컬럼만 표시
        lines.append(f"    | {header} |")
        lines.append(f"    |{'-' * (len(header) + 2)}|")
        
        for row in samples:
            values = []
            for col in columns[:8]:
                val = row.get(col, "")
                # 긴 값은 자르기
                val_str = str(val)[:20] if val is not None else "NULL"
                values.append(val_str)
            lines.append(f"    | {' | '.join(values)} |")
        
        return "\n".join(lines)
    
    def format_schema_with_samples_for_prompt(self, max_tables: int = None, sample_limit: int = 2) -> str:
        """
        스키마 정보 + 샘플 데이터를 함께 프롬프트용으로 포맷팅
        
        Args:
            max_tables: 최대 테이블 수 (None이면 전체)
            sample_limit: 테이블당 샘플 행 개수
        
        Returns:
            포맷팅된 스키마 + 샘플 데이터 문자열
        """
        schema = self.collect_full_schema()
        tables = schema["tables"]
        
        # 테이블 수 제한 (너무 많으면 일부만)
        if max_tables and len(tables) > max_tables:
            sorted_tables = sorted(
                tables.items(),
                key=lambda x: x[1]["row_count"],
                reverse=True
            )
            tables = dict(sorted_tables[:max_tables])
        
        lines = []
        lines.append("=" * 80)
        lines.append("DATABASE SCHEMA WITH SAMPLE DATA")
        lines.append("=" * 80)
        lines.append(f"\nTotal Tables: {schema['summary']['total_tables']}")
        lines.append("")
        
        for table_name, table_info in tables.items():
            lines.append(f"Table: {table_name}")
            lines.append(f"  Rows: {table_info['row_count']:,}")
            
            # Primary Keys
            if table_info["primary_keys"]:
                pk_str = ", ".join(table_info["primary_keys"])
                lines.append(f"  Primary Keys: {pk_str}")
            
            # Foreign Keys
            if table_info["foreign_keys"]:
                lines.append("  Foreign Keys:")
                for fk in table_info["foreign_keys"]:
                    lines.append(
                        f"    - {fk['column']} → {fk['references_table']}.{fk['references_column']}"
                    )
            
            # Columns
            lines.append("  Columns:")
            for col in table_info["columns"]:
                nullable = "NULL" if col["nullable"] else "NOT NULL"
                pk_mark = " [PK]" if col["name"] in table_info["primary_keys"] else ""
                lines.append(
                    f"    - {col['name']}: {col['type']} {nullable}{pk_mark}"
                )
            
            # 샘플 데이터 추가
            lines.append("")
            lines.append(self.format_sample_data_for_prompt(table_name, sample_limit))
            lines.append("")
        
        return "\n".join(lines)

