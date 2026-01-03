# src/database/managers/parameter.py
"""
Parameter Schema Manager

parameter 테이블 관리:
- Wide-format: 컬럼명에서 추출한 파라미터
- Long-format: 컬럼값에서 추출한 파라미터
"""

from typing import List, Dict, Any
from .base import BaseSchemaManager, init_schema, ensure_schema
from ..schemas.parameter import (
    CREATE_PARAMETER_SQL,
    CREATE_PARAMETER_UPDATE_TRIGGER_SQL,
)
from ..connection import get_db_manager


class ParameterSchemaManager(BaseSchemaManager):
    """Parameter 스키마 관리"""
    
    @property
    def table_names(self) -> List[str]:
        """관리하는 테이블 이름 목록"""
        return ['parameter']
    
    @property
    def create_ddl_statements(self) -> List[str]:
        """테이블 생성 DDL SQL 리스트"""
        return [
            CREATE_PARAMETER_SQL,
            CREATE_PARAMETER_UPDATE_TRIGGER_SQL,
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """parameter 테이블 통계 조회"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        try:
            # 전체 파라미터 수
            cursor.execute("SELECT COUNT(*) FROM parameter")
            stats['total_parameters'] = cursor.fetchone()[0]
            
            # source_type별 수
            cursor.execute("""
                SELECT source_type, COUNT(*) 
                FROM parameter 
                GROUP BY source_type
            """)
            stats['by_source_type'] = dict(cursor.fetchall())
            
            # semantic 분석 완료 수
            cursor.execute("""
                SELECT COUNT(*) FROM parameter 
                WHERE semantic_name IS NOT NULL
            """)
            stats['with_semantic'] = cursor.fetchone()[0]
            
            # semantic 분석 대기 수
            cursor.execute("""
                SELECT COUNT(*) FROM parameter 
                WHERE semantic_name IS NULL
            """)
            stats['pending_semantic'] = cursor.fetchone()[0]
            
            # concept_category별 수
            cursor.execute("""
                SELECT concept_category, COUNT(*) 
                FROM parameter 
                WHERE concept_category IS NOT NULL
                GROUP BY concept_category
            """)
            stats['by_category'] = dict(cursor.fetchall())
            
            # dictionary 매칭 상태별 수
            cursor.execute("""
                SELECT dict_match_status, COUNT(*) 
                FROM parameter 
                WHERE dict_match_status IS NOT NULL
                GROUP BY dict_match_status
            """)
            stats['by_match_status'] = dict(cursor.fetchall())
            
        except Exception as e:
            print(f"[ParameterSchema] Error getting stats: {e}")
            stats['error'] = str(e)
        
        return stats


# =============================================================================
# 편의 함수
# =============================================================================

def init_parameter_schema(reset: bool = False) -> ParameterSchemaManager:
    """
    parameter 스키마 초기화
    
    Args:
        reset: True면 기존 테이블 삭제 후 재생성
    
    Returns:
        ParameterSchemaManager 인스턴스
    """
    return init_schema(ParameterSchemaManager, reset=reset)


def ensure_parameter_schema():
    """parameter 테이블이 없으면 생성"""
    ensure_schema(ParameterSchemaManager)

