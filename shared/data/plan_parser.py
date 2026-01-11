# shared/data/plan_parser.py
"""
PlanParser - Execution Plan JSON 파싱 모듈

역할:
1. ExtractionAgent의 execution_plan JSON 해석
2. Cohort/Signal/Join 메타데이터 추출
3. DB에서 파일 경로 resolve

DataContext에서 파싱 로직을 분리하여 단일 책임 원칙 준수
"""

import logging
from typing import Dict, Any, List, Optional

from shared.database.connection import get_db_manager
from shared.models.plan import (
    CohortMetadata,
    SignalMetadata,
    JoinConfig,
    ParsedPlan,
)
from shared.utils import lazy_property

logger = logging.getLogger(__name__)


class PlanParser:
    """
    Execution Plan JSON 파서
    
    ExtractionAgent가 생성한 plan을 파싱하고,
    DB에서 필요한 정보(파일 경로 등)를 resolve합니다.
    
    Usage:
        parser = PlanParser()
        parsed = parser.parse(execution_plan)
        
        print(parsed.cohort.file_path)
        print(parsed.signal.param_keys)
    """
    
    def __init__(self, db_manager=None):
        """
        Args:
            db_manager: DB 매니저 (None이면 lazy loading)
        """
        self._db = db_manager
    
    @lazy_property
    def db(self):
        """Lazy DB connection"""
        return get_db_manager()
    
    def parse(self, execution_plan: Dict[str, Any], resolve_paths: bool = True) -> ParsedPlan:
        """
        Execution Plan 파싱
        
        Args:
            execution_plan: ExtractionAgent가 생성한 plan JSON
            resolve_paths: DB에서 파일 경로를 resolve할지 여부
        
        Returns:
            ParsedPlan 객체
        """
        plan = execution_plan.get("execution_plan", {})
        
        # 1. Cohort 메타데이터 파싱
        cohort = self._parse_cohort(plan.get("cohort_source", {}), resolve_paths)
        
        # 2. Signal 메타데이터 파싱
        signal = self._parse_signal(plan.get("signal_source", {}), resolve_paths)
        
        # 3. Join 설정 파싱
        join = self._parse_join(
            plan.get("join_specification", {}),
            cohort.entity_identifier,
            signal.entity_identifier_key
        )
        
        # 4. 원본 쿼리
        original_query = execution_plan.get("original_query")
        
        return ParsedPlan(
            raw_plan=execution_plan,
            cohort=cohort,
            signal=signal,
            join=join,
            original_query=original_query
        )
    
    def _parse_cohort(self, cohort_source: Dict[str, Any], resolve_paths: bool) -> CohortMetadata:
        """Cohort 소스 파싱"""
        if not cohort_source:
            return CohortMetadata()
        
        file_id = cohort_source.get("file_id")
        file_path = None
        
        # DB에서 파일 경로 resolve
        if resolve_paths and file_id:
            file_path = self._resolve_file_path(file_id)
        
        return CohortMetadata(
            file_id=file_id,
            file_path=file_path,
            file_name=cohort_source.get("file_name"),
            entity_identifier=cohort_source.get("entity_identifier"),
            row_represents=cohort_source.get("row_represents"),
            filters=cohort_source.get("filters", [])
        )
    
    def _parse_signal(self, signal_source: Dict[str, Any], resolve_paths: bool) -> SignalMetadata:
        """Signal 소스 파싱"""
        if not signal_source:
            return SignalMetadata()
        
        group_id = signal_source.get("group_id")
        files = []
        
        # DB에서 signal 파일들 resolve
        if resolve_paths and group_id:
            files = self._resolve_signal_files(group_id)
        
        # Parameters 파싱
        parameters = signal_source.get("parameters", [])
        param_keys = []
        for p in parameters:
            param_keys.extend(p.get("param_keys", []))
        
        return SignalMetadata(
            group_id=group_id,
            group_name=signal_source.get("group_name"),
            entity_identifier_key=signal_source.get("entity_identifier_key"),
            row_represents=signal_source.get("row_represents"),
            files=files,
            param_keys=param_keys,
            param_info=parameters,
            temporal_config=signal_source.get("temporal_alignment", {})
        )
    
    def _parse_join(
        self, 
        join_spec: Optional[Dict[str, Any]],
        cohort_entity_id: Optional[str],
        signal_entity_id_key: Optional[str]
    ) -> JoinConfig:
        """Join 설정 파싱"""
        # join_spec이 None인 경우 빈 dict로 대체
        join_spec = join_spec or {}
        
        # Plan에서 제공된 키 사용, 없으면 메타데이터에서 추출한 값 사용
        default_key = signal_entity_id_key or cohort_entity_id or "caseid"
        
        return JoinConfig(
            cohort_key=join_spec.get("cohort_key") or cohort_entity_id or default_key,
            signal_key=join_spec.get("signal_key") or signal_entity_id_key or default_key,
            join_type=join_spec.get("type", "inner")
        )
    
    def _resolve_file_path(self, file_id: str) -> Optional[str]:
        """DB에서 파일 경로 조회"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT file_path FROM file_catalog WHERE file_id = %s",
                (file_id,)
            )
            row = cursor.fetchone()
            conn.commit()
            
            if row:
                return row[0]
            
            logger.warning(f"File not found in DB: {file_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error resolving file path: {e}")
            return None
    
    def _resolve_signal_files(self, group_id: str) -> List[Dict[str, Any]]:
        """DB에서 Signal 그룹의 파일들 조회"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # file_group 테이블에서 entity_identifier_key 조회
            cursor.execute("""
                SELECT entity_identifier_key 
                FROM file_group 
                WHERE group_id = %s
            """, (group_id,))
            
            group_row = cursor.fetchone()
            # entity_identifier_key 가져오기 (기본값: caseid)
            entity_key_db = group_row[0] if group_row else "caseid"
            
            # filename_values에서 사용할 키 후보들 생성
            # DB에는 case_id, filename_values에는 caseid로 저장될 수 있음
            entity_key_candidates = [
                entity_key_db,                      # 원본 (case_id 또는 caseid)
                entity_key_db.replace("_", ""),     # underscore 제거 (caseid)
                entity_key_db.lower(),              # 소문자 변환
            ]
            # 중복 제거
            entity_key_candidates = list(dict.fromkeys(entity_key_candidates))
            
            # file_catalog에서 해당 그룹의 파일들 조회
            # filename_values JSONB에서 entity 값을 추출
            cursor.execute("""
                SELECT file_id, file_path, filename_values
                FROM file_catalog
                WHERE group_id = %s
            """, (group_id,))
            
            rows = cursor.fetchall()
            conn.commit()
            
            files = []
            for row in rows:
                file_id, file_path, filename_values = row
                # filename_values JSONB에서 entity 값 추출
                entity_value = None
                matched_key = None
                if filename_values:
                    # 후보 키들을 순서대로 시도
                    for key in entity_key_candidates:
                        if key in filename_values:
                            entity_value = filename_values[key]
                            matched_key = key
                            break
                
                if entity_value is not None:
                    files.append({
                        "file_id": str(file_id),
                        "file_path": file_path,
                        "entity_id": str(entity_value),  # DataContext.get_case_ids()가 사용하는 표준 키
                        matched_key: entity_value  # 실제 매칭된 키도 유지
                    })
            
            logger.info(f"📁 Resolved {len(files)} signal files for group {group_id}")
            return files
            
        except Exception as e:
            logger.error(f"Error resolving signal files: {e}")
            return []
