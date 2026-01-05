# src/database/schemas/dictionary.py
"""
Data Dictionary DDL

metadata 파일에서 추출한 key-desc-unit 정보를 저장하는 테이블 정의:
- data_dictionary: 파라미터 정의 사전 (clinical_parameters.csv 등에서 추출)
"""

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

