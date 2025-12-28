# src/database/schema_ontology.py
"""
Ontology 스키마 정의

온톨로지 매니저에서 사용하는 테이블들을 정의합니다.
- ontology_column_metadata: LLM 분석 컬럼 메타데이터 (JSONB 기반)
- table_entities: 테이블별 Entity Understanding

Note: schema_catalog.py의 column_metadata와는 다른 테이블입니다.
      - schema_catalog.py: 파일 기반, Phase 0/1 워크플로우용
      - schema_ontology.py: 데이터셋 기반, 온톨로지 분석용
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from .connection import get_db_manager


# =============================================================================
# DDL: 테이블 생성 SQL
# =============================================================================

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

# =============================================================================
# Phase 2C: Ontology Enhancement 테이블
# =============================================================================

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


# =============================================================================
# Schema Manager Class
# =============================================================================

class OntologySchemaManager:
    """온톨로지 스키마 관리자"""
    
    def __init__(self):
        self.db = get_db_manager()
    
    def create_tables(self):
        """온톨로지 테이블 생성"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Phase 2A/2B 테이블
            cursor.execute(CREATE_ONTOLOGY_COLUMN_METADATA_SQL)
            cursor.execute(CREATE_TABLE_ENTITIES_SQL)
            cursor.execute(CREATE_TABLE_RELATIONSHIPS_SQL)
            # Phase 2C 테이블
            cursor.execute(CREATE_ONTOLOGY_SUBCATEGORIES_SQL)
            cursor.execute(CREATE_SEMANTIC_EDGES_SQL)
            cursor.execute(CREATE_MEDICAL_TERM_MAPPINGS_SQL)
            cursor.execute(CREATE_CROSS_TABLE_SEMANTICS_SQL)
            conn.commit()
            print("[OntologySchema] Tables created successfully")
        except Exception as e:
            conn.rollback()
            print(f"[OntologySchema] Error creating tables: {e}")
            raise
    
    def drop_tables(self, confirm: bool = False):
        """온톨로지 테이블 삭제"""
        if not confirm:
            print("[OntologySchema] Drop cancelled. Set confirm=True to proceed.")
            return
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Phase 2C 테이블 (역순 삭제)
            cursor.execute("DROP TABLE IF EXISTS cross_table_semantics CASCADE")
            cursor.execute("DROP TABLE IF EXISTS medical_term_mappings CASCADE")
            cursor.execute("DROP TABLE IF EXISTS semantic_edges CASCADE")
            cursor.execute("DROP TABLE IF EXISTS ontology_subcategories CASCADE")
            # Phase 2A/2B 테이블
            cursor.execute("DROP TABLE IF EXISTS table_relationships CASCADE")
            cursor.execute("DROP TABLE IF EXISTS ontology_column_metadata CASCADE")
            cursor.execute("DROP TABLE IF EXISTS table_entities CASCADE")
            conn.commit()
            print("[OntologySchema] Tables dropped successfully")
        except Exception as e:
            conn.rollback()
            print(f"[OntologySchema] Error dropping tables: {e}")
    
    def reset_tables(self):
        """테이블 삭제 후 재생성"""
        self.drop_tables(confirm=True)
        self.create_tables()
    
    # =========================================================================
    # ontology_column_metadata CRUD
    # =========================================================================
    
    def load_column_metadata(self, dataset_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        ontology_column_metadata 로드
        
        Returns:
            {table_name: {column_name: metadata_dict}}
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        column_metadata = {}
        
        try:
            if dataset_id:
                cursor.execute("""
                    SELECT table_name, column_name, metadata
                    FROM ontology_column_metadata
                    WHERE dataset_id = %s
                """, (dataset_id,))
            else:
                cursor.execute("""
                    SELECT table_name, column_name, metadata
                    FROM ontology_column_metadata
                """)
            
            for row in cursor.fetchall():
                table_name, col_name, metadata = row
                
                if table_name not in column_metadata:
                    column_metadata[table_name] = {}
                
                column_metadata[table_name][col_name] = metadata if isinstance(metadata, dict) else {}
                
        except Exception as e:
            print(f"[OntologySchema] Error loading column metadata: {e}")
        
        return column_metadata
    
    def save_column_metadata(self, column_metadata: Dict, dataset_id: str):
        """
        ontology_column_metadata 저장 (UPSERT)
        
        Args:
            column_metadata: {table_name: {column_name: metadata_dict}}
            dataset_id: 데이터셋 ID
        """
        if not column_metadata:
            return
        
        import json
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for table_name, columns in column_metadata.items():
                for col_name, metadata in columns.items():
                    cursor.execute("""
                        INSERT INTO ontology_column_metadata 
                            (dataset_id, table_name, column_name, metadata, updated_at)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (dataset_id, table_name, column_name)
                        DO UPDATE SET metadata = %s, updated_at = CURRENT_TIMESTAMP
                    """, (dataset_id, table_name, col_name, 
                          json.dumps(metadata), json.dumps(metadata)))
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            print(f"[OntologySchema] Error saving column metadata: {e}")
    
    # =========================================================================
    # table_entities CRUD
    # =========================================================================
    
    def load_table_entities(self, file_ids: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """
        table_entities 로드
        
        Args:
            file_ids: 조회할 file_id 목록 (None이면 전체)
        
        Returns:
            {file_id: entity_info_dict}
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        table_entities = {}
        
        try:
            if file_ids:
                placeholders = ', '.join(['%s'] * len(file_ids))
                cursor.execute(f"""
                    SELECT file_id, row_represents, entity_identifier,
                           confidence, reasoning, llm_analyzed_at
                    FROM table_entities
                    WHERE file_id IN ({placeholders})
                """, file_ids)
            else:
                cursor.execute("""
                    SELECT file_id, row_represents, entity_identifier,
                           confidence, reasoning, llm_analyzed_at
                    FROM table_entities
                """)
            
            for row in cursor.fetchall():
                (file_id, row_represents, entity_identifier,
                 confidence, reasoning, llm_analyzed_at) = row
                
                table_entities[str(file_id)] = {
                    "file_id": str(file_id),
                    "row_represents": row_represents,
                    "entity_identifier": entity_identifier,
                    "confidence": confidence or 0.0,
                    "reasoning": reasoning,
                    "llm_analyzed_at": str(llm_analyzed_at) if llm_analyzed_at else None
                }
                
        except Exception as e:
            print(f"[OntologySchema] Error loading table entities: {e}")
        
        return table_entities
    
    def save_table_entities(self, table_entities: List[Dict[str, Any]]):
        """
        table_entities 저장 (UPSERT)
        
        Args:
            table_entities: [{"file_id": ..., "row_represents": ..., ...}, ...]
        """
        if not table_entities:
            return
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for entity_info in table_entities:
                cursor.execute("""
                    INSERT INTO table_entities (
                        file_id, row_represents, entity_identifier,
                        confidence, reasoning, llm_analyzed_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT (file_id)
                    DO UPDATE SET
                        row_represents = EXCLUDED.row_represents,
                        entity_identifier = EXCLUDED.entity_identifier,
                        confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning,
                        llm_analyzed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    entity_info.get("file_id"),
                    entity_info.get("row_represents"),
                    entity_info.get("entity_identifier"),
                    entity_info.get("confidence", 0.0),
                    entity_info.get("reasoning")
                ))
            
            conn.commit()
            print(f"[OntologySchema] Saved {len(table_entities)} table entities")
            
        except Exception as e:
            conn.rollback()
            print(f"[OntologySchema] Error saving table entities: {e}")
            raise
    
    # =========================================================================
    # table_relationships CRUD
    # =========================================================================
    
    def load_table_relationships(self, file_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        table_relationships 로드
        
        Args:
            file_ids: 필터링할 file_id 목록 (source 또는 target)
        
        Returns:
            [{"rel_id": ..., "source_file_id": ..., ...}, ...]
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        relationships = []
        
        try:
            if file_ids:
                placeholders = ', '.join(['%s'] * len(file_ids))
                cursor.execute(f"""
                    SELECT rel_id, source_file_id, target_file_id,
                           source_column, target_column,
                           relationship_type, cardinality,
                           confidence, reasoning
                    FROM table_relationships
                    WHERE source_file_id IN ({placeholders})
                       OR target_file_id IN ({placeholders})
                """, file_ids + file_ids)
            else:
                cursor.execute("""
                    SELECT rel_id, source_file_id, target_file_id,
                           source_column, target_column,
                           relationship_type, cardinality,
                           confidence, reasoning
                    FROM table_relationships
                """)
            
            for row in cursor.fetchall():
                (rel_id, source_file_id, target_file_id,
                 source_column, target_column,
                 relationship_type, cardinality,
                 confidence, reasoning) = row
                
                relationships.append({
                    "rel_id": str(rel_id),
                    "source_file_id": str(source_file_id),
                    "target_file_id": str(target_file_id),
                    "source_column": source_column,
                    "target_column": target_column,
                    "relationship_type": relationship_type,
                    "cardinality": cardinality,
                    "confidence": confidence or 0.0,
                    "reasoning": reasoning
                })
                
        except Exception as e:
            print(f"[OntologySchema] Error loading table relationships: {e}")
        
        return relationships
    
    def save_table_relationships(self, relationships: List[Dict[str, Any]]):
        """
        table_relationships 저장 (UPSERT)
        
        Args:
            relationships: [{"source_file_id": ..., "target_file_id": ..., ...}, ...]
        """
        if not relationships:
            return
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for rel in relationships:
                cursor.execute("""
                    INSERT INTO table_relationships (
                        source_file_id, target_file_id,
                        source_column, target_column,
                        relationship_type, cardinality,
                        confidence, reasoning
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_file_id, target_file_id, source_column, target_column)
                    DO UPDATE SET
                        relationship_type = EXCLUDED.relationship_type,
                        cardinality = EXCLUDED.cardinality,
                        confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning
                """, (
                    rel.get("source_file_id"),
                    rel.get("target_file_id"),
                    rel.get("source_column"),
                    rel.get("target_column"),
                    rel.get("relationship_type"),
                    rel.get("cardinality"),
                    rel.get("confidence", 0.0),
                    rel.get("reasoning")
                ))
            
            conn.commit()
            print(f"[OntologySchema] Saved {len(relationships)} table relationships")
            
        except Exception as e:
            conn.rollback()
            print(f"[OntologySchema] Error saving table relationships: {e}")
            raise
    
    # =========================================================================
    # Phase 2C: ontology_subcategories CRUD
    # =========================================================================
    
    def save_subcategories(self, subcategories: List[Dict[str, Any]]):
        """
        ontology_subcategories 저장 (UPSERT)
        
        Args:
            subcategories: [{"parent_category": ..., "subcategory_name": ..., ...}, ...]
        """
        if not subcategories:
            return
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for subcat in subcategories:
                cursor.execute("""
                    INSERT INTO ontology_subcategories (
                        parent_category, subcategory_name,
                        confidence, reasoning
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (parent_category, subcategory_name)
                    DO UPDATE SET
                        confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning
                """, (
                    subcat.get("parent_category"),
                    subcat.get("subcategory_name"),
                    subcat.get("confidence", 0.0),
                    subcat.get("reasoning")
                ))
            
            conn.commit()
            print(f"[OntologySchema] Saved {len(subcategories)} subcategories")
            
        except Exception as e:
            conn.rollback()
            print(f"[OntologySchema] Error saving subcategories: {e}")
            raise
    
    def load_subcategories(self) -> List[Dict[str, Any]]:
        """ontology_subcategories 로드"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        subcategories = []
        
        try:
            cursor.execute("""
                SELECT subcategory_id, parent_category, subcategory_name,
                       confidence, reasoning
                FROM ontology_subcategories
                ORDER BY parent_category, subcategory_name
            """)
            
            for row in cursor.fetchall():
                subcategory_id, parent, name, conf, reasoning = row
                subcategories.append({
                    "subcategory_id": str(subcategory_id),
                    "parent_category": parent,
                    "subcategory_name": name,
                    "confidence": conf or 0.0,
                    "reasoning": reasoning
                })
                
        except Exception as e:
            print(f"[OntologySchema] Error loading subcategories: {e}")
        
        return subcategories
    
    # =========================================================================
    # Phase 2C: semantic_edges CRUD
    # =========================================================================
    
    def save_semantic_edges(self, edges: List[Dict[str, Any]]):
        """
        semantic_edges 저장 (UPSERT)
        
        Args:
            edges: [{"source_parameter": ..., "target_parameter": ..., "relationship_type": ..., ...}, ...]
        """
        if not edges:
            return
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for edge in edges:
                cursor.execute("""
                    INSERT INTO semantic_edges (
                        source_parameter, target_parameter, relationship_type,
                        confidence, reasoning
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_parameter, target_parameter, relationship_type)
                    DO UPDATE SET
                        confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning
                """, (
                    edge.get("source_parameter"),
                    edge.get("target_parameter"),
                    edge.get("relationship_type"),
                    edge.get("confidence", 0.0),
                    edge.get("reasoning")
                ))
            
            conn.commit()
            print(f"[OntologySchema] Saved {len(edges)} semantic edges")
            
        except Exception as e:
            conn.rollback()
            print(f"[OntologySchema] Error saving semantic edges: {e}")
            raise
    
    def load_semantic_edges(self) -> List[Dict[str, Any]]:
        """semantic_edges 로드"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        edges = []
        
        try:
            cursor.execute("""
                SELECT edge_id, source_parameter, target_parameter,
                       relationship_type, confidence, reasoning
                FROM semantic_edges
            """)
            
            for row in cursor.fetchall():
                edge_id, source, target, rel_type, conf, reasoning = row
                edges.append({
                    "edge_id": str(edge_id),
                    "source_parameter": source,
                    "target_parameter": target,
                    "relationship_type": rel_type,
                    "confidence": conf or 0.0,
                    "reasoning": reasoning
                })
                
        except Exception as e:
            print(f"[OntologySchema] Error loading semantic edges: {e}")
        
        return edges
    
    # =========================================================================
    # Phase 2C: medical_term_mappings CRUD
    # =========================================================================
    
    def save_medical_term_mappings(self, mappings: List[Dict[str, Any]]):
        """
        medical_term_mappings 저장 (UPSERT)
        
        Args:
            mappings: [{"parameter_key": ..., "snomed_code": ..., ...}, ...]
        """
        if not mappings:
            return
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for mapping in mappings:
                cursor.execute("""
                    INSERT INTO medical_term_mappings (
                        parameter_key, snomed_code, snomed_name,
                        loinc_code, loinc_name, icd10_code, icd10_name,
                        confidence
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (parameter_key)
                    DO UPDATE SET
                        snomed_code = EXCLUDED.snomed_code,
                        snomed_name = EXCLUDED.snomed_name,
                        loinc_code = EXCLUDED.loinc_code,
                        loinc_name = EXCLUDED.loinc_name,
                        icd10_code = EXCLUDED.icd10_code,
                        icd10_name = EXCLUDED.icd10_name,
                        confidence = EXCLUDED.confidence
                """, (
                    mapping.get("parameter_key"),
                    mapping.get("snomed_code"),
                    mapping.get("snomed_name"),
                    mapping.get("loinc_code"),
                    mapping.get("loinc_name"),
                    mapping.get("icd10_code"),
                    mapping.get("icd10_name"),
                    mapping.get("confidence", 0.0)
                ))
            
            conn.commit()
            print(f"[OntologySchema] Saved {len(mappings)} medical term mappings")
            
        except Exception as e:
            conn.rollback()
            print(f"[OntologySchema] Error saving medical term mappings: {e}")
            raise
    
    def load_medical_term_mappings(self) -> List[Dict[str, Any]]:
        """medical_term_mappings 로드"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        mappings = []
        
        try:
            cursor.execute("""
                SELECT mapping_id, parameter_key, snomed_code, snomed_name,
                       loinc_code, loinc_name, icd10_code, icd10_name, confidence
                FROM medical_term_mappings
            """)
            
            for row in cursor.fetchall():
                (mapping_id, param, snomed_code, snomed_name,
                 loinc_code, loinc_name, icd10_code, icd10_name, conf) = row
                mappings.append({
                    "mapping_id": str(mapping_id),
                    "parameter_key": param,
                    "snomed_code": snomed_code,
                    "snomed_name": snomed_name,
                    "loinc_code": loinc_code,
                    "loinc_name": loinc_name,
                    "icd10_code": icd10_code,
                    "icd10_name": icd10_name,
                    "confidence": conf or 0.0
                })
                
        except Exception as e:
            print(f"[OntologySchema] Error loading medical term mappings: {e}")
        
        return mappings
    
    # =========================================================================
    # Phase 2C: cross_table_semantics CRUD
    # =========================================================================
    
    def save_cross_table_semantics(self, semantics: List[Dict[str, Any]]):
        """
        cross_table_semantics 저장 (UPSERT)
        
        Args:
            semantics: [{"source_file_id": ..., "source_column": ..., ...}, ...]
        """
        if not semantics:
            return
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for sem in semantics:
                cursor.execute("""
                    INSERT INTO cross_table_semantics (
                        source_file_id, source_column,
                        target_file_id, target_column,
                        relationship_type, confidence, reasoning
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_file_id, source_column, target_file_id, target_column)
                    DO UPDATE SET
                        relationship_type = EXCLUDED.relationship_type,
                        confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning
                """, (
                    sem.get("source_file_id"),
                    sem.get("source_column"),
                    sem.get("target_file_id"),
                    sem.get("target_column"),
                    sem.get("relationship_type"),
                    sem.get("confidence", 0.0),
                    sem.get("reasoning")
                ))
            
            conn.commit()
            print(f"[OntologySchema] Saved {len(semantics)} cross table semantics")
            
        except Exception as e:
            conn.rollback()
            print(f"[OntologySchema] Error saving cross table semantics: {e}")
            raise
    
    def load_cross_table_semantics(self) -> List[Dict[str, Any]]:
        """cross_table_semantics 로드"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        semantics = []
        
        try:
            cursor.execute("""
                SELECT semantic_id, source_file_id, source_column,
                       target_file_id, target_column,
                       relationship_type, confidence, reasoning
                FROM cross_table_semantics
            """)
            
            for row in cursor.fetchall():
                (semantic_id, src_file, src_col,
                 tgt_file, tgt_col, rel_type, conf, reasoning) = row
                semantics.append({
                    "semantic_id": str(semantic_id),
                    "source_file_id": str(src_file),
                    "source_column": src_col,
                    "target_file_id": str(tgt_file),
                    "target_column": tgt_col,
                    "relationship_type": rel_type,
                    "confidence": conf or 0.0,
                    "reasoning": reasoning
                })
                
        except Exception as e:
            print(f"[OntologySchema] Error loading cross table semantics: {e}")
        
        return semantics


# =============================================================================
# 편의 함수
# =============================================================================

def init_ontology_schema(reset: bool = False):
    """온톨로지 스키마 초기화"""
    manager = OntologySchemaManager()
    if reset:
        manager.reset_tables()
    else:
        manager.create_tables()
    return manager


def ensure_ontology_schema():
    """온톨로지 스키마가 존재하는지 확인하고 없으면 생성"""
    manager = OntologySchemaManager()
    try:
        manager.create_tables()
    except Exception:
        pass  # 이미 존재하면 무시

