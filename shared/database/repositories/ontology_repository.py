# src/database/repositories/ontology_repository.py
"""
OntologyRepository - ontology_enhancement 온톨로지 테이블 CRUD

담당 테이블:
- ontology_subcategories: 카테고리 세분화
- semantic_edges: 파라미터 간 시맨틱 관계
- medical_term_mappings: 의료 표준 용어 매핑
- cross_table_semantics: 테이블 간 시맨틱 유사성
- ontology_column_metadata: 컬럼 메타데이터 (JSONB)
"""

import json
from typing import Dict, Any, List, Optional
from .base import BaseRepository


class OntologyRepository(BaseRepository):
    """
    ontology_enhancement 온톨로지 테이블 CRUD Repository
    """
    
    # =========================================================================
    # ontology_column_metadata
    # =========================================================================
    
    def load_column_metadata(self, dataset_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        ontology_column_metadata 로드
        
        Returns:
            {table_name: {column_name: metadata_dict}}
        """
        if dataset_id:
            rows = self._execute_query("""
                SELECT table_name, column_name, metadata
                FROM ontology_column_metadata
                WHERE dataset_id = %s
            """, (dataset_id,), fetch="all")
        else:
            rows = self._execute_query("""
                SELECT table_name, column_name, metadata
                FROM ontology_column_metadata
            """, fetch="all")
        
        result = {}
        for table_name, col_name, metadata in rows:
            if table_name not in result:
                result[table_name] = {}
            result[table_name][col_name] = metadata if isinstance(metadata, dict) else {}
        
        return result
    
    def save_column_metadata(self, column_metadata: Dict, dataset_id: str):
        """ontology_column_metadata 저장 (UPSERT)"""
        if not column_metadata:
            return
        
        conn, cursor = self._get_cursor()
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
        except Exception:
            conn.rollback()
            raise
    
    # =========================================================================
    # ontology_subcategories
    # =========================================================================
    
    def save_subcategories(self, subcategories: List[Dict[str, Any]]) -> int:
        """ontology_subcategories 저장 (UPSERT)"""
        if not subcategories:
            return 0
        
        conn, cursor = self._get_cursor()
        count = 0
        
        try:
            for subcat in subcategories:
                cursor.execute("""
                    INSERT INTO ontology_subcategories (
                        parent_category, subcategory_name, confidence, reasoning
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (parent_category, subcategory_name)
                    DO UPDATE SET confidence = EXCLUDED.confidence, reasoning = EXCLUDED.reasoning
                """, (
                    subcat.get("parent_category"),
                    subcat.get("subcategory_name"),
                    subcat.get("confidence", 0.0),
                    subcat.get("reasoning")
                ))
                count += 1
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise
    
    def load_subcategories(self) -> List[Dict[str, Any]]:
        """ontology_subcategories 로드"""
        rows = self._execute_query("""
            SELECT subcategory_id, parent_category, subcategory_name, confidence, reasoning
            FROM ontology_subcategories
            ORDER BY parent_category, subcategory_name
        """, fetch="all")
        
        return [{
            "subcategory_id": str(row[0]),
            "parent_category": row[1],
            "subcategory_name": row[2],
            "confidence": row[3] or 0.0,
            "reasoning": row[4]
        } for row in rows]
    
    # =========================================================================
    # semantic_edges
    # =========================================================================
    
    def save_semantic_edges(self, edges: List[Dict[str, Any]]) -> int:
        """semantic_edges 저장 (UPSERT)"""
        if not edges:
            return 0
        
        conn, cursor = self._get_cursor()
        count = 0
        
        try:
            for edge in edges:
                cursor.execute("""
                    INSERT INTO semantic_edges (
                        source_parameter, target_parameter, relationship_type,
                        confidence, reasoning
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_parameter, target_parameter, relationship_type)
                    DO UPDATE SET confidence = EXCLUDED.confidence, reasoning = EXCLUDED.reasoning
                """, (
                    edge.get("source_parameter"),
                    edge.get("target_parameter"),
                    edge.get("relationship_type"),
                    edge.get("confidence", 0.0),
                    edge.get("reasoning")
                ))
                count += 1
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise
    
    def load_semantic_edges(self) -> List[Dict[str, Any]]:
        """semantic_edges 로드"""
        rows = self._execute_query("""
            SELECT edge_id, source_parameter, target_parameter, 
                   relationship_type, confidence, reasoning
            FROM semantic_edges
        """, fetch="all")
        
        return [{
            "edge_id": str(row[0]),
            "source_parameter": row[1],
            "target_parameter": row[2],
            "relationship_type": row[3],
            "confidence": row[4] or 0.0,
            "reasoning": row[5]
        } for row in rows]
    
    # =========================================================================
    # medical_term_mappings
    # =========================================================================
    
    def save_medical_term_mappings(self, mappings: List[Dict[str, Any]]) -> int:
        """medical_term_mappings 저장 (UPSERT)"""
        if not mappings:
            return 0
        
        conn, cursor = self._get_cursor()
        count = 0
        
        try:
            for m in mappings:
                cursor.execute("""
                    INSERT INTO medical_term_mappings (
                        parameter_key, snomed_code, snomed_name,
                        loinc_code, loinc_name, icd10_code, icd10_name,
                        confidence, reasoning
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (parameter_key)
                    DO UPDATE SET
                        snomed_code = EXCLUDED.snomed_code,
                        snomed_name = EXCLUDED.snomed_name,
                        loinc_code = EXCLUDED.loinc_code,
                        loinc_name = EXCLUDED.loinc_name,
                        icd10_code = EXCLUDED.icd10_code,
                        icd10_name = EXCLUDED.icd10_name,
                        confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning
                """, (
                    m.get("parameter_key"),
                    m.get("snomed_code"), m.get("snomed_name"),
                    m.get("loinc_code"), m.get("loinc_name"),
                    m.get("icd10_code"), m.get("icd10_name"),
                    m.get("confidence", 0.0), m.get("reasoning")
                ))
                count += 1
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise
    
    def load_medical_term_mappings(self) -> List[Dict[str, Any]]:
        """medical_term_mappings 로드"""
        rows = self._execute_query("""
            SELECT mapping_id, parameter_key, snomed_code, snomed_name,
                   loinc_code, loinc_name, icd10_code, icd10_name, 
                   confidence, reasoning
            FROM medical_term_mappings
        """, fetch="all")
        
        return [{
            "mapping_id": str(row[0]),
            "parameter_key": row[1],
            "snomed_code": row[2], "snomed_name": row[3],
            "loinc_code": row[4], "loinc_name": row[5],
            "icd10_code": row[6], "icd10_name": row[7],
            "confidence": row[8] or 0.0, "reasoning": row[9]
        } for row in rows]
    
    # =========================================================================
    # cross_table_semantics
    # =========================================================================
    
    def save_cross_table_semantics(self, semantics: List[Dict[str, Any]]) -> int:
        """cross_table_semantics 저장 (UPSERT)"""
        if not semantics:
            return 0
        
        conn, cursor = self._get_cursor()
        count = 0
        
        try:
            for sem in semantics:
                cursor.execute("""
                    INSERT INTO cross_table_semantics (
                        source_file_id, source_column, target_file_id, target_column,
                        relationship_type, confidence, reasoning
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_file_id, source_column, target_file_id, target_column)
                    DO UPDATE SET
                        relationship_type = EXCLUDED.relationship_type,
                        confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning
                """, (
                    sem.get("source_file_id"), sem.get("source_column"),
                    sem.get("target_file_id"), sem.get("target_column"),
                    sem.get("relationship_type"),
                    sem.get("confidence", 0.0), sem.get("reasoning")
                ))
                count += 1
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise
    
    def load_cross_table_semantics(self) -> List[Dict[str, Any]]:
        """cross_table_semantics 로드"""
        rows = self._execute_query("""
            SELECT semantic_id, source_file_id, source_column,
                   target_file_id, target_column,
                   relationship_type, confidence, reasoning
            FROM cross_table_semantics
        """, fetch="all")
        
        return [{
            "semantic_id": str(row[0]),
            "source_file_id": str(row[1]), "source_column": row[2],
            "target_file_id": str(row[3]), "target_column": row[4],
            "relationship_type": row[5],
            "confidence": row[6] or 0.0, "reasoning": row[7]
        } for row in rows]

