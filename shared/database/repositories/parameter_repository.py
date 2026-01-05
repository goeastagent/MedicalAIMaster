# src/database/repositories/parameter_repository.py
"""
ParameterRepository - parameter 테이블 관련 CRUD

parameter 테이블:
- param_id, file_id, param_key, source_type, source_column_id
- semantic_name, unit, concept_category, description (LLM 분석 결과)
- dict_entry_id, dict_match_status, match_confidence (Dictionary 매칭)
- is_identifier, llm_confidence, llm_reasoning
"""

from typing import Dict, Any, List, Optional
from .base import BaseRepository
from shared.models import DictMatchStatus


class ParameterRepository(BaseRepository):
    """
    parameter 테이블 CRUD Repository
    
    주요 메서드:
    - create_parameter(): 단일 파라미터 생성
    - create_parameters_batch(): 배치 생성 ([420] column_classification에서 사용)
    - get_parameters_by_file(): 파일별 파라미터 조회
    - get_parameters_for_semantic(): semantic 분석 대기 파라미터 조회 ([600]에서 사용)
    - update_semantic_info(): semantic 정보 업데이트 ([600]에서 사용)
    """
    
    # =========================================================================
    # CREATE
    # =========================================================================
    
    def create_parameter(
        self,
        file_id: str,
        param_key: str,
        source_type: str,
        source_column_id: int = None,
        is_identifier: bool = False
    ) -> Optional[int]:
        """
        단일 파라미터 생성
        
        Args:
            file_id: 파일 ID
            param_key: 파라미터 키 ("HR", "SpO2" 등)
            source_type: 출처 타입 ('column_name' | 'column_value')
            source_column_id: 출처 컬럼 ID
            is_identifier: 식별자 여부
        
        Returns:
            생성된 param_id 또는 None
        """
        conn, cursor = self._get_cursor()
        
        try:
            # Partial unique index 사용 시 WHERE 절 필요
            cursor.execute("""
                INSERT INTO parameter (
                    file_id, param_key, source_type, source_column_id,
                    is_identifier
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (file_id, param_key, source_type) WHERE file_id IS NOT NULL
                DO UPDATE SET
                    source_column_id = EXCLUDED.source_column_id,
                    is_identifier = EXCLUDED.is_identifier,
                    updated_at = NOW()
                RETURNING param_id
            """, (
                file_id,
                param_key,
                source_type,
                source_column_id,
                is_identifier
            ))
            
            result = cursor.fetchone()
            conn.commit()
            return result[0] if result else None
            
        except Exception as e:
            conn.rollback()
            print(f"[ParameterRepository] Error creating parameter: {e}")
            return None
    
    def create_parameters_batch(
        self,
        file_id: str,
        parameters: List[Dict[str, Any]]
    ) -> int:
        """
        여러 파라미터 배치 생성
        
        [420] column_classification 노드에서 사용:
        - Wide-format: column_role='parameter_name'인 컬럼명들
        - Long-format: column_role='parameter_container'인 컬럼의 unique values
        
        Args:
            file_id: 파일 ID
            parameters: [
                {
                    "param_key": str,
                    "source_type": str,  # 'column_name' | 'column_value'
                    "source_column_id": int (optional),
                    "is_identifier": bool (optional)
                }
            ]
        
        Returns:
            생성된 파라미터 수
        """
        if not parameters:
            return 0
        
        conn, cursor = self._get_cursor()
        created = 0
        
        try:
            for param in parameters:
                # Partial unique index 사용 시 WHERE 절 필요
                cursor.execute("""
                    INSERT INTO parameter (
                        file_id, param_key, source_type, source_column_id,
                        is_identifier
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (file_id, param_key, source_type) WHERE file_id IS NOT NULL
                    DO UPDATE SET
                        source_column_id = EXCLUDED.source_column_id,
                        is_identifier = EXCLUDED.is_identifier,
                        updated_at = NOW()
                """, (
                    file_id,
                    param.get('param_key'),
                    param.get('source_type'),
                    param.get('source_column_id'),
                    param.get('is_identifier', False)
                ))
                created += 1
            
            conn.commit()
            return created
            
        except Exception as e:
            conn.rollback()
            print(f"[ParameterRepository] Error batch creating: {e}")
            raise
    
    # =========================================================================
    # READ
    # =========================================================================
    
    def get_parameters_by_file(self, file_id: str) -> List[Dict[str, Any]]:
        """
        파일의 모든 파라미터 조회
        
        Returns:
            [
                {
                    "param_id": int,
                    "param_key": str,
                    "source_type": str,
                    "source_column_id": int,
                    "semantic_name": str,
                    "unit": str,
                    "concept_category": str,
                    "is_identifier": bool,
                    ...
                }
            ]
        """
        rows = self._execute_query("""
            SELECT param_id, param_key, source_type, source_column_id,
                   semantic_name, unit, concept_category, description,
                   dict_entry_id, dict_match_status, match_confidence,
                   is_identifier, llm_confidence, llm_reasoning
            FROM parameter
            WHERE file_id = %s
            ORDER BY param_id
        """, (file_id,), fetch="all")
        
        return [self._row_to_param_dict(row) for row in rows]
    
    def get_parameters_for_semantic(
        self,
        file_id: str = None,
        limit: int = None
    ) -> List[Dict[str, Any]]:
        """
        Semantic 분석 대기 중인 파라미터 조회
        
        [600] parameter_semantic 노드에서 사용:
        - semantic_name이 NULL인 파라미터만 조회
        - identifier도 포함 (LLM이 concept_category='Identifiers' 할당)
        
        Args:
            file_id: 특정 파일만 조회 (None이면 전체)
            limit: 최대 조회 수
        
        Returns:
            파라미터 목록
        """
        query = """
            SELECT p.param_id, p.file_id, p.param_key, p.source_type,
                   p.source_column_id, p.is_identifier,
                   f.file_name, f.file_path
            FROM parameter p
            JOIN file_catalog f ON p.file_id = f.file_id
            WHERE p.semantic_name IS NULL
        """
        params = []
        
        if file_id:
            query += " AND p.file_id = %s"
            params.append(file_id)
        
        query += " ORDER BY p.file_id, p.param_id"
        
        if limit:
            query += f" LIMIT {limit}"
        
        rows = self._execute_query(query, tuple(params) if params else None, fetch="all")
        
        result = []
        for row in rows:
            (param_id, fid, param_key, source_type, source_col_id,
             is_id, file_name, file_path) = row
            
            result.append({
                "param_id": param_id,
                "file_id": str(fid),
                "param_key": param_key,
                "source_type": source_type,
                "source_column_id": source_col_id,
                "is_identifier": is_id,
                "file_name": file_name,
                "file_path": file_path
            })
        
        return result
    
    def get_parameters_without_semantic(
        self,
        file_ids: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Semantic 분석이 필요한 파라미터 조회 (여러 파일)
        
        [600] parameter_semantic 노드에서 사용:
        - semantic_name이 NULL인 파라미터만 조회
        - identifier도 포함 (LLM이 concept_category='Identifiers' 할당)
        
        Args:
            file_ids: 파일 ID 목록
        
        Returns:
            파라미터 목록
        """
        if not file_ids:
            return []
        
        placeholders = ','.join(['%s'] * len(file_ids))
        
        rows = self._execute_query(f"""
            SELECT p.param_id, p.file_id, p.param_key, p.source_type,
                   p.source_column_id, p.is_identifier,
                   f.file_name, f.file_path
            FROM parameter p
            JOIN file_catalog f ON p.file_id = f.file_id
            WHERE p.semantic_name IS NULL
              AND p.file_id IN ({placeholders})
            ORDER BY p.file_id, p.param_id
        """, tuple(file_ids), fetch="all")
        
        result = []
        for row in rows:
            (param_id, fid, param_key, source_type, source_col_id,
             is_id, file_name, file_path) = row
            
            result.append({
                "param_id": param_id,
                "file_id": str(fid),
                "param_key": param_key,
                "source_type": source_type,
                "source_column_id": source_col_id,
                "is_identifier": is_id,
                "file_name": file_name,
                "file_path": file_path
            })
        
        return result
    
    def get_group_parameters_without_semantic(self) -> List[Dict[str, Any]]:
        """
        Semantic 분석이 필요한 그룹 레벨 파라미터 조회
        
        [600] parameter_semantic 노드에서 사용:
        - file_id가 NULL이고 group_id가 있는 파라미터
        - semantic_name이 NULL인 것만
        
        Returns:
            그룹 레벨 파라미터 목록
        """
        rows = self._execute_query("""
            SELECT p.param_id, p.group_id, p.param_key, p.source_type,
                   p.source_column_id, p.is_identifier,
                   g.group_name
            FROM parameter p
            JOIN file_group g ON p.group_id = g.group_id
            WHERE p.file_id IS NULL
              AND p.group_id IS NOT NULL
              AND p.semantic_name IS NULL
            ORDER BY g.group_name, p.param_id
        """, fetch="all")
        
        result = []
        for row in (rows or []):
            (param_id, group_id, param_key, source_type, source_col_id,
             is_id, group_name) = row
            
            result.append({
                "param_id": param_id,
                "group_id": str(group_id) if group_id else None,
                "file_id": None,  # 그룹 레벨이므로 None
                "param_key": param_key,
                "source_type": source_type,
                "source_column_id": source_col_id,
                "is_identifier": is_id,
                "group_name": group_name,
                "file_name": group_name,  # LLM context용
                "file_path": f"[Group: {group_name}]"  # LLM context용
            })
        
        return result
    
    def get_parameter_count(self, file_id: str = None) -> int:
        """파라미터 수 조회"""
        if file_id:
            row = self._execute_query(
                "SELECT COUNT(*) FROM parameter WHERE file_id = %s",
                (file_id,), fetch="one"
            )
        else:
            row = self._execute_query(
                "SELECT COUNT(*) FROM parameter",
                fetch="one"
            )
        return row[0] if row else 0
    
    def get_parameters_by_category(
        self,
        concept_category: str
    ) -> List[Dict[str, Any]]:
        """특정 카테고리의 파라미터 조회"""
        rows = self._execute_query("""
            SELECT param_id, file_id, param_key, semantic_name, unit
            FROM parameter
            WHERE concept_category = %s
            ORDER BY param_key
        """, (concept_category,), fetch="all")
        
        return [
            {
                "param_id": r[0],
                "file_id": str(r[1]),
                "param_key": r[2],
                "semantic_name": r[3],
                "unit": r[4]
            }
            for r in rows
        ]
    
    def get_parameters_by_concept(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        [R1] ConceptCategory별 파라미터 그룹 조회
        
        [800] ontology_enhancement 노드의 _load_concept_parameters()에서 사용
        
        Returns:
            {
                "Vitals": [{"key": "hr", "name": "Heart Rate", "unit": "bpm"}, ...],
                "Laboratory": [{"key": "glucose", "name": "Glucose", "unit": "mg/dL"}, ...],
                ...
            }
        """
        rows = self._execute_query("""
            SELECT concept_category, param_key, semantic_name, unit
            FROM parameter
            WHERE concept_category IS NOT NULL
            ORDER BY concept_category, param_key
        """, fetch="all")
        
        concept_params: Dict[str, List[Dict[str, Any]]] = {}
        
        for concept, param_key, sem_name, unit in rows:
            if concept not in concept_params:
                concept_params[concept] = []
            
            concept_params[concept].append({
                "key": param_key,
                "name": sem_name or param_key,
                "unit": unit
            })
        
        return concept_params
    
    def get_all_parameters_for_ontology(self) -> List[Dict[str, Any]]:
        """
        [R2] Ontology용 전체 파라미터 조회 (중복 제거)
        
        [800] ontology_enhancement 노드의 _load_all_parameters()에서 사용
        [900] relationship_inference 노드의 Neo4j 동기화에서 사용
        - identifier 포함 (Neo4j Parameter 노드에 is_identifier 속성으로 표시)
        - param_key 기준 중복 제거
        
        Returns:
            [
                {"key": "hr", "name": "Heart Rate", "unit": "bpm", "concept": "Vitals", "is_identifier": False},
                {"key": "case_id", "name": "Case ID", "unit": None, "concept": "Identifiers", "is_identifier": True},
                ...
            ]
        """
        rows = self._execute_query("""
            SELECT DISTINCT ON (param_key) 
                   param_key, semantic_name, unit, concept_category, is_identifier
            FROM parameter
            ORDER BY param_key, param_id
        """, fetch="all")
        
        return [
            {
                "key": param_key,
                "name": sem_name or param_key,
                "unit": unit,
                "concept": concept,
                "is_identifier": is_id
            }
            for param_key, sem_name, unit, concept, is_id in rows
        ]
    
    def get_group_common_params_for_neo4j(self) -> List[Dict[str, Any]]:
        """
        [R3] Neo4j용 group_common 파라미터 조회
        
        [900] relationship_inference 노드에서 HAS_COMMON_PARAM 엣지 생성에 사용
        - source_type = 'group_common'인 파라미터만 조회
        - group_id가 있는 것만 (file_group에 속한 것)
        
        Returns:
            [
                {
                    "group_id": "uuid",
                    "group_name": "vital_files",
                    "param_key": "Solar8000/HR",
                    "concept_category": "Vital Signs"
                },
                ...
            ]
        """
        rows = self._execute_query("""
            SELECT 
                p.group_id,
                g.group_name,
                p.param_key,
                p.concept_category
            FROM parameter p
            JOIN file_group g ON p.group_id = g.group_id
            WHERE p.source_type = 'group_common'
              AND p.group_id IS NOT NULL
            ORDER BY g.group_name, p.param_key
        """, fetch="all")
        
        return [
            {
                "group_id": str(group_id),
                "group_name": group_name,
                "param_key": param_key,
                "concept_category": concept
            }
            for group_id, group_name, param_key, concept in (rows or [])
        ]
    
    # =========================================================================
    # UPDATE
    # =========================================================================
    
    def update_semantic_info(
        self,
        param_id: int,
        semantic_name: str = None,
        unit: str = None,
        concept_category: str = None,
        description: str = None,
        dict_entry_id: str = None,
        dict_match_status: str = None,
        match_confidence: float = None,
        llm_confidence: float = None,
        llm_reasoning: str = None
    ) -> int:
        """
        파라미터의 semantic 정보 업데이트
        
        [600] parameter_semantic 노드에서 사용
        
        Returns:
            업데이트된 행 수
        """
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute("""
                UPDATE parameter
                SET semantic_name = COALESCE(%s, semantic_name),
                    unit = COALESCE(%s, unit),
                    concept_category = COALESCE(%s, concept_category),
                    description = COALESCE(%s, description),
                    dict_entry_id = %s,
                    dict_match_status = COALESCE(%s, dict_match_status),
                    match_confidence = COALESCE(%s, match_confidence),
                    llm_confidence = COALESCE(%s, llm_confidence),
                    llm_reasoning = COALESCE(%s, llm_reasoning),
                    updated_at = NOW()
                WHERE param_id = %s
            """, (
                semantic_name, unit, concept_category, description,
                dict_entry_id, dict_match_status, match_confidence,
                llm_confidence, llm_reasoning, param_id
            ))
            
            conn.commit()
            return cursor.rowcount
            
        except Exception as e:
            conn.rollback()
            print(f"[ParameterRepository] Error updating semantic: {e}")
            return 0
    
    def batch_update_semantic_info(
        self,
        updates: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        여러 파라미터의 semantic 정보 일괄 업데이트
        
        Args:
            updates: [
                {
                    "param_id": int,
                    "semantic_name": str,
                    "unit": str,
                    "concept_category": str,
                    "description": str,
                    "dict_entry_id": str (optional),
                    "dict_match_status": str,
                    "match_confidence": float,
                    "llm_confidence": float,
                    "llm_reasoning": str
                }
            ]
        
        Returns:
            {"matched": n, "not_found": n, "null_from_llm": n, "total": n}
        """
        conn, cursor = self._get_cursor()
        
        stats = {
            DictMatchStatus.MATCHED.value: 0,
            DictMatchStatus.NOT_FOUND.value: 0,
            DictMatchStatus.NULL_FROM_LLM.value: 0,
            "total": 0
        }
        
        try:
            for update in updates:
                status = update.get('dict_match_status', DictMatchStatus.NULL_FROM_LLM.value)
                if status in stats:
                    stats[status] += 1
                stats["total"] += 1
                
                cursor.execute("""
                    UPDATE parameter
                    SET semantic_name = %s,
                        unit = %s,
                        concept_category = %s,
                        description = %s,
                        dict_entry_id = %s,
                        dict_match_status = %s,
                        match_confidence = %s,
                        llm_confidence = %s,
                        llm_reasoning = %s,
                        updated_at = NOW()
                    WHERE param_id = %s
                """, (
                    update.get('semantic_name'),
                    update.get('unit'),
                    update.get('concept_category'),
                    update.get('description'),
                    update.get('dict_entry_id'),
                    update.get('dict_match_status'),
                    update.get('match_confidence'),
                    update.get('llm_confidence'),
                    update.get('llm_reasoning'),
                    update.get('param_id')
                ))
            
            conn.commit()
            return stats
            
        except Exception as e:
            conn.rollback()
            print(f"[ParameterRepository] Error batch updating: {e}")
            raise
    
    # =========================================================================
    # DELETE
    # =========================================================================
    
    def delete_parameters_by_file(self, file_id: str) -> int:
        """파일의 모든 파라미터 삭제"""
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute(
                "DELETE FROM parameter WHERE file_id = %s",
                (file_id,)
            )
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            print(f"[ParameterRepository] Error deleting: {e}")
            return 0
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _row_to_param_dict(self, row: tuple) -> Dict[str, Any]:
        """DB row를 dict로 변환"""
        (param_id, param_key, source_type, source_col_id,
         sem_name, unit, category, desc,
         dict_id, match_status, match_conf,
         is_id, llm_conf, llm_reason) = row
        
        return {
            "param_id": param_id,
            "param_key": param_key,
            "source_type": source_type,
            "source_column_id": source_col_id,
            "semantic_name": sem_name,
            "unit": unit,
            "concept_category": category,
            "description": desc,
            "dict_entry_id": str(dict_id) if dict_id else None,
            "dict_match_status": match_status,
            "match_confidence": match_conf,
            "is_identifier": is_id,
            "llm_confidence": llm_conf,
            "llm_reasoning": llm_reason
        }

