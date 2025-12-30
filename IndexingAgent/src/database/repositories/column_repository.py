# src/database/repositories/column_repository.py
"""
ColumnRepository - column_metadata 테이블 관련 조회

column_metadata 테이블:
- col_id, file_id, original_name
- semantic_name, unit, description, concept_category
- data_type, column_type, column_info (JSONB), value_distribution (JSONB)
- dict_entry_id, dict_match_status, match_confidence
- llm_confidence, llm_analyzed_at
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
    - update_semantic_info(): 시맨틱 정보 업데이트
    """
    
    def get_columns_by_file(self, file_id: str) -> List[Dict[str, Any]]:
        """
        파일의 모든 컬럼 조회
        
        Returns:
            [
                {
                    "col_id": int,
                    "original_name": str,
                    "semantic_name": str,
                    "unit": str,
                    "description": str,
                    "concept_category": str,
                    "data_type": str,
                    "column_type": str,
                    "column_info": dict,
                    "value_distribution": dict,
                    "dict_entry_id": str,
                    "dict_match_status": str,
                    "match_confidence": float
                }
            ]
        """
        rows = self._execute_query("""
            SELECT col_id, original_name, semantic_name, unit, description,
                   concept_category, data_type, column_type, column_info,
                   value_distribution, dict_entry_id, dict_match_status, match_confidence
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        return [self._row_to_column_dict(row) for row in rows]
    
    def get_columns_for_classification(self, file_id: str) -> List[Dict[str, Any]]:
        """
        분류용 컬럼 정보 조회 (Phase 4)
        
        Returns:
            [
                {
                    "name": str,
                    "dtype": str,
                    "column_type": str,
                    "unique_values": list,
                    "n_unique": int
                }
            ]
        """
        rows = self._execute_query("""
            SELECT original_name, data_type, column_type, value_distribution
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            col_name, dtype, col_type, value_dist = row
            dist = self._parse_json_field(value_dist)
            
            unique_values = dist.get('unique_values', [])
            samples = dist.get('samples', [])
            
            # unique_values가 없으면 samples 사용
            if not unique_values and samples:
                unique_values = samples
            
            # 최대 10개만
            unique_values = unique_values[:10] if unique_values else []
            
            columns.append({
                "name": col_name,
                "dtype": dtype or "unknown",
                "column_type": col_type or "unknown",
                "unique_values": unique_values,
                "n_unique": len(unique_values)
            })
        
        return columns
    
    def get_columns_with_stats(self, file_id: str) -> List[Dict[str, Any]]:
        """
        통계 포함 컬럼 정보 조회 (Phase 6, 8)
        
        Returns:
            [
                {
                    "col_id": int,
                    "original_name": str,
                    "semantic_name": str,
                    "column_type": str,
                    "data_type": str,
                    "concept_category": str,
                    "column_info": dict,  # min, max, mean 등
                    "value_distribution": dict,  # unique_values, samples 등
                    "unique_count": int
                }
            ]
        """
        rows = self._execute_query("""
            SELECT col_id, original_name, semantic_name, column_type, data_type,
                   concept_category, unit, column_info, value_distribution
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            (col_id, name, sem_name, col_type, dtype,
             concept, unit, col_info, val_dist) = row
            
            col_info_dict = self._parse_json_field(col_info)
            val_dist_dict = self._parse_json_field(val_dist)
            
            # unique_count 추출
            unique_values = val_dist_dict.get('unique_values', [])
            unique_count = len(unique_values) if unique_values else col_info_dict.get('unique_count')
            
            columns.append({
                "col_id": col_id,
                "original_name": name,
                "semantic_name": sem_name,
                "column_type": col_type or "unknown",
                "data_type": dtype or "unknown",
                "concept_category": concept,
                "unit": unit,
                "column_info": col_info_dict,
                "value_distribution": val_dist_dict,
                "unique_count": unique_count
            })
        
        return columns
    
    def get_columns_for_entity_analysis(
        self, 
        file_id: str
    ) -> List[Dict[str, Any]]:
        """
        Entity 분석용 컬럼 정보 조회 (Phase 8)
        Phase 6에서 분석된 semantic 정보 포함
        """
        rows = self._execute_query("""
            SELECT original_name, semantic_name, column_type,
                   concept_category, column_info, value_distribution
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            (name, sem_name, col_type, concept, col_info, val_dist) = row
            
            val_dist_dict = self._parse_json_field(val_dist)
            unique_values = val_dist_dict.get('unique_values', [])
            unique_count = len(unique_values) if unique_values else None
            
            # column_info에서도 unique_count 추출 시도
            if unique_count is None:
                col_info_dict = self._parse_json_field(col_info)
                unique_count = col_info_dict.get('unique_count')
            
            columns.append({
                "original_name": name,
                "semantic_name": sem_name,
                "column_type": col_type,
                "concept_category": concept,
                "unique_count": unique_count,
                "column_info": self._parse_json_field(col_info)
            })
        
        return columns
    
    def get_columns_for_relationship(
        self, 
        file_id: str
    ) -> List[Dict[str, Any]]:
        """
        관계 추론용 컬럼 정보 조회 (Phase 9)
        """
        rows = self._execute_query("""
            SELECT original_name, semantic_name, concept_category,
                   unit, value_distribution
            FROM column_metadata
            WHERE file_id = %s
            ORDER BY col_id
        """, (file_id,), fetch="all")
        
        columns = []
        for row in rows:
            name, sem_name, concept, unit, val_dist = row
            
            val_dist_dict = self._parse_json_field(val_dist)
            unique_values = val_dist_dict.get('unique_values', [])
            
            columns.append({
                "original_name": name,
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
    
    def update_semantic_info(
        self,
        file_id: str,
        original_name: str,
        semantic_name: str = None,
        unit: str = None,
        description: str = None,
        concept_category: str = None,
        dict_entry_id: str = None,
        dict_match_status: str = None,
        match_confidence: float = None,
        llm_confidence: float = None
    ) -> int:
        """컬럼 시맨틱 정보 업데이트"""
        conn, cursor = self._get_cursor()
        now = datetime.now()
        
        try:
            cursor.execute("""
                UPDATE column_metadata
                SET semantic_name = COALESCE(%s, semantic_name),
                    unit = COALESCE(%s, unit),
                    description = COALESCE(%s, description),
                    concept_category = COALESCE(%s, concept_category),
                    dict_entry_id = COALESCE(%s, dict_entry_id),
                    dict_match_status = COALESCE(%s, dict_match_status),
                    match_confidence = COALESCE(%s, match_confidence),
                    llm_confidence = COALESCE(%s, llm_confidence),
                    llm_analyzed_at = %s
                WHERE file_id = %s AND original_name = %s
            """, (
                semantic_name, unit, description, concept_category,
                dict_entry_id, dict_match_status, match_confidence,
                llm_confidence, now, file_id, original_name
            ))
            
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            print(f"[ColumnRepository] Error updating semantic info: {e}")
            return 0
    
    def batch_update_semantic_info(
        self,
        file_id: str,
        updates: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        여러 컬럼의 시맨틱 정보 일괄 업데이트
        
        Args:
            file_id: 파일 ID
            updates: [
                {
                    "original_name": str,
                    "semantic_name": str,
                    "unit": str,
                    "description": str,
                    "concept_category": str,
                    "dict_entry_id": str,
                    "dict_match_status": str,
                    "match_confidence": float
                }
            ]
        
        Returns:
            {"matched": n, "not_found": n, "null_from_llm": n}
        """
        conn, cursor = self._get_cursor()
        now = datetime.now()
        
        stats = {"matched": 0, "not_found": 0, "null_from_llm": 0}
        
        try:
            for update in updates:
                # status 집계
                status = update.get('dict_match_status', 'null_from_llm')
                stats[status] = stats.get(status, 0) + 1
                
                cursor.execute("""
                    UPDATE column_metadata
                    SET semantic_name = %s,
                        unit = %s,
                        description = %s,
                        concept_category = %s,
                        dict_entry_id = %s,
                        dict_match_status = %s,
                        match_confidence = %s,
                        llm_confidence = %s,
                        llm_analyzed_at = %s
                    WHERE file_id = %s AND original_name = %s
                """, (
                    update.get('semantic_name'),
                    update.get('unit'),
                    update.get('description'),
                    update.get('concept_category'),
                    update.get('dict_entry_id'),
                    update.get('dict_match_status'),
                    update.get('match_confidence'),
                    update.get('match_confidence'),  # llm_confidence도 동일하게
                    now,
                    file_id,
                    update.get('original_name')
                ))
            
            conn.commit()
            return stats
        except Exception as e:
            conn.rollback()
            print(f"[ColumnRepository] Error batch updating: {e}")
            raise
    
    def _row_to_column_dict(self, row: tuple) -> Dict[str, Any]:
        """DB row를 dict로 변환"""
        (col_id, name, sem_name, unit, desc, concept, dtype, col_type,
         col_info, val_dist, dict_id, match_status, match_conf) = row
        
        return {
            "col_id": col_id,
            "original_name": name,
            "semantic_name": sem_name,
            "unit": unit,
            "description": desc,
            "concept_category": concept,
            "data_type": dtype,
            "column_type": col_type,
            "column_info": self._parse_json_field(col_info),
            "value_distribution": self._parse_json_field(val_dist),
            "dict_entry_id": str(dict_id) if dict_id else None,
            "dict_match_status": match_status,
            "match_confidence": match_conf
        }

