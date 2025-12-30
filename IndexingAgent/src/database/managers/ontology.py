# src/database/managers/ontology.py
"""
Ontology Schema Manager

온톨로지 관련 테이블 스키마 관리만 담당
CRUD 작업은 repositories/ontology_repository.py 또는 entity_repository.py 사용
"""

from typing import List, Dict, Any
from .base import BaseSchemaManager, init_schema, ensure_schema
from ..schemas.ontology_core import (
    CREATE_ONTOLOGY_COLUMN_METADATA_SQL,
    CREATE_TABLE_ENTITIES_SQL,
    CREATE_TABLE_RELATIONSHIPS_SQL,
)
from ..schemas.ontology_enhancement import (
    CREATE_ONTOLOGY_SUBCATEGORIES_SQL,
    CREATE_SEMANTIC_EDGES_SQL,
    CREATE_MEDICAL_TERM_MAPPINGS_SQL,
    CREATE_CROSS_TABLE_SEMANTICS_SQL,
)


class OntologySchemaManager(BaseSchemaManager):
    """
    온톨로지 스키마 관리자 (DDL만 담당)
    
    CRUD 작업은:
    - EntityRepository: table_entities, table_relationships
    - OntologyRepository: ontology_enhancement 테이블들
    """
    
    @property
    def table_names(self) -> List[str]:
        """관리하는 테이블 이름 목록 (생성 순서)"""
        return [
            'ontology_column_metadata',
            'table_entities',
            'table_relationships',
            'ontology_subcategories',
            'semantic_edges',
            'medical_term_mappings',
            'cross_table_semantics',
        ]
    
    @property
    def create_ddl_statements(self) -> List[str]:
        """테이블 생성 DDL SQL 리스트"""
        return [
            CREATE_ONTOLOGY_COLUMN_METADATA_SQL,
            CREATE_TABLE_ENTITIES_SQL,
            CREATE_TABLE_RELATIONSHIPS_SQL,
            CREATE_ONTOLOGY_SUBCATEGORIES_SQL,
            CREATE_SEMANTIC_EDGES_SQL,
            CREATE_MEDICAL_TERM_MAPPINGS_SQL,
            CREATE_CROSS_TABLE_SEMANTICS_SQL,
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """온톨로지 테이블 통계 조회"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        try:
            for table_name in self.table_names:
                if self.table_exists(table_name):
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    stats[table_name] = cursor.fetchone()[0]
                else:
                    stats[table_name] = 0
        except Exception as e:
            print(f"[OntologySchema] Error getting stats: {e}")
            stats['error'] = str(e)
        
        return stats


def init_ontology_schema(reset: bool = False) -> OntologySchemaManager:
    """온톨로지 스키마 초기화"""
    return init_schema(OntologySchemaManager, reset=reset)


def ensure_ontology_schema():
    """온톨로지 스키마 존재 확인"""
    ensure_schema(OntologySchemaManager)
