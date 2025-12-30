# src/database/managers/dictionary.py
"""
Data Dictionary Schema Manager

data_dictionary 테이블 관리 + CRUD 함수
"""

from typing import List, Dict, Any, Optional
from .base import BaseSchemaManager, init_schema, ensure_schema
from ..schemas.dictionary import CREATE_DATA_DICTIONARY_SQL
from ..connection import get_db_manager


class DictionarySchemaManager(BaseSchemaManager):
    """Data Dictionary 스키마 관리"""
    
    @property
    def table_names(self) -> List[str]:
        """관리하는 테이블 이름 목록"""
        return ['data_dictionary']
    
    @property
    def create_ddl_statements(self) -> List[str]:
        """테이블 생성 DDL SQL 리스트"""
        return [CREATE_DATA_DICTIONARY_SQL]
    
    def get_stats(self) -> Dict[str, Any]:
        """data_dictionary 통계 조회"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        try:
            # 전체 엔트리 수
            cursor.execute("SELECT COUNT(*) FROM data_dictionary")
            stats['total_entries'] = cursor.fetchone()[0]
            
            # 소스 파일별 엔트리 수
            cursor.execute("""
                SELECT source_file_name, COUNT(*) 
                FROM data_dictionary 
                GROUP BY source_file_name
            """)
            stats['entries_by_file'] = dict(cursor.fetchall())
            
            # unit이 있는 엔트리 수
            cursor.execute("""
                SELECT COUNT(*) FROM data_dictionary 
                WHERE parameter_unit IS NOT NULL AND parameter_unit != ''
            """)
            stats['entries_with_unit'] = cursor.fetchone()[0]
            
        except Exception as e:
            print(f"[DictionarySchema] Error getting stats: {e}")
            stats['error'] = str(e)
        
        return stats


# =============================================================================
# CRUD 함수
# =============================================================================

def insert_dictionary_entries_batch(
    entries: List[Dict[str, Any]],
    db_manager=None
) -> int:
    """
    data_dictionary에 여러 엔트리 배치 삽입
    
    Args:
        entries: List of dicts with keys:
            - source_file_id
            - source_file_name
            - parameter_key
            - parameter_desc (optional)
            - parameter_unit (optional)
            - extra_info (optional)
            - llm_confidence (optional)
    
    Returns:
        삽입된 엔트리 수
    """
    import json
    
    if not entries:
        return 0
    
    db = db_manager or get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    inserted = 0
    
    try:
        for entry in entries:
            cursor.execute("""
                INSERT INTO data_dictionary (
                    source_file_id, source_file_name,
                    parameter_key, parameter_desc, parameter_unit,
                    extra_info, llm_confidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_file_id, parameter_key) DO UPDATE SET
                    parameter_desc = EXCLUDED.parameter_desc,
                    parameter_unit = EXCLUDED.parameter_unit,
                    extra_info = EXCLUDED.extra_info,
                    llm_confidence = EXCLUDED.llm_confidence
            """, (
                entry.get('source_file_id'),
                entry.get('source_file_name'),
                entry.get('parameter_key'),
                entry.get('parameter_desc'),
                entry.get('parameter_unit'),
                json.dumps(entry.get('extra_info') or {}),
                entry.get('llm_confidence')
            ))
            inserted += 1
        
        conn.commit()
        return inserted
        
    except Exception as e:
        conn.rollback()
        print(f"[DataDictionary] Error batch inserting: {e}")
        raise


# =============================================================================
# 편의 함수
# =============================================================================

def init_dictionary_schema(reset: bool = False) -> DictionarySchemaManager:
    """
    data_dictionary 스키마 초기화
    
    Args:
        reset: True면 기존 테이블 삭제 후 재생성
    
    Returns:
        DictionarySchemaManager 인스턴스
    """
    return init_schema(DictionarySchemaManager, reset=reset)


def ensure_dictionary_schema():
    """data_dictionary 테이블이 없으면 생성"""
    ensure_schema(DictionarySchemaManager)

