# src/database/schema_dictionary.py
"""
Data Dictionary 스키마

metadata 파일에서 추출한 key-desc-unit 정보를 저장하는 테이블 정의
- data_dictionary: 파라미터 정의 사전 (clinical_parameters.csv 등에서 추출)
"""

from typing import Optional, List, Dict, Any
from .connection import get_db_manager


# =============================================================================
# DDL: 테이블 생성 SQL
# =============================================================================

CREATE_DATA_DICTIONARY_SQL = """
CREATE TABLE IF NOT EXISTS data_dictionary (
    -- PK
    dict_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 출처 정보
    source_file_id UUID REFERENCES file_catalog(file_id) ON DELETE CASCADE,
    source_file_name VARCHAR(255),
    
    -- 핵심 정보 (key-desc-unit)
    parameter_key VARCHAR(255) NOT NULL,
    parameter_desc TEXT,
    parameter_unit VARCHAR(100),
    
    -- 추가 메타정보 (JSONB) - 파일마다 다른 추가 컬럼들
    -- 예: {"category": "CBC", "reference_value": "4~10", "data_source": "EMR"}
    extra_info JSONB DEFAULT '{}'::jsonb,
    
    -- LLM 분석 정보
    llm_confidence FLOAT,
    
    -- 메타
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- 같은 파일에서 같은 key는 중복 불가
    UNIQUE(source_file_id, parameter_key)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_dict_key ON data_dictionary (parameter_key);
CREATE INDEX IF NOT EXISTS idx_dict_source ON data_dictionary (source_file_id);
CREATE INDEX IF NOT EXISTS idx_dict_extra ON data_dictionary USING gin (extra_info);
"""


# =============================================================================
# Schema Manager Class
# =============================================================================

class DictionarySchemaManager:
    """Data Dictionary 스키마 관리"""
    
    def __init__(self, db_manager=None):
        self.db = db_manager or get_db_manager()
    
    def create_tables(self) -> bool:
        """
        data_dictionary 테이블 생성
        
        Note: file_catalog 테이블이 먼저 존재해야 함 (FK 참조)
        
        Returns:
            True if successful
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(CREATE_DATA_DICTIONARY_SQL)
            conn.commit()
            print("[DictionarySchema] Table created successfully")
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"[DictionarySchema] Error creating table: {e}")
            raise
    
    def drop_tables(self, confirm: bool = False) -> bool:
        """
        테이블 삭제 (주의: 모든 데이터 삭제됨)
        
        Args:
            confirm: True로 설정해야 삭제 실행
        """
        if not confirm:
            print("[DictionarySchema] Set confirm=True to drop table")
            return False
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DROP TABLE IF EXISTS data_dictionary CASCADE")
            conn.commit()
            print("[DictionarySchema] Table dropped successfully")
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"[DictionarySchema] Error dropping table: {e}")
            raise
    
    def reset_tables(self) -> bool:
        """테이블 초기화 (삭제 후 재생성)"""
        self.drop_tables(confirm=True)
        return self.create_tables()
    
    def table_exists(self) -> bool:
        """테이블 존재 여부 확인"""
        return self.db.table_exists('data_dictionary')
    
    def get_stats(self) -> dict:
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

def insert_dictionary_entry(
    source_file_id: str,
    source_file_name: str,
    parameter_key: str,
    parameter_desc: Optional[str] = None,
    parameter_unit: Optional[str] = None,
    extra_info: Optional[Dict[str, Any]] = None,
    llm_confidence: Optional[float] = None,
    db_manager=None
) -> str:
    """
    data_dictionary에 단일 엔트리 삽입
    
    Returns:
        dict_id (UUID string)
    """
    import json
    
    db = db_manager or get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
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
            RETURNING dict_id
        """, (
            source_file_id,
            source_file_name,
            parameter_key,
            parameter_desc,
            parameter_unit,
            json.dumps(extra_info or {}),
            llm_confidence
        ))
        
        dict_id = cursor.fetchone()[0]
        conn.commit()
        return str(dict_id)
        
    except Exception as e:
        conn.rollback()
        print(f"[DataDictionary] Error inserting entry: {e}")
        raise


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


def get_dictionary_by_file(file_id: str, db_manager=None) -> List[Dict[str, Any]]:
    """특정 파일에서 추출된 모든 dictionary 엔트리 조회"""
    db = db_manager or get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT dict_id, parameter_key, parameter_desc, parameter_unit, 
               extra_info, llm_confidence
        FROM data_dictionary
        WHERE source_file_id = %s
        ORDER BY parameter_key
    """, (file_id,))
    
    columns = ['dict_id', 'parameter_key', 'parameter_desc', 'parameter_unit', 
               'extra_info', 'llm_confidence']
    
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_dictionary_by_key(parameter_key: str, db_manager=None) -> List[Dict[str, Any]]:
    """특정 key에 해당하는 모든 dictionary 엔트리 조회 (여러 파일에서 정의 가능)"""
    db = db_manager or get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT dict_id, source_file_name, parameter_key, parameter_desc, 
               parameter_unit, extra_info, llm_confidence
        FROM data_dictionary
        WHERE parameter_key = %s
        ORDER BY source_file_name
    """, (parameter_key,))
    
    columns = ['dict_id', 'source_file_name', 'parameter_key', 'parameter_desc', 
               'parameter_unit', 'extra_info', 'llm_confidence']
    
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_all_dictionary_keys(db_manager=None) -> List[str]:
    """모든 unique parameter_key 목록 조회"""
    db = db_manager or get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT parameter_key 
        FROM data_dictionary 
        ORDER BY parameter_key
    """)
    
    return [row[0] for row in cursor.fetchall()]


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
    manager = DictionarySchemaManager()
    
    if reset:
        manager.reset_tables()
    else:
        manager.create_tables()
    
    return manager


def ensure_dictionary_schema():
    """data_dictionary 테이블이 없으면 생성"""
    manager = DictionarySchemaManager()
    if not manager.table_exists():
        manager.create_tables()

