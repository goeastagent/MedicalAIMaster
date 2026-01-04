# src/database/managers/file_group.py
"""
File Group Schema Manager

file_group 테이블 관리 및 관련 FK 추가 (file_catalog.group_id, parameter.group_id)
"""

from typing import List, Dict, Any
from .base import BaseSchemaManager, init_schema, ensure_schema
from ..schemas.file_group import (
    CREATE_FILE_GROUP_SQL,
    ADD_FILE_CATALOG_GROUP_FK_SQL,
    ADD_PARAMETER_GROUP_FK_SQL,
    CREATE_FILE_GROUP_UPDATE_TRIGGER_SQL,
)


class FileGroupSchemaManager(BaseSchemaManager):
    """File Group 스키마 관리"""
    
    @property
    def table_names(self) -> List[str]:
        """관리하는 테이블 이름 목록 (생성 순서)"""
        return ['file_group']
    
    @property
    def create_ddl_statements(self) -> List[str]:
        """테이블 생성 DDL SQL 리스트"""
        return [CREATE_FILE_GROUP_SQL]
    
    def _post_create_hook(self, cursor) -> None:
        """
        테이블 생성 후:
        - file_catalog에 group_id FK 추가 (테이블이 존재할 때만)
        - parameter에 group_id FK 추가 (테이블이 존재할 때만)
        - updated_at 트리거 생성
        """
        # file_catalog 테이블이 존재하면 group_id FK 추가
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'file_catalog'
            )
        """)
        if cursor.fetchone()[0]:
            cursor.execute(ADD_FILE_CATALOG_GROUP_FK_SQL)
        
        # parameter 테이블이 존재하면 group_id FK 추가
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'parameter'
            )
        """)
        if cursor.fetchone()[0]:
            cursor.execute(ADD_PARAMETER_GROUP_FK_SQL)
        
        # updated_at 트리거
        cursor.execute(CREATE_FILE_GROUP_UPDATE_TRIGGER_SQL)
    
    def get_stats(self) -> Dict[str, Any]:
        """파일 그룹 통계 조회"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        try:
            # 전체 그룹 수
            cursor.execute("SELECT COUNT(*) FROM file_group")
            stats['total_groups'] = cursor.fetchone()[0]
            
            # 전체 그룹화된 파일 수
            cursor.execute("""
                SELECT COALESCE(SUM(file_count), 0) FROM file_group
            """)
            stats['total_grouped_files'] = cursor.fetchone()[0]
            
            # 분석 완료 그룹 수
            cursor.execute("""
                SELECT COUNT(*) FROM file_group 
                WHERE llm_analyzed_at IS NOT NULL
            """)
            stats['analyzed_groups'] = cursor.fetchone()[0]
            
            # 확장자별 그룹 수
            cursor.execute("""
                SELECT 
                    grouping_criteria->'extensions' AS extensions,
                    COUNT(*) AS cnt
                FROM file_group 
                GROUP BY grouping_criteria->'extensions'
            """)
            stats['groups_by_extension'] = [
                {"extensions": row[0], "count": row[1]} 
                for row in cursor.fetchall()
            ]
            
            # 그룹별 파일 수 분포
            cursor.execute("""
                SELECT 
                    CASE 
                        WHEN file_count <= 10 THEN '1-10'
                        WHEN file_count <= 100 THEN '11-100'
                        WHEN file_count <= 1000 THEN '101-1000'
                        ELSE '1000+'
                    END as range,
                    COUNT(*) as cnt
                FROM file_group
                GROUP BY range
                ORDER BY range
            """)
            stats['file_count_distribution'] = dict(cursor.fetchall())
            
            # 그룹 파라미터 수 (group_id로 연결된 파라미터)
            cursor.execute("""
                SELECT COUNT(*) FROM parameter WHERE group_id IS NOT NULL
            """)
            stats['group_parameters'] = cursor.fetchone()[0]
            
        except Exception as e:
            print(f"[FileGroupSchema] Error getting stats: {e}")
            stats['error'] = str(e)
        
        return stats


def init_file_group_schema(reset: bool = False) -> FileGroupSchemaManager:
    """
    파일 그룹 스키마 초기화
    
    Args:
        reset: True면 기존 테이블 삭제 후 재생성
    
    Returns:
        FileGroupSchemaManager 인스턴스
        
    Note:
        이 함수는 file_catalog와 parameter 테이블이 이미 존재해야 합니다.
        FK를 추가하기 때문입니다.
    """
    return init_schema(FileGroupSchemaManager, reset=reset)


def ensure_file_group_schema():
    """file_group 테이블이 없으면 생성"""
    ensure_schema(FileGroupSchemaManager)

