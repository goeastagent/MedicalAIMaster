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
    -- =========================================================================
    file_id UUID REFERENCES file_catalog(file_id) ON DELETE CASCADE,
    param_key VARCHAR(255) NOT NULL,           -- 원본 파라미터명 ("HR", "SpO2", "age")
    source_type VARCHAR(20) NOT NULL,          -- 'column_name' | 'column_value'
    source_column_id INTEGER REFERENCES column_metadata(col_id) ON DELETE SET NULL,
                                               -- Wide: 해당 컬럼 / Long: key 컬럼
    
    -- =========================================================================
    -- Long-format 추가 정보 (source_type='column_value'인 경우)
    -- =========================================================================
    occurrence_count INTEGER,                   -- 해당 파라미터 출현 횟수
    extracted_unit VARCHAR(50),                 -- unit 컬럼에서 추출한 값 (있으면)
    value_stats JSONB,                          -- {"min": 60, "max": 120, "mean": 75.2}
    
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
    
    -- 같은 파일에서 같은 param_key + source_type 조합은 중복 불가
    UNIQUE(file_id, param_key, source_type)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_param_file ON parameter (file_id);
CREATE INDEX IF NOT EXISTS idx_param_key ON parameter (param_key);
CREATE INDEX IF NOT EXISTS idx_param_source_type ON parameter (source_type);
CREATE INDEX IF NOT EXISTS idx_param_source_col ON parameter (source_column_id);
CREATE INDEX IF NOT EXISTS idx_param_category ON parameter (concept_category);
CREATE INDEX IF NOT EXISTS idx_param_dict ON parameter (dict_entry_id);
CREATE INDEX IF NOT EXISTS idx_param_match_status ON parameter (dict_match_status);
CREATE INDEX IF NOT EXISTS idx_param_semantic_null ON parameter (semantic_name) WHERE semantic_name IS NULL;
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

