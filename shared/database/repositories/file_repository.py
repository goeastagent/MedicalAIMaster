# src/database/repositories/file_repository.py
"""
FileRepository - file_catalog 테이블 관련 조회

file_catalog 테이블:
- file_id, file_name, file_path, processor_type
- file_metadata (JSONB), raw_stats (JSONB)
- is_metadata, llm_confidence, llm_analyzed_at
- filename_values (JSONB)
"""

from typing import Dict, Any, List, Optional
from .base import BaseRepository


class FileRepository(BaseRepository):
    """
    file_catalog 테이블 조회 Repository
    
    주요 메서드:
    - get_file_by_id(): 단일 파일 조회
    - get_file_by_path(): 경로로 파일 조회
    - get_files_by_ids(): 여러 파일 조회
    - get_files_with_classification_info(): 분류용 파일 정보
    - get_metadata_files(): is_metadata=true 파일들
    - get_data_files(): is_metadata=false 파일들
    """
    
    def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """
        file_id로 단일 파일 조회
        
        Returns:
            {
                "file_id": str,
                "file_name": str,
                "file_path": str,
                "processor_type": str,
                "file_metadata": dict,
                "raw_stats": dict,
                "is_metadata": bool,
                "filename_values": dict
            }
        """
        row = self._execute_query("""
            SELECT file_id, file_name, file_path, processor_type,
                   file_metadata, raw_stats, is_metadata, filename_values
            FROM file_catalog
            WHERE file_id = %s
        """, (file_id,), fetch="one")
        
        if not row:
            return None
        
        return self._row_to_file_dict(row)
    
    def get_file_by_path(self, file_path: str) -> Optional[Dict[str, Any]]:
        """file_path로 단일 파일 조회"""
        row = self._execute_query("""
            SELECT file_id, file_name, file_path, processor_type,
                   file_metadata, raw_stats, is_metadata, filename_values
            FROM file_catalog
            WHERE file_path = %s
        """, (file_path,), fetch="one")
        
        if not row:
            # file_name으로도 시도
            file_name = file_path.split('/')[-1]
            row = self._execute_query("""
                SELECT file_id, file_name, file_path, processor_type,
                       file_metadata, raw_stats, is_metadata, filename_values
                FROM file_catalog
                WHERE file_name = %s
            """, (file_name,), fetch="one")
        
        if not row:
            return None
        
        return self._row_to_file_dict(row)
    
    def get_files_by_ids(self, file_ids: List[str]) -> List[Dict[str, Any]]:
        """여러 file_id로 파일들 조회"""
        if not file_ids:
            return []
        
        placeholders = ','.join(['%s'] * len(file_ids))
        rows = self._execute_query(f"""
            SELECT file_id, file_name, file_path, processor_type,
                   file_metadata, raw_stats, is_metadata, filename_values
            FROM file_catalog
            WHERE file_id IN ({placeholders})
            ORDER BY file_name
        """, tuple(file_ids), fetch="all")
        
        return [self._row_to_file_dict(row) for row in rows]
    
    def get_files_by_paths(self, file_paths: List[str]) -> List[Dict[str, Any]]:
        """여러 file_path로 파일들 조회"""
        if not file_paths:
            return []
        
        placeholders = ','.join(['%s'] * len(file_paths))
        rows = self._execute_query(f"""
            SELECT file_id, file_name, file_path, processor_type,
                   file_metadata, raw_stats, is_metadata, filename_values
            FROM file_catalog
            WHERE file_path IN ({placeholders})
            ORDER BY file_name
        """, tuple(file_paths), fetch="all")
        
        return [self._row_to_file_dict(row) for row in rows]
    
    def get_files_with_classification_info(
        self, 
        file_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """
        분류용 파일 정보 조회 (컬럼 정보 포함)
        
        file_classification node에서 사용: file_catalog + column_metadata 조인
        
        Returns:
            [
                {
                    "file_id": str,
                    "file_name": str,
                    "file_path": str,
                    "row_count": int,
                    "column_count": int,
                    "columns": [
                        {
                            "name": str,
                            "dtype": str,
                            "column_type": str,
                            "unique_values": list,
                            "n_unique": int
                        }
                    ]
                }
            ]
        """
        if not file_ids:
            return []
        
        from .column_repository import ColumnRepository
        col_repo = ColumnRepository(self.db)
        
        files = self.get_files_by_ids(file_ids)
        
        result = []
        for f in files:
            file_id = f['file_id']
            metadata = f.get('file_metadata', {})
            
            # 컬럼 정보 조회
            columns = col_repo.get_columns_for_classification(file_id)
            
            result.append({
                "file_id": file_id,
                "file_name": f['file_name'],
                "file_path": f['file_path'],
                "row_count": metadata.get('row_count', 0),
                "column_count": metadata.get('column_count', 0) or len(columns),
                "columns": columns
            })
        
        return result
    
    def get_metadata_files(self) -> List[str]:
        """is_metadata=true인 파일 경로 목록 조회"""
        rows = self._execute_query("""
            SELECT file_path FROM file_catalog 
            WHERE is_metadata = true 
            ORDER BY file_name
        """, fetch="all")
        
        return [row[0] for row in rows]
    
    def get_data_files(self) -> List[str]:
        """is_metadata=false인 파일 경로 목록 조회"""
        rows = self._execute_query("""
            SELECT file_path FROM file_catalog 
            WHERE is_metadata = false 
            ORDER BY file_name
        """, fetch="all")
        
        return [row[0] for row in rows]
    
    def get_ungrouped_data_files(self) -> List[str]:
        """
        그룹에 속하지 않은 data 파일 경로 목록 조회
        
        [420] column_classification 노드에서 사용
        - is_metadata = false
        - group_id IS NULL
        
        Returns:
            파일 경로 리스트
        """
        rows = self._execute_query("""
            SELECT file_path FROM file_catalog 
            WHERE is_metadata = false 
              AND group_id IS NULL
            ORDER BY file_name
        """, fetch="all")
        
        return [row[0] for row in rows]
    
    def get_data_files_with_details(self) -> List[Dict[str, Any]]:
        """
        [R5] is_metadata=false인 파일들의 상세 정보 조회
        
        [800] ontology_enhancement 노드의 _load_tables_with_columns()에서 사용
        [700] relationship_inference 노드의 _load_tables_with_columns()에서 사용
        [500] entity_identification 노드의 _load_data_files_with_columns()에서 사용
        
        Returns:
            [
                {
                    "file_id": str,
                    "file_name": str,
                    "file_path": str
                }
            ]
        """
        rows = self._execute_query("""
            SELECT file_id, file_name, file_path
            FROM file_catalog
            WHERE is_metadata = false
            ORDER BY file_name
        """, fetch="all")
        
        return [
            {
                "file_id": str(r[0]),
                "file_name": r[1],
                "file_path": r[2]
            }
            for r in rows
        ]
    
    def get_all_file_ids(self) -> List[str]:
        """모든 file_id 조회"""
        rows = self._execute_query("""
            SELECT file_id FROM file_catalog ORDER BY file_name
        """, fetch="all")
        
        return [str(row[0]) for row in rows]
    
    # =========================================================================
    # [Phase 1] Skip Already Analyzed - 스킵 로직 지원 메서드
    # =========================================================================
    
    def get_files_without_classification(
        self, 
        file_ids: List[str]
    ) -> List[str]:
        """
        주어진 file_ids 중 아직 분류되지 않은 (llm_analyzed_at IS NULL) 파일만 반환
        
        [400] file_classification 노드에서 사용
        
        Args:
            file_ids: 체크할 파일 ID 목록
        
        Returns:
            분류되지 않은 file_id 목록
        """
        if not file_ids:
            return []
        
        placeholders = ','.join(['%s'] * len(file_ids))
        rows = self._execute_query(f"""
            SELECT file_id FROM file_catalog
            WHERE file_id IN ({placeholders})
              AND llm_analyzed_at IS NULL
            ORDER BY file_name
        """, tuple(file_ids), fetch="all")
        
        return [str(row[0]) for row in rows]
    
    def get_already_classified_count(self, file_ids: List[str]) -> int:
        """
        이미 분류된 파일 수 조회 (스킵 로그용)
        
        Args:
            file_ids: 체크할 파일 ID 목록
            
        Returns:
            llm_analyzed_at IS NOT NULL인 파일 수
        """
        if not file_ids:
            return 0
        
        placeholders = ','.join(['%s'] * len(file_ids))
        row = self._execute_query(f"""
            SELECT COUNT(*) FROM file_catalog
            WHERE file_id IN ({placeholders})
              AND llm_analyzed_at IS NOT NULL
        """, tuple(file_ids), fetch="one")
        
        return row[0] if row else 0
    
    def get_files_by_dir_id(self, dir_id: str) -> List[Dict[str, Any]]:
        """
        특정 디렉토리의 파일 목록 조회
        
        [250] file_grouping_prep 노드에서 사용
        
        Args:
            dir_id: 디렉토리 ID
        
        Returns:
            파일 정보 리스트
        """
        rows = self._execute_query("""
            SELECT file_id, file_name, file_extension, 
                   file_size_bytes, filename_values, group_id
            FROM file_catalog
            WHERE dir_id = %s
            ORDER BY file_name
        """, (dir_id,), fetch="all")
        
        return [
            {
                "file_id": str(row[0]),
                "file_name": row[1],
                "file_extension": row[2],
                "file_size_bytes": row[3],
                "filename_values": self._parse_json_field(row[4]),
                "group_id": str(row[5]) if row[5] else None
            }
            for row in rows
        ]
    
    def get_file_count(self) -> int:
        """전체 파일 수 조회"""
        row = self._execute_query("""
            SELECT COUNT(*) FROM file_catalog
        """, fetch="one")
        
        return row[0] if row else 0
    
    def update_is_metadata(
        self, 
        file_name: str, 
        is_metadata: bool, 
        confidence: float
    ) -> int:
        """is_metadata 필드 업데이트"""
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute("""
                UPDATE file_catalog
                SET is_metadata = %s, llm_confidence = %s, llm_analyzed_at = NOW()
                WHERE file_name = %s
            """, (is_metadata, confidence, file_name))
            
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            print(f"[FileRepository] Error updating is_metadata: {e}")
            return 0
    
    def _row_to_file_dict(self, row: tuple) -> Dict[str, Any]:
        """DB row를 dict로 변환"""
        (file_id, file_name, file_path, processor_type,
         file_metadata, raw_stats, is_metadata, filename_values) = row
        
        return {
            "file_id": str(file_id),
            "file_name": file_name,
            "file_path": file_path,
            "processor_type": processor_type,
            "file_metadata": self._parse_json_field(file_metadata),
            "raw_stats": self._parse_json_field(raw_stats),
            "is_metadata": is_metadata,
            "filename_values": self._parse_json_field(filename_values)
        }
    
    # =========================================================================
    # [700] Directory Pattern Analysis 지원 메서드
    # =========================================================================
    
    def update_filename_values_by_pattern(
        self,
        dir_id: str,
        pattern_regex: str,
        columns: List[Dict[str, Any]]
    ) -> int:
        """
        패턴 regex를 사용하여 파일명에서 값 추출 후 filename_values 업데이트
        
        PostgreSQL substring() 함수를 사용하여 첫 번째 캡처 그룹 추출
        
        Args:
            dir_id: 디렉토리 ID
            pattern_regex: PostgreSQL regex 패턴 (캡처 그룹 포함)
            columns: [{"name": str, "type": str}] 추출할 컬럼 정보
        
        Returns:
            업데이트된 총 파일 수
        """
        conn, cursor = self._get_cursor()
        updated_total = 0
        
        try:
            for col in columns:
                col_name = col.get("name")
                if not col_name:
                    continue
                
                col_type = col.get("type", "text")
                
                if col_type == "integer":
                    # 정수형 캐스팅
                    cursor.execute("""
                        UPDATE file_catalog
                        SET filename_values = CASE 
                            WHEN file_name ~ %s THEN
                                COALESCE(filename_values, '{}'::jsonb) || 
                                jsonb_build_object(%s, substring(file_name from %s)::integer)
                            ELSE filename_values
                        END
                        WHERE dir_id = %s
                          AND file_name ~ %s
                    """, (
                        pattern_regex,
                        col_name,
                        pattern_regex,
                        dir_id,
                        pattern_regex
                    ))
                else:
                    # 텍스트형
                    cursor.execute("""
                        UPDATE file_catalog
                        SET filename_values = CASE 
                            WHEN file_name ~ %s THEN
                                COALESCE(filename_values, '{}'::jsonb) || 
                                jsonb_build_object(%s, substring(file_name from %s))
                            ELSE filename_values
                        END
                        WHERE dir_id = %s
                          AND file_name ~ %s
                    """, (
                        pattern_regex,
                        col_name,
                        pattern_regex,
                        dir_id,
                        pattern_regex
                    ))
                
                updated_total += cursor.rowcount
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[FileRepository] Error updating filename_values: {e}")
        
        return updated_total
    
    def update_filename_values_by_group_pattern(
        self,
        group_id: str,
        pattern_regex: str,
        columns: List[Dict[str, Any]]
    ) -> int:
        """
        그룹 내 모든 파일에 패턴을 적용하여 filename_values 업데이트
        
        Args:
            group_id: 파일 그룹 ID
            pattern_regex: 파일명 추출 정규식 (PostgreSQL regex)
            columns: 추출할 컬럼 정보
                [{"name": "caseid", "position": 1, "type": "integer"}, ...]
        
        Returns:
            업데이트된 총 파일 수
        """
        conn, cursor = self._get_cursor()
        updated_total = 0
        
        try:
            for col in columns:
                col_name = col.get("name")
                position = col.get("position", 1)
                if not col_name:
                    continue
                
                col_type = col.get("type", "text")
                
                # PostgreSQL의 regexp_match 사용하여 특정 그룹 추출
                # position은 1-indexed이지만 배열 인덱싱은 1-indexed임
                if col_type == "integer":
                    cursor.execute("""
                        UPDATE file_catalog
                        SET filename_values = CASE 
                            WHEN file_name ~ %s THEN
                                COALESCE(filename_values, '{}'::jsonb) || 
                                jsonb_build_object(%s, (regexp_match(file_name, %s))[%s]::integer)
                            ELSE filename_values
                        END
                        WHERE group_id = %s
                          AND file_name ~ %s
                    """, (
                        pattern_regex,
                        col_name,
                        pattern_regex,
                        position,
                        group_id,
                        pattern_regex
                    ))
                else:
                    cursor.execute("""
                        UPDATE file_catalog
                        SET filename_values = CASE 
                            WHEN file_name ~ %s THEN
                                COALESCE(filename_values, '{}'::jsonb) || 
                                jsonb_build_object(%s, (regexp_match(file_name, %s))[%s])
                            ELSE filename_values
                        END
                        WHERE group_id = %s
                          AND file_name ~ %s
                    """, (
                        pattern_regex,
                        col_name,
                        pattern_regex,
                        position,
                        group_id,
                        pattern_regex
                    ))
                
                updated_total += cursor.rowcount
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[FileRepository] Error updating filename_values by group: {e}")
        
        return updated_total

