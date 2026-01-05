# src/database/schemas/parameter.py
"""
Parameter DDL

논리적 파라미터 테이블 정의:
- parameter: Wide-format 컬럼명 또는 Long-format 컬럼값에서 추출한 측정 파라미터

Wide-format: 컬럼명이 parameter (source_type='column_name')
  예: HR, SpO2, age 컬럼 → parameter rows

Long-format: 특정 컬럼의 값들이 parameter (source_type='column_value')
  예: param 컬럼의 값 [HR, SpO2, BP] → parameter rows
"""

CREATE_PARAMETER_SQL = """
CREATE TABLE IF NOT EXISTS parameter (
    -- PK
    param_id SERIAL PRIMARY KEY,
    
    -- =========================================================================
    -- Source 정보 ([420] column_classification에서 채움)
    -- file_id 또는 group_id 중 하나는 반드시 있어야 함
    -- =========================================================================
    file_id UUID REFERENCES file_catalog(file_id) ON DELETE CASCADE,
    group_id UUID,                              -- file_group FK (테이블 생성 순서상 나중에 FK 추가)
    param_key VARCHAR(255) NOT NULL,           -- 원본 파라미터명 ("HR", "SpO2", "age")
    source_type VARCHAR(20) NOT NULL,          -- 'column_name' | 'column_value' | 'group_common'
    source_column_id INTEGER REFERENCES column_metadata(col_id) ON DELETE SET NULL,
                                               -- Wide: 해당 컬럼 / Long: key 컬럼
    
    -- =========================================================================
    -- Semantic 정보 ([600] parameter_semantic에서 LLM이 채움)
    -- =========================================================================
    semantic_name VARCHAR(255),                 -- "Heart Rate"
    unit VARCHAR(100),                          -- "bpm" (LLM이 확정/보정)
    concept_category VARCHAR(255),              -- "Vitals"
    description TEXT,                           -- 상세 설명
    
    -- =========================================================================
    -- Dictionary 매칭 ([600] parameter_semantic에서 채움)
    -- =========================================================================
    dict_entry_id UUID REFERENCES data_dictionary(dict_id) ON DELETE SET NULL,
    dict_match_status VARCHAR(20),              -- 'matched', 'not_found', 'null_from_llm'
    match_confidence FLOAT,                     -- dictionary 매칭 확신도
    
    -- =========================================================================
    -- 속성
    -- =========================================================================
    is_identifier BOOLEAN DEFAULT FALSE,        -- 식별자 여부 (caseid 등)
    
    -- =========================================================================
    -- LLM 메타
    -- =========================================================================
    llm_confidence FLOAT,                       -- LLM 분석 확신도
    llm_reasoning TEXT,                         -- LLM 판단 근거
    
    -- =========================================================================
    -- 메타
    -- =========================================================================
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- file_id 또는 group_id 중 하나는 반드시 있어야 함
    CONSTRAINT chk_parameter_source CHECK (file_id IS NOT NULL OR group_id IS NOT NULL)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_param_file ON parameter (file_id);
CREATE INDEX IF NOT EXISTS idx_param_group ON parameter (group_id);
CREATE INDEX IF NOT EXISTS idx_param_key ON parameter (param_key);
CREATE INDEX IF NOT EXISTS idx_param_source_type ON parameter (source_type);
CREATE INDEX IF NOT EXISTS idx_param_source_col ON parameter (source_column_id);
CREATE INDEX IF NOT EXISTS idx_param_category ON parameter (concept_category);
CREATE INDEX IF NOT EXISTS idx_param_dict ON parameter (dict_entry_id);
CREATE INDEX IF NOT EXISTS idx_param_match_status ON parameter (dict_match_status);
CREATE INDEX IF NOT EXISTS idx_param_semantic_null ON parameter (semantic_name) WHERE semantic_name IS NULL;

-- UNIQUE 제약조건 (ON CONFLICT용)
-- file_id 기반 파라미터 중복 방지
CREATE UNIQUE INDEX IF NOT EXISTS idx_param_file_key_unique 
    ON parameter (file_id, param_key, source_type) 
    WHERE file_id IS NOT NULL;
-- group_id 기반 파라미터 중복 방지
CREATE UNIQUE INDEX IF NOT EXISTS idx_param_group_key_unique 
    ON parameter (group_id, param_key, source_type) 
    WHERE group_id IS NOT NULL;
"""

# Updated_at 자동 갱신 트리거
CREATE_PARAMETER_UPDATE_TRIGGER_SQL = """
-- parameter 테이블 updated_at 트리거
DROP TRIGGER IF EXISTS update_parameter_updated_at ON parameter;
CREATE TRIGGER update_parameter_updated_at
    BEFORE UPDATE ON parameter
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
"""

