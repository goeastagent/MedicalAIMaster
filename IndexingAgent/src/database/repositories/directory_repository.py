# src/database/repositories/directory_repository.py
"""
DirectoryRepository - directory_catalog 테이블 관련 조회/저장

directory_catalog 테이블:
- dir_id, dir_path, dir_name, file_count
- file_extensions (JSONB), filename_samples (JSONB)
- dir_type, filename_pattern, filename_columns
"""

from typing import Dict, Any, List, Optional
from .base import BaseRepository


class DirectoryRepository(BaseRepository):
    """
    directory_catalog 테이블 조회/저장 Repository
    
    [700] directory_pattern 노드에서 사용:
    - get_directories_for_analysis(): 패턴 분석 대상 디렉토리 조회
    - update_pattern_info(): 패턴 분석 결과 저장
    """
    
    def get_directories_for_analysis(
        self,
        min_files: int = 3
    ) -> List[Dict[str, Any]]:
        """
        패턴 분석 대상 디렉토리 조회
        
        [700] directory_pattern 노드의 _get_directories_for_analysis()에서 사용
        - filename_pattern이 NULL인 디렉토리만 (아직 분석 안 됨)
        - min_files 이상의 파일이 있는 디렉토리만
        
        Args:
            min_files: 최소 파일 수 (기본 3)
        
        Returns:
            [
                {
                    "dir_id": str,
                    "dir_path": str,
                    "dir_name": str,
                    "file_count": int,
                    "file_extensions": dict,
                    "filename_samples": list,
                    "dir_type": str
                }
            ]
        """
        rows = self._execute_query("""
            SELECT dir_id, dir_path, dir_name, file_count, 
                   file_extensions, filename_samples, dir_type
            FROM directory_catalog
            WHERE file_count >= %s
              AND filename_pattern IS NULL
            ORDER BY file_count DESC
        """, (min_files,), fetch="all")
        
        directories = []
        for row in rows:
            dir_id, dir_path, dir_name, file_count, file_ext, samples, dir_type = row
            
            directories.append({
                "dir_id": str(dir_id),
                "dir_path": dir_path,
                "dir_name": dir_name,
                "file_count": file_count,
                "file_extensions": self._parse_json_field(file_ext),
                "filename_samples": samples if samples else [],
                "dir_type": dir_type
            })
        
        return directories
    
    def get_directory_by_id(self, dir_id: str) -> Optional[Dict[str, Any]]:
        """dir_id로 단일 디렉토리 조회"""
        row = self._execute_query("""
            SELECT dir_id, dir_path, dir_name, file_count, 
                   file_extensions, filename_samples, dir_type,
                   filename_pattern, filename_columns
            FROM directory_catalog
            WHERE dir_id = %s
        """, (dir_id,), fetch="one")
        
        if not row:
            return None
        
        return self._row_to_dict(row)
    
    def get_directory_by_path(self, dir_path: str) -> Optional[Dict[str, Any]]:
        """dir_path로 단일 디렉토리 조회"""
        row = self._execute_query("""
            SELECT dir_id, dir_path, dir_name, file_count, 
                   file_extensions, filename_samples, dir_type,
                   filename_pattern, filename_columns
            FROM directory_catalog
            WHERE dir_path = %s
        """, (dir_path,), fetch="one")
        
        if not row:
            return None
        
        return self._row_to_dict(row)
    
    def get_directory_by_name(self, dir_name: str) -> Optional[Dict[str, Any]]:
        """dir_name으로 단일 디렉토리 조회"""
        row = self._execute_query("""
            SELECT dir_id, dir_path, dir_name, file_count, 
                   file_extensions, filename_samples, dir_type,
                   filename_pattern, filename_columns
            FROM directory_catalog
            WHERE dir_name = %s
        """, (dir_name,), fetch="one")
        
        if not row:
            return None
        
        return self._row_to_dict(row)
    
    def get_directory_by_id(self, dir_id: str) -> Optional[Dict[str, Any]]:
        """dir_id로 단일 디렉토리 조회"""
        row = self._execute_query("""
            SELECT dir_id, dir_path, dir_name, file_count, 
                   file_extensions, filename_samples, dir_type,
                   filename_pattern, filename_columns
            FROM directory_catalog
            WHERE dir_id = %s
        """, (dir_id,), fetch="one")
        
        if not row:
            return None
        
        return self._row_to_dict(row)
    
    def get_all_directories(self) -> List[Dict[str, Any]]:
        """모든 디렉토리 조회"""
        rows = self._execute_query("""
            SELECT dir_id, dir_path, dir_name, file_count, 
                   file_extensions, filename_samples, dir_type,
                   filename_pattern, filename_columns
            FROM directory_catalog
            ORDER BY dir_path
        """, fetch="all")
        
        return [self._row_to_dict(row) for row in rows]
    
    def get_directories_with_files(self, min_files: int = 1) -> List[Dict[str, Any]]:
        """
        파일이 있는 디렉토리 조회 (실제 file_catalog 기준)
        
        [250] file_grouping_prep 노드에서 사용
        
        Args:
            min_files: 최소 파일 수 (기본 1)
        
        Returns:
            디렉토리 정보 리스트 (실제 파일 수 포함)
        """
        rows = self._execute_query("""
            SELECT 
                dc.dir_id,
                dc.dir_path,
                dc.dir_name,
                dc.file_count,
                dc.file_extensions,
                dc.filename_samples,
                COUNT(fc.file_id) as actual_file_count
            FROM directory_catalog dc
            LEFT JOIN file_catalog fc ON dc.dir_id = fc.dir_id
            GROUP BY dc.dir_id, dc.dir_path, dc.dir_name, dc.file_count, 
                     dc.file_extensions, dc.filename_samples
            HAVING COUNT(fc.file_id) >= %s
            ORDER BY COUNT(fc.file_id) DESC
        """, (min_files,), fetch="all")
        
        return [
            {
                "dir_id": str(row[0]),
                "dir_path": row[1],
                "dir_name": row[2],
                "file_count": row[3],
                "file_extensions": self._parse_json_field(row[4]),
                "filename_samples": row[5] if row[5] else [],
                "actual_file_count": row[6]
            }
            for row in rows
        ]
    
    def update_pattern_info(
        self,
        dir_id: str,
        filename_pattern: str = None,
        filename_columns: List[Dict[str, Any]] = None
    ) -> int:
        """
        디렉토리 패턴 분석 결과 저장
        
        Args:
            dir_id: 디렉토리 ID
            filename_pattern: 파일명 패턴 (예: "{caseid}.{extension}")
            filename_columns: 추출된 컬럼 정보
        
        Returns:
            업데이트된 행 수
        """
        import json
        
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute("""
                UPDATE directory_catalog
                SET filename_pattern = %s,
                    filename_columns = %s
                WHERE dir_id = %s
            """, (
                filename_pattern,
                json.dumps(filename_columns) if filename_columns else None,
                dir_id
            ))
            
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            print(f"[DirectoryRepository] Error updating pattern: {e}")
            return 0
    
    def get_directory_count(self) -> int:
        """전체 디렉토리 수 조회"""
        row = self._execute_query(
            "SELECT COUNT(*) FROM directory_catalog",
            fetch="one"
        )
        return row[0] if row else 0
    
    def _row_to_dict(self, row: tuple) -> Dict[str, Any]:
        """DB row를 dict로 변환"""
        (dir_id, dir_path, dir_name, file_count, file_ext, 
         samples, dir_type, pattern, columns) = row
        
        return {
            "dir_id": str(dir_id),
            "dir_path": dir_path,
            "dir_name": dir_name,
            "file_count": file_count,
            "file_extensions": self._parse_json_field(file_ext),
            "filename_samples": samples if samples else [],
            "dir_type": dir_type,
            "filename_pattern": pattern,
            "filename_columns": self._parse_json_field(columns)
        }
    
    # =========================================================================
    # [700] Directory Pattern Analysis 지원 메서드
    # =========================================================================
    
    def get_data_dictionary_for_pattern(self) -> Dict[str, Any]:
        """
        패턴 분석을 위한 Data Dictionary 수집
        
        file_catalog, column_metadata, parameter 테이블을 조인하여
        LLM 패턴 분석에 필요한 데이터 사전 정보를 수집합니다.
        
        Returns:
            {
                "table_name": {
                    "columns": [{"name": str, "type": str, "description": str, "examples": list}]
                }
            }
        """
        rows = self._execute_query("""
            SELECT 
                fc.file_name,
                cm.original_name,
                p.semantic_name,
                p.description,
                cm.value_distribution
            FROM file_catalog fc
            JOIN column_metadata cm ON fc.file_id = cm.file_id
            LEFT JOIN parameter p ON cm.col_id = p.source_column_id 
                                  AND cm.file_id = p.file_id
            WHERE fc.is_metadata = FALSE
              AND (p.description IS NOT NULL OR p.semantic_name IS NOT NULL)
            ORDER BY fc.file_name, cm.col_id
        """, fetch="all")
        
        tables = {}
        for row in rows:
            file_name = row[0]
            if file_name not in tables:
                tables[file_name] = {
                    "columns": []
                }
            
            value_dist = row[4] if row[4] else {}
            examples = value_dist.get('samples', []) if isinstance(value_dist, dict) else []
            
            tables[file_name]["columns"].append({
                "name": row[1],
                "type": row[2],
                "description": row[3],
                "examples": examples
            })
        
        return tables
    
    def get_data_dictionary_simple(self) -> Dict[str, Any]:
        """
        간단한 Data Dictionary (이전 단계 결과 없을 때 사용)
        
        data_dictionary 테이블과 column_metadata에서 ID 관련 컬럼 수집
        
        Returns:
            {
                "dictionary_entries": {key: {"description": str, "unit": str, "source": str}},
                "id_columns_by_file": {file_name: [{"name": str, "type": str, "examples": list}]}
            }
        """
        dict_entries = {}
        
        # data_dictionary 테이블 조회
        try:
            rows = self._execute_query("""
                SELECT 
                    parameter_key,
                    parameter_desc,
                    parameter_unit,
                    source_file_name
                FROM data_dictionary
                ORDER BY parameter_key
            """, fetch="all")
            
            for row in rows:
                key = row[0]
                if key not in dict_entries:
                    dict_entries[key] = {
                        "description": row[1],
                        "unit": row[2],
                        "source": row[3]
                    }
        except Exception:
            pass  # 테이블 없으면 무시
        
        # ID 관련 컬럼 수집
        id_rows = self._execute_query("""
            SELECT DISTINCT
                fc.file_name,
                cm.original_name,
                cm.data_type,
                cm.value_distribution
            FROM file_catalog fc
            JOIN column_metadata cm ON fc.file_id = cm.file_id
            WHERE fc.is_metadata = FALSE
              AND (
                  LOWER(cm.original_name) LIKE '%%id%%' 
                  OR LOWER(cm.original_name) LIKE '%%case%%'
                  OR LOWER(cm.original_name) LIKE '%%subject%%'
              )
            ORDER BY fc.file_name
        """, fetch="all")
        
        id_columns = {}
        for row in id_rows:
            file_name = row[0]
            if file_name not in id_columns:
                id_columns[file_name] = []
            
            value_dist = row[3] if row[3] else {}
            examples = value_dist.get('samples', []) if isinstance(value_dist, dict) else []
            
            id_columns[file_name].append({
                "name": row[1],
                "type": row[2],
                "examples": examples
            })
        
        return {
            "dictionary_entries": dict_entries,
            "id_columns_by_file": id_columns
        }
    
    def save_pattern_results(self, results: List[Dict[str, Any]]) -> int:
        """
        패턴 분석 결과 일괄 저장
        
        Args:
            results: [
                {
                    "dir_id": str,
                    "pattern": str,
                    "columns": list,
                    "confidence": float,
                    "reasoning": str
                }
            ]
        
        Returns:
            저장된 결과 수
        """
        import json
        
        conn, cursor = self._get_cursor()
        saved_count = 0
        
        try:
            for r in results:
                cursor.execute("""
                    UPDATE directory_catalog
                    SET filename_pattern = %s,
                        filename_columns = %s,
                        pattern_confidence = %s,
                        pattern_reasoning = %s,
                        pattern_analyzed_at = NOW()
                    WHERE dir_id = %s
                """, (
                    r.get("pattern"),
                    json.dumps(r.get("columns", [])),
                    r.get("confidence"),
                    r.get("reasoning"),
                    r["dir_id"]
                ))
                saved_count += 1
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[DirectoryRepository] Error saving pattern results: {e}")
        
        return saved_count
    
    def get_filename_column_mappings(self) -> Dict[str, Dict[str, Any]]:
        """
        패턴 분석된 디렉토리의 filename_columns 매핑 정보 조회
        
        [750] RelationshipInferenceNode의 _load_filename_column_mappings()에서 사용
        
        Returns:
            {
                "dir_name": {
                    "column_name": {
                        "type": str,
                        "matched_column": str,
                        "match_confidence": float,
                        "match_reasoning": str
                    }
                }
            }
        """
        import json
        
        rows = self._execute_query("""
            SELECT dir_name, filename_columns
            FROM directory_catalog
            WHERE filename_columns IS NOT NULL
        """, fetch="all")
        
        mappings = {}
        for row in rows:
            dir_name, filename_columns = row
            if filename_columns:
                # JSON 파싱
                if isinstance(filename_columns, str):
                    filename_columns = json.loads(filename_columns)
                
                col_map = {}
                for col_info in filename_columns:
                    col_name = col_info.get('name')
                    if col_name:
                        col_map[col_name] = {
                            "type": col_info.get('type'),
                            "matched_column": col_info.get('matched_column'),
                            "match_confidence": col_info.get('match_confidence', 0.0),
                            "match_reasoning": col_info.get('match_reasoning', '')
                        }
                
                if col_map:
                    mappings[dir_name] = col_map
        
        return mappings

