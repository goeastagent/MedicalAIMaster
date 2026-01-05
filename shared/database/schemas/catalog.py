# src/database/schemas/catalog.py
"""
Data Catalog DDL

파일과 컬럼 메타데이터 테이블 정의:
- file_catalog: 파일 단위 거시적 정보 (file_catalog + file_classification)
- column_metadata: 컬럼 단위 물리적 정보 + 역할 분류 (file_catalog + column_classification)

Note: 컬럼의 semantic 정보(semantic_name, unit, concept_category 등)는 
      parameter 테이블에서 관리됩니다.
"""

# UUID 확장 활성화
CREATE_UUID_EXTENSION_SQL = """
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
"""

CREATE_FILE_CATALOG_SQL = """
CREATE TABLE IF NOT EXISTS file_catalog (
    -- [file_catalog node] 물리적 정보
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
    
    -- [directory_catalog node] 디렉토리 연결 (directory_catalog FK)
    dir_id UUID,                          -- directory_catalog FK (테이블 생성 순서상 나중에 FK 추가)
    
    -- [directory_pattern node] 파일명에서 추출한 값 (LLM 분석 결과)
    filename_values JSONB,                -- {"caseid": 1, "session": "A"} - 파일명에서 추출한 값
    
    -- [file_classification node] LLM 분석 결과
    is_metadata BOOLEAN DEFAULT FALSE,    -- 메타데이터/카탈로그 파일 여부 (데이터 사전, README 등)
    llm_confidence FLOAT,                 -- LLM 분석 확신도
    llm_analyzed_at TIMESTAMP,            -- LLM 분석 완료 시간
    
    -- [file_group] 파일 그룹 연결 (file-based sharding 지원)
    group_id UUID,                        -- file_group FK (테이블 생성 순서상 나중에 FK 추가)
    
    -- 메타
    created_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_file_catalog_path ON file_catalog (file_path);
CREATE INDEX IF NOT EXISTS idx_file_catalog_modified ON file_catalog (file_path, file_modified_at);
CREATE INDEX IF NOT EXISTS idx_file_catalog_meta ON file_catalog USING gin (file_metadata);
CREATE INDEX IF NOT EXISTS idx_file_catalog_type ON file_catalog (processor_type);
CREATE INDEX IF NOT EXISTS idx_file_catalog_dir ON file_catalog (dir_id);
CREATE INDEX IF NOT EXISTS idx_file_catalog_group ON file_catalog (group_id);
"""

CREATE_COLUMN_METADATA_SQL = """
CREATE TABLE IF NOT EXISTS column_metadata (
    -- =========================================================================
    -- [file_catalog node] 물리적 정보
    -- =========================================================================
    col_id SERIAL PRIMARY KEY,
    file_id UUID REFERENCES file_catalog(file_id) ON DELETE CASCADE,
    original_name VARCHAR(255),
    column_type VARCHAR(50),              -- "categorical", "continuous", "datetime", "waveform", etc.
    data_type VARCHAR(100),               -- dtype (int64, float64, object, etc.)
    column_info JSONB DEFAULT '{}'::jsonb,      -- {"min": 0, "max": 100, "mean": 50, ...}
    value_distribution JSONB DEFAULT '{}'::jsonb, -- {"unique_values": [...], "value_counts": {...}}
    
    -- =========================================================================
    -- [column_classification node] 컬럼 역할 분류 (LLM)
    -- =========================================================================
    column_role VARCHAR(50),              -- 컬럼의 역할 (정규화된 값):
                                          --   'parameter_name': 컬럼명이 파라미터 (Wide-format)
                                          --   'parameter_container': 값들이 파라미터 (Long-format key column)
                                          --   'identifier': 식별자 (caseid, patient_id 등)
                                          --   'value': 측정값 컬럼 (Long-format)
                                          --   'unit': 단위 컬럼 (Long-format)
                                          --   'timestamp': 시간 컬럼
                                          --   'attribute': 속성 (sex, department 등)
                                          --   'other': 기타
    column_role_reasoning TEXT,           -- LLM의 역할 판단 근거 설명
    
    -- =========================================================================
    -- 메타
    -- =========================================================================
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(file_id, original_name)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_column_meta_file ON column_metadata (file_id);
CREATE INDEX IF NOT EXISTS idx_column_meta_name ON column_metadata (original_name);
CREATE INDEX IF NOT EXISTS idx_column_meta_info ON column_metadata USING gin (column_info);
CREATE INDEX IF NOT EXISTS idx_column_meta_type ON column_metadata (column_type);
CREATE INDEX IF NOT EXISTS idx_column_meta_role ON column_metadata (column_role);
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

