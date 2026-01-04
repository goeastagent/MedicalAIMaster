# src/database/repositories/file_group_repository.py
"""
File Group Repository

파일 그룹 관련 DB 조회/저장 로직

그룹 관리:
- 그룹 생성/조회/업데이트/삭제
- 그룹 내 파일 관리
- 샘플 파일 선정

분석 관련:
- LLM 분석 결과 저장
- 관계 정보 저장
- 그룹 파라미터 관리
"""

import json
from typing import List, Dict, Any, Optional, Tuple
from .base import BaseRepository


class FileGroupRepository(BaseRepository):
    """파일 그룹 Repository"""
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 그룹 CRUD
    # ═══════════════════════════════════════════════════════════════════════════
    
    def create_group(
        self,
        group_name: str,
        grouping_criteria: Dict,
        file_count: int = 0
    ) -> Optional[str]:
        """
        새 파일 그룹 생성
        
        Args:
            group_name: 그룹 이름 (예: "vital_files_caseid")
            grouping_criteria: 그룹핑 기준 
                {
                    "extensions": [".vital"],
                    "pattern": "{caseid}.vital",
                    "pattern_key": "caseid"
                }
            file_count: 초기 파일 수
        
        Returns:
            생성된 group_id (UUID string) 또는 None
        """
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute("""
                INSERT INTO file_group (group_name, grouping_criteria, file_count)
                VALUES (%s, %s, %s)
                RETURNING group_id
            """, (group_name, json.dumps(grouping_criteria), file_count))
            
            result = cursor.fetchone()
            conn.commit()
            return str(result[0]) if result else None
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error creating group: {e}")
            raise
    
    def get_group_by_id(self, group_id: str) -> Optional[Dict]:
        """ID로 그룹 조회"""
        result = self._execute_query("""
            SELECT 
                group_id, group_name, grouping_criteria, file_count,
                row_represents, entity_identifier_source, entity_identifier_key,
                confidence, reasoning, llm_analyzed_at,
                status, validation_reasoning, validated_at,
                related_files, sample_file_ids, verification_file_ids,
                created_at, updated_at
            FROM file_group
            WHERE group_id = %s
        """, (group_id,), fetch="one")
        
        return self._row_to_dict(result) if result else None
    
    def get_group_by_name(self, group_name: str) -> Optional[Dict]:
        """이름으로 그룹 조회"""
        result = self._execute_query("""
            SELECT 
                group_id, group_name, grouping_criteria, file_count,
                row_represents, entity_identifier_source, entity_identifier_key,
                confidence, reasoning, llm_analyzed_at,
                status, validation_reasoning, validated_at,
                related_files, sample_file_ids, verification_file_ids,
                created_at, updated_at
            FROM file_group
            WHERE group_name = %s
        """, (group_name,), fetch="one")
        
        return self._row_to_dict(result) if result else None
    
    def get_all_groups(self, status: str = None) -> List[Dict]:
        """
        모든 그룹 조회
        
        Args:
            status: 필터링할 상태 ('candidate', 'confirmed', 'rejected')
                    None이면 전체 조회
        """
        if status:
            results = self._execute_query("""
                SELECT 
                    group_id, group_name, grouping_criteria, file_count,
                    row_represents, entity_identifier_source, entity_identifier_key,
                    confidence, reasoning, llm_analyzed_at,
                    status, validation_reasoning, validated_at,
                    related_files, sample_file_ids, verification_file_ids,
                    created_at, updated_at
                FROM file_group
                WHERE status = %s
                ORDER BY created_at DESC
            """, (status,), fetch="all")
        else:
            results = self._execute_query("""
                SELECT 
                    group_id, group_name, grouping_criteria, file_count,
                    row_represents, entity_identifier_source, entity_identifier_key,
                    confidence, reasoning, llm_analyzed_at,
                    status, validation_reasoning, validated_at,
                    related_files, sample_file_ids, verification_file_ids,
                    created_at, updated_at
                FROM file_group
                ORDER BY created_at DESC
            """, fetch="all")
        
        return [self._row_to_dict(row) for row in results]
    
    def find_group_by_criteria(self, grouping_criteria: Dict) -> Optional[Dict]:
        """
        동일한 그룹핑 기준을 가진 그룹 찾기
        
        정확히 일치하는 criteria를 가진 그룹을 검색합니다.
        """
        result = self._execute_query("""
            SELECT 
                group_id, group_name, grouping_criteria, file_count,
                row_represents, entity_identifier_source, entity_identifier_key,
                confidence, reasoning, llm_analyzed_at,
                status, validation_reasoning, validated_at,
                related_files, sample_file_ids, verification_file_ids,
                created_at, updated_at
            FROM file_group
            WHERE grouping_criteria @> %s AND grouping_criteria <@ %s
        """, (json.dumps(grouping_criteria), json.dumps(grouping_criteria)), fetch="one")
        
        return self._row_to_dict(result) if result else None
    
    def find_or_create_group(
        self,
        group_name: str,
        grouping_criteria: Dict
    ) -> Tuple[str, bool]:
        """
        그룹 찾기 또는 생성
        
        Returns:
            (group_id, created): group_id와 새로 생성 여부
        """
        existing = self.find_group_by_criteria(grouping_criteria)
        if existing:
            return existing['group_id'], False
        
        group_id = self.create_group(group_name, grouping_criteria)
        return group_id, True
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 그룹 업데이트
    # ═══════════════════════════════════════════════════════════════════════════
    
    def update_group_analysis(
        self,
        group_id: str,
        row_represents: str,
        entity_identifier_source: str,
        entity_identifier_key: str,
        confidence: float,
        reasoning: str,
        sample_file_ids: List[str] = None,
        verification_file_ids: List[str] = None
    ) -> bool:
        """
        LLM 분석 결과 업데이트
        
        Args:
            group_id: 그룹 ID
            row_represents: 행이 나타내는 것 (예: 'surgical_case_vital_signs')
            entity_identifier_source: ID 출처 ('filename', 'content', 'directory')
            entity_identifier_key: ID 키 (예: 'caseid')
            confidence: 신뢰도 (0.0 ~ 1.0)
            reasoning: LLM 판단 근거
            sample_file_ids: 분석에 사용된 샘플 파일 IDs
            verification_file_ids: 검증에 사용된 파일 IDs
        
        Returns:
            성공 여부
        """
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute("""
                UPDATE file_group SET
                    row_represents = %s,
                    entity_identifier_source = %s,
                    entity_identifier_key = %s,
                    confidence = %s,
                    reasoning = %s,
                    llm_analyzed_at = NOW(),
                    sample_file_ids = %s::uuid[],
                    verification_file_ids = %s::uuid[]
                WHERE group_id = %s::uuid
            """, (
                row_represents,
                entity_identifier_source,
                entity_identifier_key,
                confidence,
                reasoning,
                sample_file_ids,
                verification_file_ids,
                group_id
            ))
            
            conn.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error updating analysis: {e}")
            raise
    
    def update_file_count(self, group_id: str) -> int:
        """
        그룹의 파일 수를 실제 값으로 업데이트
        
        Returns:
            업데이트된 파일 수
        """
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute("""
                UPDATE file_group 
                SET file_count = (
                    SELECT COUNT(*) FROM file_catalog WHERE group_id = %s
                )
                WHERE group_id = %s
                RETURNING file_count
            """, (group_id, group_id))
            
            result = cursor.fetchone()
            conn.commit()
            return result[0] if result else 0
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error updating file count: {e}")
            raise
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 파일-그룹 관리
    # ═══════════════════════════════════════════════════════════════════════════
    
    def add_files_to_group(
        self,
        group_id: str,
        file_ids: List[str]
    ) -> int:
        """
        파일들을 그룹에 추가
        
        Args:
            group_id: 그룹 ID
            file_ids: 추가할 파일 ID 리스트
        
        Returns:
            업데이트된 파일 수
        """
        if not file_ids:
            return 0
            
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute("""
                UPDATE file_catalog
                SET group_id = %s::uuid
                WHERE file_id = ANY(%s::uuid[])
            """, (group_id, file_ids))
            
            updated = cursor.rowcount
            
            # 파일 수 업데이트
            cursor.execute("""
                UPDATE file_group 
                SET file_count = (
                    SELECT COUNT(*) FROM file_catalog WHERE group_id = %s
                )
                WHERE group_id = %s
            """, (group_id, group_id))
            
            conn.commit()
            return updated
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error adding files: {e}")
            raise
    
    def remove_files_from_group(
        self,
        group_id: str,
        file_ids: List[str] = None
    ) -> int:
        """
        파일들을 그룹에서 제거
        
        Args:
            group_id: 그룹 ID
            file_ids: 제거할 파일 ID 리스트 (None이면 전체)
        
        Returns:
            제거된 파일 수
        """
        conn, cursor = self._get_cursor()
        
        try:
            if file_ids:
                cursor.execute("""
                    UPDATE file_catalog
                    SET group_id = NULL
                    WHERE group_id = %s AND file_id = ANY(%s)
                """, (group_id, file_ids))
            else:
                cursor.execute("""
                    UPDATE file_catalog
                    SET group_id = NULL
                    WHERE group_id = %s
                """, (group_id,))
            
            removed = cursor.rowcount
            
            # 파일 수 업데이트
            self.update_file_count(group_id)
            
            conn.commit()
            return removed
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error removing files: {e}")
            raise
    
    def get_files_in_group(
        self,
        group_id: str,
        limit: int = None,
        offset: int = 0
    ) -> List[Dict]:
        """
        그룹 내 파일 조회
        
        Args:
            group_id: 그룹 ID
            limit: 최대 조회 수
            offset: 시작 위치
        
        Returns:
            파일 정보 리스트
        """
        limit_clause = f"LIMIT {limit}" if limit else ""
        
        results = self._execute_query(f"""
            SELECT 
                file_id, file_path, file_name, file_extension,
                filename_values, file_size_bytes
            FROM file_catalog
            WHERE group_id = %s
            ORDER BY file_name
            {limit_clause}
            OFFSET %s
        """, (group_id, offset), fetch="all")
        
        return [
            {
                'file_id': str(row[0]),
                'file_path': row[1],
                'file_name': row[2],
                'file_extension': row[3],
                'filename_values': self._parse_json_field(row[4]),
                'file_size_bytes': row[5]
            }
            for row in results
        ]
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 샘플링
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_sample_files_for_analysis(
        self,
        group_id: str,
        sample_size: int = 5,
        strategy: str = "distributed"
    ) -> List[Dict]:
        """
        분석용 샘플 파일 선정
        
        Args:
            group_id: 그룹 ID
            sample_size: 샘플 수
            strategy: 샘플링 전략
                - "distributed": 파일 크기 분포에서 균등 추출
                - "random": 무작위 추출
                - "first": 처음 N개
        
        Returns:
            샘플 파일 정보 리스트
        """
        if strategy == "distributed":
            # 파일 크기 기준 분위수 추출
            results = self._execute_query(f"""
                WITH ranked AS (
                    SELECT 
                        file_id, file_path, file_name, file_extension,
                        filename_values, file_size_bytes,
                        NTILE(%s) OVER (ORDER BY file_size_bytes) as bucket
                    FROM file_catalog
                    WHERE group_id = %s
                )
                SELECT DISTINCT ON (bucket)
                    file_id, file_path, file_name, file_extension,
                    filename_values, file_size_bytes, bucket
                FROM ranked
                ORDER BY bucket, RANDOM()
            """, (sample_size, group_id), fetch="all")
            
        elif strategy == "random":
            results = self._execute_query("""
                SELECT 
                    file_id, file_path, file_name, file_extension,
                    filename_values, file_size_bytes, 0 as bucket
                FROM file_catalog
                WHERE group_id = %s
                ORDER BY RANDOM()
                LIMIT %s
            """, (group_id, sample_size), fetch="all")
            
        else:  # first
            results = self._execute_query("""
                SELECT 
                    file_id, file_path, file_name, file_extension,
                    filename_values, file_size_bytes, 0 as bucket
                FROM file_catalog
                WHERE group_id = %s
                ORDER BY file_name
                LIMIT %s
            """, (group_id, sample_size), fetch="all")
        
        return [
            {
                'file_id': str(row[0]),
                'file_path': row[1],
                'file_name': row[2],
                'file_extension': row[3],
                'filename_values': self._parse_json_field(row[4]),
                'file_size_bytes': row[5],
                'bucket': row[6] if len(row) > 6 else None
            }
            for row in results
        ]
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 그룹 파라미터
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_group_parameters(self, group_id: str) -> List[Dict]:
        """
        그룹에 연결된 파라미터 조회
        """
        results = self._execute_query("""
            SELECT 
                param_id, param_key, source_type,
                semantic_name, unit, concept_category,
                description, llm_confidence
            FROM parameter
            WHERE group_id = %s
            ORDER BY param_key
        """, (group_id,), fetch="all")
        
        return [
            {
                'param_id': row[0],
                'param_key': row[1],
                'source_type': row[2],
                'semantic_name': row[3],
                'unit': row[4],
                'concept_category': row[5],
                'description': row[6],
                'llm_confidence': row[7]
            }
            for row in results
        ]
    
    def add_group_parameter(
        self,
        group_id: str,
        param_key: str,
        source_type: str = 'group_common',
        semantic_name: str = None,
        unit: str = None,
        concept_category: str = None,
        description: str = None,
        llm_confidence: float = None,
        llm_reasoning: str = None
    ) -> int:
        """
        그룹에 파라미터 추가
        
        Returns:
            생성된 param_id
        """
        conn, cursor = self._get_cursor()
        
        try:
            # Partial unique index 사용: group_id 기반 중복 방지
            cursor.execute("""
                INSERT INTO parameter (
                    group_id, param_key, source_type,
                    semantic_name, unit, concept_category,
                    description, llm_confidence, llm_reasoning
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (group_id, param_key, source_type) WHERE group_id IS NOT NULL
                DO UPDATE SET
                    semantic_name = EXCLUDED.semantic_name,
                    unit = EXCLUDED.unit,
                    concept_category = EXCLUDED.concept_category,
                    description = EXCLUDED.description,
                    llm_confidence = EXCLUDED.llm_confidence,
                    llm_reasoning = EXCLUDED.llm_reasoning,
                    updated_at = NOW()
                RETURNING param_id
            """, (
                group_id, param_key, source_type,
                semantic_name, unit, concept_category,
                description, llm_confidence, llm_reasoning
            ))
            
            result = cursor.fetchone()
            conn.commit()
            return result[0] if result else None
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error adding parameter: {e}")
            raise
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 삭제
    # ═══════════════════════════════════════════════════════════════════════════
    
    def delete_group(self, group_id: str, remove_file_refs: bool = True) -> bool:
        """
        그룹 삭제
        
        Args:
            group_id: 삭제할 그룹 ID
            remove_file_refs: True면 연결된 파일의 group_id도 NULL로 설정
        
        Returns:
            성공 여부
        """
        conn, cursor = self._get_cursor()
        
        try:
            if remove_file_refs:
                cursor.execute("""
                    UPDATE file_catalog SET group_id = NULL WHERE group_id = %s
                """, (group_id,))
                
                cursor.execute("""
                    UPDATE parameter SET group_id = NULL WHERE group_id = %s
                """, (group_id,))
            
            cursor.execute("""
                DELETE FROM file_group WHERE group_id = %s
            """, (group_id,))
            
            conn.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error deleting group: {e}")
            raise
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 통계 및 분석
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_groups_needing_validation(self) -> List[Dict]:
        """
        검증이 필요한 그룹 조회 (status='candidate')
        
        Phase 2의 file_grouping_validation 노드에서 사용
        """
        results = self._execute_query("""
            SELECT 
                group_id, group_name, grouping_criteria, file_count
            FROM file_group
            WHERE status = 'candidate' AND file_count > 0
            ORDER BY file_count DESC
        """, fetch="all")
        
        return [
            {
                'group_id': str(row[0]),
                'group_name': row[1],
                'grouping_criteria': self._parse_json_field(row[2]),
                'file_count': row[3]
            }
            for row in results
        ]
    
    def get_groups_needing_analysis(self) -> List[Dict]:
        """
        분석이 필요한 그룹 조회 
        (status='confirmed' AND llm_analyzed_at IS NULL)
        
        확정된 그룹 중 아직 Entity 분석이 안 된 그룹
        """
        results = self._execute_query("""
            SELECT 
                group_id, group_name, grouping_criteria, file_count
            FROM file_group
            WHERE status = 'confirmed' 
              AND llm_analyzed_at IS NULL 
              AND file_count > 0
            ORDER BY file_count DESC
        """, fetch="all")
        
        return [
            {
                'group_id': str(row[0]),
                'group_name': row[1],
                'grouping_criteria': self._parse_json_field(row[2]),
                'file_count': row[3]
            }
            for row in results
        ]
    
    def get_groups_for_entity_analysis(self) -> List[Dict]:
        """
        Entity 분석이 필요한 confirmed 그룹 조회
        
        조건:
        - status = 'confirmed'
        - row_represents IS NULL (아직 Entity 분석 안 됨)
        
        Returns:
            그룹 정보 + 샘플 파일 ID 리스트
        """
        results = self._execute_query("""
            SELECT 
                fg.group_id, 
                fg.group_name, 
                fg.grouping_criteria, 
                fg.file_count,
                fg.sample_file_ids
            FROM file_group fg
            WHERE fg.status = 'confirmed'
              AND fg.row_represents IS NULL
              AND fg.file_count > 0
            ORDER BY fg.file_count DESC
        """, fetch="all")
        
        return [
            {
                'group_id': str(row[0]),
                'group_name': row[1],
                'grouping_criteria': self._parse_json_field(row[2]),
                'file_count': row[3],
                'sample_file_ids': [str(id) for id in row[4]] if row[4] else []
            }
            for row in results
        ]
    
    def update_group_validation(
        self,
        group_id: str,
        status: str,
        validation_reasoning: str = None
    ) -> bool:
        """
        그룹 검증 결과 업데이트
        
        Args:
            group_id: 그룹 ID
            status: 'confirmed' 또는 'rejected'
            validation_reasoning: LLM의 검증 판단 근거
        
        Returns:
            성공 여부
        """
        if status not in ('confirmed', 'rejected', 'candidate'):
            raise ValueError(f"Invalid status: {status}. Must be 'candidate', 'confirmed', or 'rejected'")
        
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute("""
                UPDATE file_group SET
                    status = %s,
                    validation_reasoning = %s,
                    validated_at = NOW(),
                    updated_at = NOW()
                WHERE group_id = %s
            """, (status, validation_reasoning, group_id))
            
            conn.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error updating validation: {e}")
            raise
    
    def confirm_group(self, group_id: str, reasoning: str = None) -> bool:
        """
        그룹을 확정 상태로 변경
        
        파일들의 group_id가 이미 설정되어 있어야 함
        """
        return self.update_group_validation(group_id, 'confirmed', reasoning)
    
    def reject_group(self, group_id: str, reasoning: str = None) -> bool:
        """
        그룹을 거부 상태로 변경
        
        거부된 그룹의 파일들은 개별 처리 대상이 됨
        """
        return self.update_group_validation(group_id, 'rejected', reasoning)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Human Review 관리
    # ═══════════════════════════════════════════════════════════════════════════
    
    def mark_needs_human_review(
        self,
        group_id: str,
        review_type: str,
        review_context: Dict = None,
        reasoning: str = None
    ) -> bool:
        """
        그룹을 human review 필요 상태로 마킹
        
        Args:
            group_id: 그룹 ID
            review_type: 리뷰 타입
                - 'pattern_validation_failed': 패턴 검증 실패
                - 'low_confidence': LLM 신뢰도 낮음
                - 'ambiguous_grouping': 그룹핑 기준 모호
                - 'complex_pattern': 복잡한 패턴으로 자동 처리 불가
            review_context: 리뷰에 필요한 추가 정보 (JSON)
            reasoning: 리뷰가 필요한 이유
        
        Returns:
            성공 여부
        """
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute("""
                UPDATE file_group SET
                    status = 'needs_human_review',
                    review_type = %s,
                    review_context = %s,
                    validation_reasoning = %s,
                    validated_at = NOW(),
                    updated_at = NOW()
                WHERE group_id = %s
            """, (
                review_type,
                json.dumps(review_context) if review_context else None,
                reasoning,
                group_id
            ))
            
            conn.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error marking human review: {e}")
            raise
    
    def get_groups_needing_human_review(self, review_type: str = None) -> List[Dict]:
        """
        Human review가 필요한 그룹 조회
        
        Args:
            review_type: 특정 리뷰 타입 필터 (None이면 전체)
        
        Returns:
            리뷰 필요 그룹 리스트
        """
        if review_type:
            results = self._execute_query("""
                SELECT 
                    group_id, group_name, grouping_criteria, file_count,
                    review_type, review_context, validation_reasoning,
                    validated_at
                FROM file_group
                WHERE status = 'needs_human_review' AND review_type = %s
                ORDER BY validated_at DESC
            """, (review_type,), fetch="all")
        else:
            results = self._execute_query("""
                SELECT 
                    group_id, group_name, grouping_criteria, file_count,
                    review_type, review_context, validation_reasoning,
                    validated_at
                FROM file_group
                WHERE status = 'needs_human_review'
                ORDER BY validated_at DESC
            """, fetch="all")
        
        return [
            {
                'group_id': str(row[0]),
                'group_name': row[1],
                'grouping_criteria': self._parse_json_field(row[2]),
                'file_count': row[3],
                'review_type': row[4],
                'review_context': self._parse_json_field(row[5]),
                'validation_reasoning': row[6],
                'validated_at': row[7]
            }
            for row in results
        ]
    
    def complete_human_review(
        self,
        group_id: str,
        status: str,
        reviewed_by: str,
        reasoning: str = None
    ) -> bool:
        """
        Human review 완료 처리
        
        Args:
            group_id: 그룹 ID
            status: 결과 상태 ('confirmed' 또는 'rejected')
            reviewed_by: 리뷰 완료한 사용자
            reasoning: 리뷰 결과 설명
        
        Returns:
            성공 여부
        """
        if status not in ('confirmed', 'rejected'):
            raise ValueError(f"Invalid status: {status}. Must be 'confirmed' or 'rejected'")
        
        conn, cursor = self._get_cursor()
        
        try:
            cursor.execute("""
                UPDATE file_group SET
                    status = %s,
                    reviewed_by = %s,
                    reviewed_at = NOW(),
                    validation_reasoning = COALESCE(%s, validation_reasoning),
                    updated_at = NOW()
                WHERE group_id = %s
            """, (status, reviewed_by, reasoning, group_id))
            
            conn.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error completing review: {e}")
            raise
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 패턴 분석용 (directory_pattern 노드)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_confirmed_groups_for_pattern_analysis(self) -> List[Dict]:
        """
        패턴 분석이 필요한 confirmed 그룹 조회
        
        조건:
        - status = 'confirmed'
        - grouping_criteria에 pattern_regex가 없거나 filename_values가 미적용
        
        Returns:
            그룹 정보 + 샘플 파일명 리스트
        """
        results = self._execute_query("""
            SELECT 
                fg.group_id, 
                fg.group_name, 
                fg.grouping_criteria, 
                fg.file_count,
                fg.sample_file_ids,
                ARRAY_AGG(fc.file_name ORDER BY fc.file_name) FILTER (WHERE fc.file_name IS NOT NULL) as sample_filenames
            FROM file_group fg
            LEFT JOIN file_catalog fc ON fc.group_id = fg.group_id
            WHERE fg.status = 'confirmed'
              AND (
                  fg.grouping_criteria->>'pattern_regex' IS NULL
                  OR NOT EXISTS (
                      SELECT 1 FROM file_catalog fc2 
                      WHERE fc2.group_id = fg.group_id 
                        AND fc2.filename_values IS NOT NULL 
                        AND fc2.filename_values != '{}'::jsonb
                      LIMIT 1
                  )
              )
            GROUP BY fg.group_id, fg.group_name, fg.grouping_criteria, 
                     fg.file_count, fg.sample_file_ids
            ORDER BY fg.file_count DESC
        """, fetch="all")
        
        return [
            {
                'group_id': str(row[0]),
                'group_name': row[1],
                'grouping_criteria': self._parse_json_field(row[2]),
                'file_count': row[3],
                'sample_file_ids': [str(id) for id in row[4]] if row[4] else [],
                'all_filenames': row[5][:100] if row[5] else []  # 최대 100개
            }
            for row in results
        ]
    
    def update_group_pattern(
        self,
        group_id: str,
        pattern_regex: str,
        pattern_columns: List[Dict],
        confidence: float = None
    ) -> bool:
        """
        그룹의 패턴 정보 업데이트 (grouping_criteria에 병합)
        
        Args:
            group_id: 그룹 ID
            pattern_regex: 정규식 패턴
            pattern_columns: 컬럼 정보 [{"name": "caseid", "position": 1}, ...]
            confidence: 패턴 신뢰도
        
        Returns:
            성공 여부
        """
        conn, cursor = self._get_cursor()
        
        try:
            # 기존 grouping_criteria 조회
            cursor.execute("""
                SELECT grouping_criteria FROM file_group WHERE group_id = %s
            """, (group_id,))
            result = cursor.fetchone()
            
            if not result:
                return False
            
            criteria = result[0] if isinstance(result[0], dict) else json.loads(result[0] or '{}')
            
            # 패턴 정보 병합
            criteria['pattern_regex'] = pattern_regex
            criteria['pattern_columns'] = pattern_columns
            if confidence is not None:
                criteria['pattern_confidence'] = confidence
            
            cursor.execute("""
                UPDATE file_group SET
                    grouping_criteria = %s,
                    updated_at = NOW()
                WHERE group_id = %s
            """, (json.dumps(criteria), group_id))
            
            conn.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            conn.rollback()
            print(f"[FileGroupRepository] Error updating pattern: {e}")
            raise
    
    def get_group_stats_summary(self) -> Dict[str, Any]:
        """그룹 통계 요약"""
        stats = {}
        
        # 전체 그룹 수
        result = self._execute_query(
            "SELECT COUNT(*) FROM file_group", fetch="one"
        )
        stats['total_groups'] = result[0] if result else 0
        
        # 상태별 그룹 수
        result = self._execute_query(
            "SELECT COUNT(*) FROM file_group WHERE status = 'candidate'",
            fetch="one"
        )
        stats['candidate_groups'] = result[0] if result else 0
        
        result = self._execute_query(
            "SELECT COUNT(*) FROM file_group WHERE status = 'confirmed'",
            fetch="one"
        )
        stats['confirmed_groups'] = result[0] if result else 0
        
        result = self._execute_query(
            "SELECT COUNT(*) FROM file_group WHERE status = 'rejected'",
            fetch="one"
        )
        stats['rejected_groups'] = result[0] if result else 0
        
        # Human review 필요 그룹 수
        result = self._execute_query(
            "SELECT COUNT(*) FROM file_group WHERE status = 'needs_human_review'",
            fetch="one"
        )
        stats['needs_review_groups'] = result[0] if result else 0
        
        # 분석 완료 그룹 수 (Entity 분석 완료)
        result = self._execute_query(
            "SELECT COUNT(*) FROM file_group WHERE llm_analyzed_at IS NOT NULL",
            fetch="one"
        )
        stats['analyzed_groups'] = result[0] if result else 0
        
        # 그룹화된 파일 수
        result = self._execute_query(
            "SELECT COUNT(*) FROM file_catalog WHERE group_id IS NOT NULL",
            fetch="one"
        )
        stats['grouped_files'] = result[0] if result else 0
        
        # 미그룹화 파일 수
        result = self._execute_query(
            "SELECT COUNT(*) FROM file_catalog WHERE group_id IS NULL",
            fetch="one"
        )
        stats['ungrouped_files'] = result[0] if result else 0
        
        # 그룹 파라미터 수
        result = self._execute_query(
            "SELECT COUNT(*) FROM parameter WHERE group_id IS NOT NULL",
            fetch="one"
        )
        stats['group_parameters'] = result[0] if result else 0
        
        return stats
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 헬퍼 메서드
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _row_to_dict(self, row) -> Dict:
        """DB row를 dict로 변환"""
        if not row:
            return None
        
        return {
            'group_id': str(row[0]),
            'group_name': row[1],
            'grouping_criteria': self._parse_json_field(row[2]),
            'file_count': row[3],
            'row_represents': row[4],
            'entity_identifier_source': row[5],
            'entity_identifier_key': row[6],
            'confidence': row[7],
            'reasoning': row[8],
            'llm_analyzed_at': row[9],
            'status': row[10],
            'validation_reasoning': row[11],
            'validated_at': row[12],
            'related_files': self._parse_json_field(row[13]) if row[13] else None,
            'sample_file_ids': [str(id) for id in row[14]] if row[14] else [],
            'verification_file_ids': [str(id) for id in row[15]] if row[15] else [],
            'created_at': row[16],
            'updated_at': row[17]
        }
    
    def _row_to_dict_full(self, row) -> Dict:
        """DB row를 dict로 변환 (human review 컬럼 포함)"""
        if not row:
            return None
        
        base = self._row_to_dict(row[:18])
        if base and len(row) > 18:
            base['review_type'] = row[18] if len(row) > 18 else None
            base['review_context'] = self._parse_json_field(row[19]) if len(row) > 19 and row[19] else None
            base['reviewed_by'] = row[20] if len(row) > 20 else None
            base['reviewed_at'] = row[21] if len(row) > 21 else None
        return base

