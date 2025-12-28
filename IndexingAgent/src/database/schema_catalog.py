# src/database/schema_catalog.py
"""
Data Catalog 스키마

파일과 컬럼 메타데이터를 저장하는 테이블 정의
- file_catalog: 파일 단위 거시적 정보 (Phase 0 + Phase 1)
- column_metadata: 컬럼 단위 미시적 정보 (Phase 0 + Phase 1)
"""

from typing import Optional
from .connection import get_db_manager


# =============================================================================
# DDL: 테이블 생성 SQL
# =============================================================================

# UUID 확장 활성화
CREATE_UUID_EXTENSION_SQL = """
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
"""

CREATE_FILE_CATALOG_SQL = """
CREATE TABLE IF NOT EXISTS file_catalog (
    -- Phase 0: 물리적 정보
    file_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_path TEXT UNIQUE NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_extension VARCHAR(20),
    file_size_bytes BIGINT,
    file_size_mb NUMERIC(10, 2),
    file_modified_at TIMESTAMP,
    processor_type VARCHAR(50),           -- "tabular" or "signal"
    is_text_readable BOOLEAN DEFAULT FALSE,
    file_metadata JSONB DEFAULT '{}'::jsonb,
    raw_stats JSONB,
    
    -- Phase 1: LLM 분석 결과 (의미론적 정보)
    semantic_type VARCHAR(100),           -- "Signal:Physiological", "Clinical:Demographics", "Lab:Chemistry"
    semantic_name VARCHAR(255),           -- 파일의 표준화된 이름
    file_purpose TEXT,                    -- 파일의 목적/용도 설명
    primary_entity VARCHAR(100),          -- 각 행이 나타내는 entity (예: "surgery", "patient")
    entity_identifier_column VARCHAR(100), -- entity 식별자 컬럼명
    domain VARCHAR(100),                  -- 의료 도메인 (예: "Anesthesia", "Laboratory")
    is_metadata BOOLEAN DEFAULT FALSE,    -- 메타데이터/카탈로그 파일 여부 (데이터 사전, README 등)
    llm_confidence FLOAT,                 -- LLM 분석 확신도
    llm_analyzed_at TIMESTAMP,            -- LLM 분석 완료 시간
    
    -- 메타
    created_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_file_catalog_path ON file_catalog (file_path);
CREATE INDEX IF NOT EXISTS idx_file_catalog_modified ON file_catalog (file_path, file_modified_at);
CREATE INDEX IF NOT EXISTS idx_file_catalog_meta ON file_catalog USING gin (file_metadata);
CREATE INDEX IF NOT EXISTS idx_file_catalog_type ON file_catalog (processor_type);
CREATE INDEX IF NOT EXISTS idx_file_catalog_semantic ON file_catalog (semantic_type);
CREATE INDEX IF NOT EXISTS idx_file_catalog_domain ON file_catalog (domain);
"""

CREATE_COLUMN_METADATA_SQL = """
CREATE TABLE IF NOT EXISTS column_metadata (
    -- Phase 0: 물리적 정보
    col_id SERIAL PRIMARY KEY,
    file_id UUID REFERENCES file_catalog(file_id) ON DELETE CASCADE,
    original_name VARCHAR(255),
    column_type VARCHAR(50),              -- "categorical", "continuous", "datetime", "waveform", etc.
    data_type VARCHAR(100),               -- dtype
    column_info JSONB DEFAULT '{}'::jsonb,
    value_distribution JSONB DEFAULT '{}'::jsonb,
    
    -- Phase 1B: LLM 분석 결과 (의미론적 정보)
    semantic_name VARCHAR(255),           -- 표준화된 이름 (예: "Heart Rate")
    unit VARCHAR(50),                     -- 측정 단위 (예: "bpm", "mmHg")
    concept_category VARCHAR(100),        -- 개념 카테고리 (예: "Vital Signs", "Demographics")
    description TEXT,                     -- 상세 설명
    standard_code VARCHAR(100),           -- LOINC, SNOMED 코드 (있으면)
    is_pii BOOLEAN DEFAULT FALSE,         -- 개인식별정보 여부
    llm_confidence FLOAT,                 -- LLM 분석 확신도
    llm_analyzed_at TIMESTAMP,            -- LLM 분석 완료 시간
    
    -- Phase 1B: data_dictionary 연결
    dict_entry_id UUID,                   -- FK는 data_dictionary 생성 후 추가
    dict_match_status VARCHAR(20),        -- 'matched', 'not_found', 'null_from_llm'
    match_confidence FLOAT,               -- dictionary 매칭 확신도
    
    -- 메타
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(file_id, original_name)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_column_meta_file ON column_metadata (file_id);
CREATE INDEX IF NOT EXISTS idx_column_meta_name ON column_metadata (original_name);
CREATE INDEX IF NOT EXISTS idx_column_meta_info ON column_metadata USING gin (column_info);
CREATE INDEX IF NOT EXISTS idx_column_meta_type ON column_metadata (column_type);
CREATE INDEX IF NOT EXISTS idx_column_meta_semantic ON column_metadata (semantic_name);
CREATE INDEX IF NOT EXISTS idx_column_meta_concept ON column_metadata (concept_category);
CREATE INDEX IF NOT EXISTS idx_column_meta_dict ON column_metadata (dict_entry_id);
CREATE INDEX IF NOT EXISTS idx_column_meta_match ON column_metadata (dict_match_status);
"""

# Updated_at 자동 갱신 트리거 (column_metadata만)
CREATE_UPDATE_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- column_metadata 트리거
DROP TRIGGER IF EXISTS update_column_metadata_updated_at ON column_metadata;
CREATE TRIGGER update_column_metadata_updated_at
    BEFORE UPDATE ON column_metadata
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
"""


# =============================================================================
# Schema Manager Class
# =============================================================================

class CatalogSchemaManager:
    """Data Catalog 스키마 관리"""
    
    def __init__(self, db_manager=None):
        self.db = db_manager or get_db_manager()
    
    def create_tables(self) -> bool:
        """
        file_catalog, column_metadata 테이블 생성
        
        Returns:
            True if successful
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # 0. UUID 확장 활성화
            cursor.execute(CREATE_UUID_EXTENSION_SQL)
            
            # 1. file_catalog 테이블 생성
            cursor.execute(CREATE_FILE_CATALOG_SQL)
            
            # 2. column_metadata 테이블 생성
            cursor.execute(CREATE_COLUMN_METADATA_SQL)
            
            # 3. 트리거 생성
            cursor.execute(CREATE_UPDATE_TRIGGER_SQL)
            
            conn.commit()
            print("[CatalogSchema] Tables created successfully")
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"[CatalogSchema] Error creating tables: {e}")
            raise
    
    def drop_tables(self, confirm: bool = False) -> bool:
        """
        테이블 삭제 (주의: 모든 데이터 삭제됨)
        
        Args:
            confirm: True로 설정해야 삭제 실행
        """
        if not confirm:
            print("[CatalogSchema] Set confirm=True to drop tables")
            return False
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DROP TABLE IF EXISTS column_metadata CASCADE")
            cursor.execute("DROP TABLE IF EXISTS file_catalog CASCADE")
            conn.commit()
            print("[CatalogSchema] Tables dropped successfully")
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"[CatalogSchema] Error dropping tables: {e}")
            raise
    
    def reset_tables(self) -> bool:
        """테이블 초기화 (삭제 후 재생성)"""
        self.drop_tables(confirm=True)
        return self.create_tables()
    
    def table_exists(self, table_name: str) -> bool:
        """테이블 존재 여부 확인"""
        return self.db.table_exists(table_name)
    
    def get_stats(self) -> dict:
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


# =============================================================================
# 편의 함수
# =============================================================================

def init_catalog_schema(reset: bool = False) -> CatalogSchemaManager:
    """
    카탈로그 스키마 초기화
    
    Args:
        reset: True면 기존 테이블 삭제 후 재생성
    
    Returns:
        CatalogSchemaManager 인스턴스
    """
    manager = CatalogSchemaManager()
    
    if reset:
        manager.reset_tables()
    else:
        manager.create_tables()
    
    return manager

