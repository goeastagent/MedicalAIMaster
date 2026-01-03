# src/database/repositories/column_repository.py
"""
ColumnRepository - column_metadata 테이블 관련 조회

column_metadata 테이블:
- col_id, file_id, original_name
- data_type, column_type, column_info (JSONB), value_distribution (JSONB)
- column_role (column_classification 결과)

Note: semantic 정보(semantic_name, unit, concept_category 등)는 
      parameter 테이블에서 관리됩니다.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from .base import BaseRepository


class ColumnRepository(BaseRepository):
    """
    column_metadata 테이블 조회 Repository
    
    주요 메서드:
    - get_columns_by_file(): 파일의 모든 컬럼 조회
    - get_columns_for_classification(): 분류용 컬럼 정보
    - get_columns_with_stats(): 통계 포함 컬럼 정보
    - update_column_role(): 컬럼 역할 업데이트
    """
    
    def get_columns_by_file(self, file_id: str) -> List[Dict[str, Any]]:
        """
        파일의 모든 컬럼 조회
        
        Returns:
            [
                {
                    "col_id": int,
                    "original_name": str,
                    "data_type": str,
                    "column_type": str,
                    "column_role": str,
                    "column_role_reasoning": str,
                    "column_info": dict,
                    "value_distribution": dict
                }
            ]
        """
        rows = self._execute_query("""
            SELECT col_id, original_name, data_type, column_type,
                   column_role, column_role_reasoning, column_info, value_distribution
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        return [self._row_to_column_dict(row) for row in rows]
    
    def get_columns_for_classification(self, file_id: str) -> List[Dict[str, Any]]:
        """
        분류용 컬럼 정보 조회 (file_classification, column_classification)
        
        Returns:
            [
                {
                    "col_id": int,
                    "name": str,
                    "dtype": str,
                    "column_type": str,
                    "unique_values": list,
                    "n_unique": int
                }
            ]
        """
        rows = self._execute_query("""
            SELECT col_id, original_name, data_type, column_type, value_distribution
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            col_id, col_name, dtype, col_type, value_dist = row
            dist = self._parse_json_field(value_dist)
            
            unique_values = dist.get('unique_values', [])
            samples = dist.get('samples', [])
            
            # unique_values가 없으면 samples 사용
            if not unique_values and samples:
                unique_values = samples
            
            # 최대 10개만
            unique_values = unique_values[:10] if unique_values else []
            
            columns.append({
                "col_id": col_id,
                "name": col_name,
                "dtype": dtype or "unknown",
                "column_type": col_type or "unknown",
                "unique_values": unique_values,
                "n_unique": len(unique_values)
            })
        
        return columns
    
    def get_columns_with_stats(self, file_id: str) -> List[Dict[str, Any]]:
        """
        통계 포함 컬럼 정보 조회 (entity_identification 등)
        
        Returns:
            [
                {
                    "col_id": int,
                    "original_name": str,
                    "column_type": str,
                    "data_type": str,
                    "column_role": str,
                    "column_info": dict,  # min, max, mean 등
                    "value_distribution": dict,  # unique_values, samples 등
                    "unique_count": int
                }
            ]
        """
        rows = self._execute_query("""
            SELECT col_id, original_name, column_type, data_type,
                   column_role, column_info, value_distribution
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            (col_id, name, col_type, dtype, col_role, col_info, val_dist) = row
            
            col_info_dict = self._parse_json_field(col_info)
            val_dist_dict = self._parse_json_field(val_dist)
            
            # unique_count 추출
            unique_values = val_dist_dict.get('unique_values', [])
            unique_count = len(unique_values) if unique_values else col_info_dict.get('unique_count')
            
            columns.append({
                "col_id": col_id,
                "original_name": name,
                "column_type": col_type or "unknown",
                "data_type": dtype or "unknown",
                "column_role": col_role,
                "column_info": col_info_dict,
                "value_distribution": val_dist_dict,
                "unique_count": unique_count
            })
        
        return columns
    
    def get_columns_by_file_path(self, file_path: str) -> List[Dict[str, Any]]:
        """
        파일 경로로 컬럼 정보 조회 (column_classification node)
        
        file_catalog.file_path와 JOIN하여 컬럼 정보 반환
        
        Returns:
            [
                {
                    "col_id": int,
                    "column_name": str,
                    "data_type": str,
                    "unique_values": list,
                    "unique_count": int,
                    "total_count": int,
                    "null_count": int
                }
            ]
        """
        rows = self._execute_query("""
            SELECT cm.col_id, cm.original_name, cm.data_type,
                   cm.column_info, cm.value_distribution
            FROM column_metadata cm
            JOIN file_catalog fc ON cm.file_id = fc.file_id
            WHERE fc.file_path = %s
            ORDER BY cm.col_id
        """, (file_path,), fetch="all")
        
        columns = []
        for row in rows:
            (col_id, col_name, dtype, col_info, val_dist) = row
            
            col_info_dict = self._parse_json_field(col_info)
            val_dist_dict = self._parse_json_field(val_dist)
            
            # unique_values 추출
            unique_values = val_dist_dict.get('unique_values', [])
            if not unique_values:
                unique_values = val_dist_dict.get('samples', [])
            
            # 통계 추출
            total_count = col_info_dict.get('count', 0)
            null_count = col_info_dict.get('null_count', 0)
            unique_count = len(unique_values) if unique_values else col_info_dict.get('unique_count', 0)
            
            columns.append({
                "col_id": col_id,
                "column_name": col_name,
                "data_type": dtype or "unknown",
                "unique_values": unique_values,
                "unique_count": unique_count,
                "total_count": total_count,
                "null_count": null_count
            })
        
        return columns
    
    def get_column_by_name(
        self, 
        file_path: str, 
        column_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        파일 경로와 컬럼명으로 단일 컬럼 정보 조회
        
        Args:
            file_path: 파일 경로
            column_name: 컬럼명
        
        Returns:
            {"col_id": int, "column_name": str, "data_type": str} or None
        """
        row = self._execute_query("""
            SELECT cm.col_id, cm.original_name, cm.data_type
            FROM column_metadata cm
            JOIN file_catalog fc ON cm.file_id = fc.file_id
            WHERE fc.file_path = %s AND cm.original_name = %s
        """, (file_path, column_name), fetch="one")
        
        if not row:
            return None
        
        return {
            "col_id": row[0],
            "column_name": row[1],
            "data_type": row[2]
        }
    
    def get_columns_for_entity_analysis(
        self, 
        file_id: str
    ) -> List[Dict[str, Any]]:
        """
        Entity 분석용 컬럼 정보 조회 (entity_identification node)
        
        Note: semantic 정보가 필요하면 parameter 테이블과 JOIN해야 함
        """
        rows = self._execute_query("""
            SELECT col_id, original_name, column_type, column_role,
                   column_info, value_distribution
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            (col_id, name, col_type, col_role, col_info, val_dist) = row
            
            val_dist_dict = self._parse_json_field(val_dist)
            unique_values = val_dist_dict.get('unique_values', [])
            unique_count = len(unique_values) if unique_values else None
            
            # column_info에서도 unique_count 추출 시도
            if unique_count is None:
                col_info_dict = self._parse_json_field(col_info)
                unique_count = col_info_dict.get('unique_count')
            
            columns.append({
                "col_id": col_id,
                "original_name": name,
                "column_type": col_type,
                "column_role": col_role,
                "unique_count": unique_count,
                "column_info": self._parse_json_field(col_info)
            })
        
        return columns
    
    def get_columns_for_relationship(
        self, 
        file_id: str
    ) -> List[Dict[str, Any]]:
        """
        관계 추론용 컬럼 정보 조회 (relationship_inference node)
        """
        rows = self._execute_query("""
            SELECT col_id, original_name, column_role, value_distribution
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            col_id, name, col_role, val_dist = row
            
            val_dist_dict = self._parse_json_field(val_dist)
            unique_values = val_dist_dict.get('unique_values', [])
            
            columns.append({
                "col_id": col_id,
                "original_name": name,
                "column_role": col_role,
                "unique_count": len(unique_values) if unique_values else None
            })
        
        return columns
    
    def get_columns_for_relationship_with_semantic(
        self, 
        file_id: str
    ) -> List[Dict[str, Any]]:
        """
        [R3 확장] 관계 추론용 컬럼 정보 + semantic 조회
        
        [900] relationship_inference 노드의 _load_tables_with_entity_and_columns()에서 사용
        parameter 테이블과 JOIN하여 semantic 정보 포함
        
        Returns:
            [
                {
                    "col_id": int,
                    "original_name": str,
                    "column_role": str,
                    "semantic_name": str,
                    "concept_category": str,
                    "unit": str,
                    "unique_count": int
                }
            ]
        """
        rows = self._execute_query("""
            SELECT 
                cm.col_id,
                cm.original_name,
                cm.column_role,
                cm.value_distribution,
                p.semantic_name,
                p.concept_category,
                p.unit
            FROM column_metadata cm
            LEFT JOIN parameter p ON cm.col_id = p.source_column_id 
                                  AND cm.file_id = p.file_id
            WHERE cm.file_id = %s
            ORDER BY cm.col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            col_id, name, col_role, val_dist, sem_name, concept, unit = row
            
            val_dist_dict = self._parse_json_field(val_dist)
            unique_values = val_dist_dict.get('unique_values', [])
            
            columns.append({
                "col_id": col_id,
                "original_name": name,
                "column_role": col_role,
                "semantic_name": sem_name,
                "concept_category": concept,
                "unit": unit,
                "unique_count": len(unique_values) if unique_values else None
            })
        
        return columns
    
    def get_column_count(self) -> int:
        """전체 컬럼 수 조회"""
        row = self._execute_query("""
            SELECT COUNT(*) FROM column_metadata
        """, fetch="one")
        
        return row[0] if row else 0
    
    def get_unique_column_count(self) -> int:
        """유니크 컬럼 수 조회"""
        row = self._execute_query("""
            SELECT COUNT(DISTINCT original_name) FROM column_metadata
        """, fetch="one")
        
        return row[0] if row else 0
    
    def get_column_id_by_name(
        self, 
        file_id: str, 
        original_name: str
    ) -> Optional[int]:
        """파일의 특정 컬럼 ID 조회"""
        row = self._execute_query("""
            SELECT col_id FROM column_metadata
            WHERE file_id = %s AND original_name = %s
        """, (file_id, original_name), fetch="one")
        
        return row[0] if row else None
    
    def update_column_role(
        self,
        column_role: str,
        column_role_reasoning: str = None,
        file_id: str = None,
        file_path: str = None,
        column_name: str = None,
        original_name: str = None
    ) -> int:
        """
        컬럼 역할 업데이트
        
        file_id 또는 file_path 중 하나 필요
        column_name 또는 original_name 중 하나 필요
        """
        conn, cursor = self._get_cursor()
        
        # column_name 우선 사용
        col_name = column_name or original_name
        
        try:
            if file_path:
                # file_path로 검색
                cursor.execute("""
                    UPDATE column_metadata cm
                    SET column_role = %s,
                        column_role_reasoning = %s,
                        updated_at = NOW()
                    FROM file_catalog fc
                    WHERE cm.file_id = fc.file_id
                      AND fc.file_path = %s 
                      AND cm.original_name = %s
                """, (column_role, column_role_reasoning, file_path, col_name))
            else:
                # file_id로 검색
                cursor.execute("""
                    UPDATE column_metadata
                    SET column_role = %s,
                        column_role_reasoning = %s,
                        updated_at = NOW()
                    WHERE file_id = %s AND original_name = %s
                """, (column_role, column_role_reasoning, file_id, col_name))
            
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            print(f"[ColumnRepository] Error updating column role: {e}")
            return 0
    
    def batch_update_column_roles(
        self,
        file_id: str,
        updates: List[Dict[str, Any]]
    ) -> int:
        """
        여러 컬럼의 역할 일괄 업데이트
        
        Args:
            file_id: 파일 ID
            updates: [
                {
                    "original_name": str,
                    "column_role": str,
                    "column_role_reasoning": str (optional)
                }
            ]
        
        Returns:
            업데이트된 행 수
        """
        conn, cursor = self._get_cursor()
        updated = 0
        
        try:
            for update in updates:
                cursor.execute("""
                    UPDATE column_metadata
                    SET column_role = %s,
                        column_role_reasoning = %s,
                        updated_at = NOW()
                    WHERE file_id = %s AND original_name = %s
                """, (
                    update.get('column_role'),
                    update.get('column_role_reasoning'),
                    file_id,
                    update.get('original_name')
                ))
                updated += cursor.rowcount
            
            conn.commit()
            return updated
        except Exception as e:
            conn.rollback()
            print(f"[ColumnRepository] Error batch updating roles: {e}")
            raise
    
    def get_parameter_container_columns(
        self,
        file_id: str
    ) -> List[Dict[str, Any]]:
        """
        parameter_container 역할의 컬럼 조회 (Long-format의 key 컬럼)
        
        Returns:
            [
                {
                    "col_id": int,
                    "original_name": str,
                    "unique_values": list  # 이 값들이 parameter가 됨
                }
            ]
        """
        rows = self._execute_query("""
            SELECT col_id, original_name, value_distribution
            FROM column_metadata
            WHERE file_id = %s AND column_role = 'parameter_container'
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            col_id, name, val_dist = row
            val_dist_dict = self._parse_json_field(val_dist)
            unique_values = val_dist_dict.get('unique_values', [])
            
            columns.append({
                "col_id": col_id,
                "original_name": name,
                "unique_values": unique_values
            })
        
        return columns
    
    def get_parameter_name_columns(
        self,
        file_id: str
    ) -> List[Dict[str, Any]]:
        """
        parameter_name 역할의 컬럼 조회 (Wide-format에서 컬럼명이 parameter)
        
        Returns:
            [
                {
                    "col_id": int,
                    "original_name": str,  # 이 값이 parameter가 됨
                    "column_info": dict
                }
            ]
        """
        rows = self._execute_query("""
            SELECT col_id, original_name, column_info
            FROM column_metadata
            WHERE file_id = %s AND column_role = 'parameter_name'
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            col_id, name, col_info = row
            
            columns.append({
                "col_id": col_id,
                "original_name": name,
                "column_info": self._parse_json_field(col_info)
            })
        
        return columns
    
    def get_columns_with_semantic(
        self,
        file_id: str
    ) -> List[Dict[str, Any]]:
        """
        [R3] Parameter JOIN하여 semantic 정보 포함한 컬럼 조회
        
        [800] ontology_enhancement 노드의 _load_tables_with_columns()에서 사용
        [700] relationship_inference 노드의 _load_tables_with_columns()에서 사용
        [500] entity_identification 노드의 _load_data_files_with_columns()에서 사용
        
        Returns:
            [
                {
                    "col_id": int,
                    "original_name": str,
                    "column_role": str,
                    "semantic_name": str,  # parameter에서 JOIN
                    "concept_category": str,  # parameter에서 JOIN
                    "unit": str  # parameter에서 JOIN
                }
            ]
        """
        rows = self._execute_query("""
            SELECT cm.col_id, cm.original_name, cm.column_role,
                   p.semantic_name, p.concept_category, p.unit
            FROM column_metadata cm
            LEFT JOIN parameter p ON cm.col_id = p.source_column_id 
                                  AND cm.file_id = p.file_id
            WHERE cm.file_id = %s
            ORDER BY cm.col_id
        """, (file_id,), fetch="all")
        
        return [
            {
                "col_id": r[0],
                "original_name": r[1],
                "column_role": r[2],
                "semantic_name": r[3] or r[1],  # fallback to original_name
                "concept_category": r[4],
                "unit": r[5]
            }
            for r in rows
        ]
    
    def _row_to_column_dict(self, row: tuple) -> Dict[str, Any]:
        """DB row를 dict로 변환"""
        (col_id, name, dtype, col_type, col_role, col_role_reasoning, col_info, val_dist) = row
        
        return {
            "col_id": col_id,
            "original_name": name,
            "data_type": dtype,
            "column_type": col_type,
            "column_role": col_role,
            "column_role_reasoning": col_role_reasoning,
            "column_info": self._parse_json_field(col_info),
            "value_distribution": self._parse_json_field(val_dist)
        }
