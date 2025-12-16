# src/database/schema_generator.py
"""
온톨로지 기반 DDL 동적 생성

relationships, hierarchy 정보를 활용하여 FK, 인덱스 자동 생성
"""

from typing import List, Dict, Any, Optional


class SchemaGenerator:
    """DDL 동적 생성기"""
    
    @staticmethod
    def generate_ddl(
        table_name: str,
        schema: List[Dict[str, Any]],
        ontology_context: Dict[str, Any]
    ) -> str:
        """
        온톨로지 기반 CREATE TABLE DDL 생성 (PostgreSQL)
        
        Args:
            table_name: 테이블 이름
            schema: finalized_schema (컬럼 정의)
            ontology_context: 온톨로지 컨텍스트
        
        Returns:
            CREATE TABLE DDL 문자열 (PostgreSQL)
        """
        # pandas to_sql이 자동으로 테이블 생성하므로
        # 여기서는 사용하지 않음 (FK 추가용으로만 사용)
        
        # 컬럼 정의
        column_definitions = []
        
        for col in schema:
            col_name = col['original_name']
            data_type = col['data_type']
            
            # PostgreSQL 데이터 타입 매핑
            sql_type = SchemaGenerator._map_to_postgresql_type(data_type)
            
            column_definitions.append(f'"{col_name}" {sql_type}')
        
        # FK 제약조건 (ALTER TABLE로 추가할 예정)
        # CREATE TABLE 시에는 포함하지 않음
        
        ddl = f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n  '
        ddl += ',\n  '.join(column_definitions)
        ddl += '\n);'
        
        return ddl
    
    @staticmethod
    def generate_indices(
        table_name: str,
        schema: List[Dict[str, Any]],
        ontology_context: Dict[str, Any]
    ) -> List[str]:
        """
        온톨로지 hierarchy 기반 인덱스 생성 DDL
        
        Level 1-2 Anchor 컬럼에 인덱스 생성 (JOIN 성능 최적화)
        
        Returns:
            CREATE INDEX 문자열 리스트
        """
        indices = []
        
        # 이 테이블의 컬럼들
        table_columns = {col['original_name'] for col in schema}
        
        # Hierarchy에서 Level 1-2 Anchor 찾기
        for h in ontology_context.get("hierarchy", []):
            if h.get("level", 99) <= 2:
                anchor_col = h.get("anchor_column")
                
                # 이 테이블에 해당 컬럼이 있으면 인덱스 생성
                if anchor_col in table_columns:
                    idx_name = f"idx_{table_name}_{anchor_col}"
                    idx_ddl = f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{table_name}"("{anchor_col}");'
                    indices.append(idx_ddl)
        
        return indices
    
    @staticmethod
    def _map_to_postgresql_type(data_type: str) -> str:
        """
        데이터 타입 매핑 (PostgreSQL)
        
        Args:
            data_type: finalized_schema의 data_type (VARCHAR, INT, FLOAT 등)
        
        Returns:
            PostgreSQL 데이터 타입
        """
        type_map = {
            "VARCHAR": "VARCHAR(255)",
            "INT": "INTEGER",
            "INTEGER": "INTEGER",
            "FLOAT": "DOUBLE PRECISION",
            "REAL": "REAL",
            "TIMESTAMP": "TIMESTAMP",
            "DATE": "DATE",
            "DATETIME": "TIMESTAMP",
            "BOOLEAN": "BOOLEAN",
            "TEXT": "TEXT"
        }
        
        return type_map.get(data_type.upper(), "TEXT")
    
    
    @staticmethod
    def _generate_fk_constraints(
        table_name: str,
        relationships: List[Dict]
    ) -> List[str]:
        """
        FK 제약조건 생성
        
        Args:
            table_name: 현재 테이블명
            relationships: 온톨로지 관계 리스트
        
        Returns:
            FOREIGN KEY 절 리스트
        """
        fk_clauses = []
        
        for rel in relationships:
            source = rel.get("source_table", "")
            target = rel.get("target_table", "")
            source_col = rel.get("source_column")
            target_col = rel.get("target_column")
            
            # 현재 테이블이 source인 경우
            if source in table_name or table_name in source:
                fk_clause = (
                    f'FOREIGN KEY ("{source_col}") '
                    f'REFERENCES "{target}"("{target_col}")'
                )
                fk_clauses.append(fk_clause)
        
        return fk_clauses

