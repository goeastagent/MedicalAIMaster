# src/database/schemas/ontology_phase10.py
"""
Ontology Enhancement DDL (Phase 10)

고급 온톨로지 테이블 정의:
- ontology_subcategories: 카테고리 세분화
- semantic_edges: 파라미터 간 시맨틱 관계
- medical_term_mappings: 의료 표준 용어 매핑 (SNOMED, LOINC, ICD-10)
- cross_table_semantics: 테이블 간 시맨틱 유사성
"""

CREATE_ONTOLOGY_SUBCATEGORIES_SQL = """
CREATE TABLE IF NOT EXISTS ontology_subcategories (
    subcategory_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    parent_category VARCHAR(255) NOT NULL,
    subcategory_name VARCHAR(255) NOT NULL,
    
    -- 메타데이터
    confidence REAL DEFAULT 0.0,
    reasoning TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(parent_category, subcategory_name)
);

CREATE INDEX IF NOT EXISTS idx_subcat_parent ON ontology_subcategories(parent_category);
"""

CREATE_SEMANTIC_EDGES_SQL = """
CREATE TABLE IF NOT EXISTS semantic_edges (
    edge_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    source_parameter VARCHAR(255) NOT NULL,
    target_parameter VARCHAR(255) NOT NULL,
    
    relationship_type VARCHAR(50) NOT NULL,  -- "RELATED_TO", "DERIVED_FROM", "OPPOSITE_OF"
    
    confidence REAL DEFAULT 0.0,
    reasoning TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(source_parameter, target_parameter, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_semantic_source ON semantic_edges(source_parameter);
CREATE INDEX IF NOT EXISTS idx_semantic_target ON semantic_edges(target_parameter);
CREATE INDEX IF NOT EXISTS idx_semantic_type ON semantic_edges(relationship_type);
"""

CREATE_MEDICAL_TERM_MAPPINGS_SQL = """
CREATE TABLE IF NOT EXISTS medical_term_mappings (
    mapping_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    parameter_key VARCHAR(255) NOT NULL,
    
    -- SNOMED-CT
    snomed_code VARCHAR(50),
    snomed_name TEXT,
    
    -- LOINC
    loinc_code VARCHAR(50),
    loinc_name TEXT,
    
    -- ICD-10
    icd10_code VARCHAR(50),
    icd10_name TEXT,
    
    confidence REAL DEFAULT 0.0,
    reasoning TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(parameter_key)
);

CREATE INDEX IF NOT EXISTS idx_med_term_param ON medical_term_mappings(parameter_key);
CREATE INDEX IF NOT EXISTS idx_med_term_snomed ON medical_term_mappings(snomed_code);
CREATE INDEX IF NOT EXISTS idx_med_term_loinc ON medical_term_mappings(loinc_code);
"""

CREATE_CROSS_TABLE_SEMANTICS_SQL = """
CREATE TABLE IF NOT EXISTS cross_table_semantics (
    semantic_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    source_file_id UUID REFERENCES file_catalog(file_id) ON DELETE CASCADE,
    source_column VARCHAR(255) NOT NULL,
    
    target_file_id UUID REFERENCES file_catalog(file_id) ON DELETE CASCADE,
    target_column VARCHAR(255) NOT NULL,
    
    relationship_type VARCHAR(50) NOT NULL,  -- "SEMANTICALLY_SIMILAR", "SAME_CONCEPT"
    
    confidence REAL DEFAULT 0.0,
    reasoning TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(source_file_id, source_column, target_file_id, target_column)
);

CREATE INDEX IF NOT EXISTS idx_cross_sem_source ON cross_table_semantics(source_file_id);
CREATE INDEX IF NOT EXISTS idx_cross_sem_target ON cross_table_semantics(target_file_id);
"""

