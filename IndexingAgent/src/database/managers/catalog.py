# src/database/managers/catalog.py
"""
Data Catalog Schema Manager

file_catalog, column_metadata 테이블 관리
"""

from typing import List, Dict, Any
from .base import BaseSchemaManager, init_schema, ensure_schema
from ..schemas.catalog import (
    CREATE_UUID_EXTENSION_SQL,
    CREATE_FILE_CATALOG_SQL,
    CREATE_COLUMN_METADATA_SQL,
    CREATE_UPDATE_TRIGGER_SQL,
)


class CatalogSchemaManager(BaseSchemaManager):
    """Data Catalog 스키마 관리"""
    
    @property
    def table_names(self) -> List[str]:
        """관리하는 테이블 이름 목록 (생성 순서)"""
        return ['file_catalog', 'column_metadata']
    
    @property
    def create_ddl_statements(self) -> List[str]:
        """테이블 생성 DDL SQL 리스트"""
        return [CREATE_FILE_CATALOG_SQL, CREATE_COLUMN_METADATA_SQL]
    
    def _pre_create_hook(self, cursor) -> None:
        """UUID 확장 활성화"""
        cursor.execute(CREATE_UUID_EXTENSION_SQL)
    
    def _post_create_hook(self, cursor) -> None:
        """트리거 생성"""
        cursor.execute(CREATE_UPDATE_TRIGGER_SQL)
    
    def get_stats(self) -> Dict[str, Any]:
        """카탈로그 통계 조회"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        try:
            # 파일 수
            cursor.execute("SELECT COUNT(*) FROM file_catalog")
            stats['total_files'] = cursor.fetchone()[0]
            
            # processor_type별 파일 수
            cursor.execute("""
                SELECT processor_type, COUNT(*) 
                FROM file_catalog 
                GROUP BY processor_type
            """)
            stats['files_by_type'] = dict(cursor.fetchall())
            
            # 컬럼 수
            cursor.execute("SELECT COUNT(*) FROM column_metadata")
            stats['total_columns'] = cursor.fetchone()[0]
            
            # column_type별 수
            cursor.execute("""
                SELECT column_type, COUNT(*) 
                FROM column_metadata 
                GROUP BY column_type
            """)
            stats['columns_by_type'] = dict(cursor.fetchall())
            
        except Exception as e:
            print(f"[CatalogSchema] Error getting stats: {e}")
            stats['error'] = str(e)
        
        return stats


def init_catalog_schema(reset: bool = False) -> CatalogSchemaManager:
    """
    카탈로그 스키마 초기화
    
    Args:
        reset: True면 기존 테이블 삭제 후 재생성
    
    Returns:
        CatalogSchemaManager 인스턴스
    """
    return init_schema(CatalogSchemaManager, reset=reset)


def ensure_catalog_schema():
    """file_catalog, column_metadata 테이블이 없으면 생성"""
    ensure_schema(CatalogSchemaManager)

