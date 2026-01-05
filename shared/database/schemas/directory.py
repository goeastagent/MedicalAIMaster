# src/database/schemas/directory.py
"""
Directory Catalog DDL

[directory_catalog node]에서 디렉토리 레벨 메타데이터를 저장하는 테이블 정의:
- directory_catalog: 디렉토리 단위 메타데이터 (파일 통계, 파일명 패턴 등)
"""

CREATE_DIRECTORY_CATALOG_SQL = """
CREATE TABLE IF NOT EXISTS directory_catalog (
    -- Primary Key
    dir_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 경로 정보
    dir_path TEXT UNIQUE NOT NULL,           -- 절대 경로 (unique constraint)
    dir_name VARCHAR(255) NOT NULL,          -- 디렉토리명 (예: "vital_files")
    parent_dir_id UUID REFERENCES directory_catalog(dir_id) ON DELETE SET NULL,  -- 상위 디렉토리 FK
    
    -- 파일 통계 ([directory_catalog node] Rule-based 수집)
    file_count INTEGER DEFAULT 0,            -- 총 파일 수 (직계 자식만)
    file_extensions JSONB,                   -- {"vital": 6388, "csv": 3}
    total_size_bytes BIGINT DEFAULT 0,       -- 총 크기
    total_size_mb FLOAT DEFAULT 0.0,
    
    -- 하위 디렉토리 통계
    subdir_count INTEGER DEFAULT 0,          -- 직계 하위 디렉토리 수
    
    -- 파일명 샘플 ([directory_catalog node] LLM 분석용 수집)
    filename_samples JSONB,                  -- ["0001.vital", "0002.vital", ..., "6388.vital"]
    filename_sample_count INTEGER DEFAULT 0, -- 샘플 수
    
    -- 패턴 분석 결과 ([directory_pattern node] LLM이 채움)
    filename_pattern TEXT,                   -- "{caseid:integer}.vital"
    filename_columns JSONB,                  -- [{"name": "caseid", "type": "integer", "links_to": {...}}]
    pattern_confidence FLOAT,                -- LLM confidence
    pattern_reasoning TEXT,                  -- LLM reasoning
    pattern_analyzed_at TIMESTAMP,           -- LLM 분석 시점
    
    -- 디렉토리 분류 ([file_classification node]에서 채워질 수 있음)
    dir_type VARCHAR(50),                    -- "signal_files", "tabular_files", "metadata", "mixed"
    
    -- 메타
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_directory_catalog_parent ON directory_catalog(parent_dir_id);
CREATE INDEX IF NOT EXISTS idx_directory_catalog_dir_type ON directory_catalog(dir_type);
CREATE INDEX IF NOT EXISTS idx_directory_catalog_path ON directory_catalog(dir_path);
"""

# file_catalog에 FK 제약 추가 (directory_catalog가 먼저 생성된 후)
ADD_FILE_CATALOG_DIR_FK_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'fk_file_catalog_dir'
    ) THEN
        ALTER TABLE file_catalog 
        ADD CONSTRAINT fk_file_catalog_dir 
        FOREIGN KEY (dir_id) REFERENCES directory_catalog(dir_id) ON DELETE SET NULL;
    END IF;
END $$;
"""

# Updated_at 자동 갱신 트리거
CREATE_DIRECTORY_UPDATE_TRIGGER_SQL = """
-- directory_catalog 트리거
DROP TRIGGER IF EXISTS update_directory_catalog_updated_at ON directory_catalog;
CREATE TRIGGER update_directory_catalog_updated_at
    BEFORE UPDATE ON directory_catalog
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
"""

