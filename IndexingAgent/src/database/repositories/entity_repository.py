# src/database/repositories/entity_repository.py
"""
EntityRepository - table_entities, table_relationships 관련 조회/저장

table_entities 테이블:
- entity_id, file_id
- row_represents, entity_identifier
- confidence, reasoning

table_relationships 테이블:
- relationship_id, source_file_id, target_file_id
- source_column, target_column
- relationship_type, cardinality
- confidence, reasoning
"""

from typing import Dict, Any, List, Optional, Set
from .base import BaseRepository


class EntityRepository(BaseRepository):
    """
    table_entities, table_relationships 테이블 조회/저장 Repository
    
    주요 메서드:
    - get_tables_with_entities(): entity 정보가 포함된 테이블 목록
    - get_entity_by_file(): 특정 파일의 entity 정보
    - save_table_entities(): entity 정보 저장
    - get_relationships(): 관계 목록 조회
    - find_shared_columns(): FK 후보 컬럼 탐지
    """
    
    def get_tables_with_entities(
        self, 
        file_paths: List[str] = None,
        include_semantic: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Entity 정보가 포함된 테이블 목록 조회
        
        table_entities + file_catalog + column_metadata 조인
        relationship_inference node에서 FK 관계 추론 시 사용
        
        Args:
            file_paths: 특정 파일 경로만 조회 (None이면 전체)
            include_semantic: parameter 테이블의 semantic 정보 포함 여부
        
        Returns:
            [
                {
                    "file_id": str,
                    "file_name": str,
                    "row_represents": str,
                    "entity_identifier": str,
                    "row_count": int,
                    "confidence": float,
                    "columns": [...],
                    "filename_values": dict
                }
            ]
        """
        from .column_repository import ColumnRepository
        col_repo = ColumnRepository(self.db)
        
        # table_entities + file_catalog 조인
        query = """
            SELECT 
                te.file_id,
                fc.file_name,
                fc.file_metadata,
                te.row_represents,
                te.entity_identifier,
                te.confidence,
                fc.filename_values
            FROM table_entities te
            JOIN file_catalog fc ON te.file_id = fc.file_id
        """
        
        if file_paths:
            placeholders = ','.join(['%s'] * len(file_paths))
            query += f" WHERE fc.file_path IN ({placeholders})"
            rows = self._execute_query(query, tuple(file_paths), fetch="all")
        else:
            rows = self._execute_query(query, fetch="all")
        
        tables = []
        for row in rows:
            (file_id, file_name, file_metadata, row_represents,
             entity_identifier, confidence, filename_values) = row
            
            # row_count 추출
            metadata = self._parse_json_field(file_metadata)
            row_count = metadata.get('row_count', 0)
            
            # 컬럼 정보 조회 (semantic 포함 여부에 따라)
            if include_semantic:
                columns = col_repo.get_columns_for_relationship_with_semantic(str(file_id))
            else:
                columns = col_repo.get_columns_for_relationship(str(file_id))
            
            tables.append({
                "file_id": str(file_id),
                "file_name": file_name,
                "row_represents": row_represents,
                "entity_identifier": entity_identifier,
                "row_count": row_count,
                "confidence": confidence or 0.0,
                "columns": columns,
                "filename_values": self._parse_json_field(filename_values)
            })
        
        return tables
    
    def get_entity_by_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        """특정 파일의 entity 정보 조회"""
        row = self._execute_query("""
            SELECT file_id, row_represents, entity_identifier,
                   confidence, reasoning
            FROM table_entities
            WHERE file_id = %s
        """, (file_id,), fetch="one")
        
        if not row:
            return None
        
        file_id, row_rep, entity_id_col, conf, reasoning = row
        
        return {
            "file_id": str(file_id),
            "row_represents": row_rep,
            "entity_identifier": entity_id_col,
            "confidence": conf,
            "reasoning": reasoning
        }
    
    def save_table_entities(
        self, 
        entities: List[Dict[str, Any]]
    ) -> int:
        """
        table_entities 저장 (UPSERT)
        
        Args:
            entities: [
                {
                    "file_id": str,
                    "row_represents": str,
                    "entity_identifier": str (optional),
                    "confidence": float,
                    "reasoning": str
                }
            ]
        
        Returns:
            저장된 엔트리 수
        """
        if not entities:
            return 0
        
        conn, cursor = self._get_cursor()
        count = 0
        
        try:
            for entity in entities:
                cursor.execute("""
                    INSERT INTO table_entities (
                        file_id, row_represents, entity_identifier,
                        confidence, reasoning, llm_analyzed_at
                    ) VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (file_id)
                    DO UPDATE SET
                        row_represents = EXCLUDED.row_represents,
                        entity_identifier = EXCLUDED.entity_identifier,
                        confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning,
                        llm_analyzed_at = NOW(),
                        updated_at = NOW()
                """, (
                    entity.get("file_id"),
                    entity.get("row_represents"),
                    entity.get("entity_identifier"),
                    entity.get("confidence", 0.0),
                    entity.get("reasoning", "")
                ))
                count += 1
            
            conn.commit()
            return count
        except Exception as e:
            conn.rollback()
            print(f"[EntityRepository] Error saving entities: {e}")
            raise
    
    def find_shared_columns(
        self, 
        tables: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        테이블 간 공유 컬럼 찾기 (FK 후보)
        
        filename_values도 가상 컬럼으로 취급하여 FK 후보에 포함
        
        Args:
            tables: get_tables_with_entities()의 결과
        
        Returns:
            [
                {
                    "column_name": "caseid",
                    "tables": [
                        {
                            "file_name": "clinical_data.csv",
                            "unique_count": 6388,
                            "row_count": 6388,
                            "source": "column"
                        },
                        {
                            "file_name": "3249.vital",
                            "unique_count": 1,
                            "row_count": 0,
                            "source": "filename",
                            "extracted_value": 3249
                        }
                    ]
                }
            ]
        """
        column_to_tables: Dict[str, List] = {}
        
        for table in tables:
            file_name = table['file_name']
            row_count = table['row_count']
            
            # 1. 일반 컬럼
            for col in table.get('columns', []):
                col_name = col['original_name']
                unique_count = col.get('unique_count')
                
                if col_name not in column_to_tables:
                    column_to_tables[col_name] = []
                
                column_to_tables[col_name].append({
                    "file_name": file_name,
                    "unique_count": unique_count,
                    "row_count": row_count,
                    "source": "column"
                })
            
            # 2. filename_values의 키도 가상 컬럼으로 추가
            filename_values = table.get('filename_values', {})
            if filename_values:
                for fv_key, fv_value in filename_values.items():
                    if fv_key not in column_to_tables:
                        column_to_tables[fv_key] = []
                    
                    # 중복 방지
                    already_exists = any(
                        t['file_name'] == file_name 
                        for t in column_to_tables[fv_key]
                    )
                    if not already_exists:
                        column_to_tables[fv_key].append({
                            "file_name": file_name,
                            "unique_count": 1,
                            "row_count": row_count,
                            "source": "filename",
                            "extracted_value": fv_value
                        })
        
        # 2개 이상 테이블에 존재하는 컬럼만 반환
        shared = []
        for col_name, table_list in column_to_tables.items():
            if len(table_list) >= 2:
                shared.append({
                    "column_name": col_name,
                    "tables": table_list
                })
        
        return shared
    
    def get_relationships(self) -> List[Dict[str, Any]]:
        """모든 테이블 관계 조회"""
        rows = self._execute_query("""
            SELECT r.relationship_id, r.source_file_id, r.target_file_id,
                   r.source_column, r.target_column,
                   r.relationship_type, r.cardinality,
                   r.confidence, r.reasoning,
                   sf.file_name as source_name,
                   tf.file_name as target_name
            FROM table_relationships r
            JOIN file_catalog sf ON r.source_file_id = sf.file_id
            JOIN file_catalog tf ON r.target_file_id = tf.file_id
            ORDER BY r.confidence DESC
        """, fetch="all")
        
        return [self._rel_row_to_dict(row) for row in rows]
    
    def save_relationships(
        self, 
        relationships: List[Dict[str, Any]]
    ) -> int:
        """
        table_relationships 저장 (UPSERT)
        
        Args:
            relationships: [
                {
                    "source_file_id": str,
                    "target_file_id": str,
                    "source_column": str,
                    "target_column": str,
                    "relationship_type": str,
                    "cardinality": str,
                    "confidence": float,
                    "reasoning": str
                }
            ]
        
        Returns:
            저장된 관계 수
        """
        if not relationships:
            return 0
        
        conn, cursor = self._get_cursor()
        count = 0
        
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
                    rel.get("relationship_type", "foreign_key"),
                    rel.get("cardinality", "1:N"),
                    rel.get("confidence", 0.0),
                    rel.get("reasoning", "")
                ))
                count += 1
            
            conn.commit()
            return count
        except Exception as e:
            conn.rollback()
            print(f"[EntityRepository] Error saving relationships: {e}")
            raise
    
    def _rel_row_to_dict(self, row: tuple) -> Dict[str, Any]:
        """relationship row를 dict로 변환"""
        (rel_id, src_id, tgt_id, src_col, tgt_col,
         rel_type, cardinality, conf, reasoning,
         src_name, tgt_name) = row
        
        return {
            "relationship_id": str(rel_id),
            "source_file_id": str(src_id),
            "target_file_id": str(tgt_id),
            "source_column": src_col,
            "target_column": tgt_col,
            "relationship_type": rel_type,
            "cardinality": cardinality,
            "confidence": conf,
            "reasoning": reasoning,
            "source_name": src_name,
            "target_name": tgt_name
        }

