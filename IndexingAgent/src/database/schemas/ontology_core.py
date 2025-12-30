# src/database/schemas/ontology_core.py
"""
Ontology Core DDL (Phase 8/9)

테이블 Entity와 Relationship 정의:
- ontology_column_metadata: LLM 분석 컬럼 메타데이터 (JSONB 기반)
- table_entities: 테이블별 Entity Understanding
- table_relationships: 테이블 간 관계 (FK 등)
"""

CREATE_ONTOLOGY_COLUMN_METADATA_SQL = """
CREATE TABLE IF NOT EXISTS ontology_column_metadata (
    dataset_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dataset_id, table_name, column_name)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_ontology_col_meta_dataset 
    ON ontology_column_metadata(dataset_id);
CREATE INDEX IF NOT EXISTS idx_ontology_col_meta_table 
    ON ontology_column_metadata(dataset_id, table_name);
"""

CREATE_TABLE_ENTITIES_SQL = """
CREATE TABLE IF NOT EXISTS table_entities (
    -- file_id를 PK로 사용 (file_catalog와 1:1 연결)
    file_id UUID PRIMARY KEY REFERENCES file_catalog(file_id) ON DELETE CASCADE,
    
    -- 핵심 정보: 각 행이 무엇을 나타내는가
    row_represents TEXT NOT NULL,          -- "surgery", "patient", "lab_result"
    entity_identifier TEXT,                -- "caseid" or NULL (복합키인 경우)
    
    -- LLM 분석 메타데이터
    confidence REAL DEFAULT 0.0,           -- LLM 확신도
    reasoning TEXT,                        -- 판단 근거
    llm_analyzed_at TIMESTAMP,             -- LLM 분석 시간
    
    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스: row_represents로 동일 entity 테이블 검색
CREATE INDEX IF NOT EXISTS idx_table_entities_entity 
    ON table_entities(row_represents);
"""

CREATE_TABLE_RELATIONSHIPS_SQL = """
CREATE TABLE IF NOT EXISTS table_relationships (
    rel_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 관계의 양쪽 테이블
    source_file_id UUID REFERENCES file_catalog(file_id) ON DELETE CASCADE,
    target_file_id UUID REFERENCES file_catalog(file_id) ON DELETE CASCADE,
    
    -- 연결 컬럼
    source_column VARCHAR(255),
    target_column VARCHAR(255),
    
    -- 관계 정보
    relationship_type VARCHAR(50),        -- "foreign_key", "shared_identifier"
    cardinality VARCHAR(10),              -- "1:1", "1:N", "N:1"
    
    -- LLM 분석 결과
    confidence REAL DEFAULT 0.0,
    reasoning TEXT,
    
    -- 메타
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(source_file_id, target_file_id, source_column, target_column)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_table_rel_source ON table_relationships(source_file_id);
CREATE INDEX IF NOT EXISTS idx_table_rel_target ON table_relationships(target_file_id);
"""

