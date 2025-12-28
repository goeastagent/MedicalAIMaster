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
    dataset_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    row_represents TEXT,
    row_represents_kr TEXT,
    entity_identifier TEXT,
    linkable_columns JSONB DEFAULT '[]',
    hierarchy_explanation TEXT,
    confidence REAL DEFAULT 0.0,
    reasoning TEXT,
    status TEXT DEFAULT 'NEEDS_REVIEW',
    user_feedback_applied TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dataset_id, table_name)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_table_entities_dataset 
    ON table_entities(dataset_id);
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
            cursor.execute(CREATE_ONTOLOGY_COLUMN_METADATA_SQL)
            cursor.execute(CREATE_TABLE_ENTITIES_SQL)
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
    
    def load_table_entities(self, dataset_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        table_entities 로드
        
        Returns:
            {table_name: entity_info_dict}
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        table_entities = {}
        
        try:
            if dataset_id:
                cursor.execute("""
                    SELECT table_name, row_represents, row_represents_kr, 
                           entity_identifier, linkable_columns, hierarchy_explanation,
                           confidence, reasoning, status, user_feedback_applied
                    FROM table_entities
                    WHERE dataset_id = %s
                """, (dataset_id,))
            else:
                cursor.execute("""
                    SELECT table_name, row_represents, row_represents_kr,
                           entity_identifier, linkable_columns, hierarchy_explanation,
                           confidence, reasoning, status, user_feedback_applied
                    FROM table_entities
                """)
            
            for row in cursor.fetchall():
                (table_name, row_represents, row_represents_kr,
                 entity_identifier, linkable_columns, hierarchy_explanation,
                 confidence, reasoning, status, user_feedback) = row
                
                table_entities[table_name] = {
                    "row_represents": row_represents,
                    "row_represents_kr": row_represents_kr,
                    "entity_identifier": entity_identifier,
                    "linkable_columns": linkable_columns or [],
                    "hierarchy_explanation": hierarchy_explanation,
                    "confidence": confidence or 0.0,
                    "reasoning": reasoning,
                    "status": status or "NEEDS_REVIEW",
                    "user_feedback_applied": user_feedback
                }
                
        except Exception as e:
            print(f"[OntologySchema] Error loading table entities: {e}")
        
        return table_entities
    
    def save_table_entities(self, table_entities: Dict, dataset_id: str):
        """
        table_entities 저장 (UPSERT)
        
        Args:
            table_entities: {table_name: entity_info_dict}
            dataset_id: 데이터셋 ID
        """
        if not table_entities:
            return
        
        import json
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for table_name, entity_info in table_entities.items():
                linkable_cols = entity_info.get("linkable_columns", [])
                if isinstance(linkable_cols, list):
                    linkable_cols = json.dumps(linkable_cols)
                
                cursor.execute("""
                    INSERT INTO table_entities (
                        dataset_id, table_name, row_represents, row_represents_kr,
                        entity_identifier, linkable_columns, hierarchy_explanation,
                        confidence, reasoning, status, user_feedback_applied, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (dataset_id, table_name)
                    DO UPDATE SET
                        row_represents = EXCLUDED.row_represents,
                        row_represents_kr = EXCLUDED.row_represents_kr,
                        entity_identifier = EXCLUDED.entity_identifier,
                        linkable_columns = EXCLUDED.linkable_columns,
                        hierarchy_explanation = EXCLUDED.hierarchy_explanation,
                        confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning,
                        status = EXCLUDED.status,
                        user_feedback_applied = EXCLUDED.user_feedback_applied,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    dataset_id, table_name,
                    entity_info.get("row_represents"),
                    entity_info.get("row_represents_kr"),
                    entity_info.get("entity_identifier"),
                    linkable_cols,
                    entity_info.get("hierarchy_explanation"),
                    entity_info.get("confidence", 0.0),
                    entity_info.get("reasoning"),
                    entity_info.get("status", "NEEDS_REVIEW"),
                    entity_info.get("user_feedback_applied")
                ))
            
            conn.commit()
            print(f"[OntologySchema] Saved {len(table_entities)} table entities")
            
        except Exception as e:
            conn.rollback()
            print(f"[OntologySchema] Error saving table entities: {e}")


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

