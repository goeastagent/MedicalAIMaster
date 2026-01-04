# src/agents/nodes/column_classification/node.py
"""
Column Classification Node

각 컬럼의 역할(column_role)을 분류하고, parameter 테이블을 생성합니다.

Workflow:
1. 각 파일의 컬럼 정보 수집 (name, unique_values, stats)
2. LLM 호출하여 column_role 분류 (ColumnRole enum 사용)
3. column_metadata.column_role 업데이트
4. parameter 테이블 생성 (rule-based 후처리)
   - parameter_name: 컬럼명 → parameter
   - parameter_container: 컬럼 unique values → parameter(s)

✅ LLM 사용: column_role 판단
✅ 후처리: parameter 테이블 생성 (rule-based)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from src.agents.state import AgentState
from src.database import FileRepository, ColumnRepository
from src.database.repositories import ParameterRepository, FileGroupRepository
from src.config import LLMConfig, ColumnClassificationConfig
from src.agents.models import (
    ColumnRole,
    SourceType,
    ColumnClassificationItem,
    ColumnClassificationResult,
)
from src.utils.llm_client import get_llm_client
from src.agents.prompts import (
    ColumnClassificationPrompt,
    build_column_info_for_prompt,
    build_columns_info_batch,
)

from ...base import BaseNode, LLMMixin, DatabaseMixin
from ...registry import register_node


@register_node
class ColumnClassificationNode(BaseNode, LLMMixin, DatabaseMixin):
    """
    Column Classification Node (LLM-based + Rule-based Post-processing)
    
    각 컬럼의 역할을 분류하고, parameter 테이블을 생성합니다.
    - Phase 1: LLM으로 column_role 분류
    - Phase 2: Rule-based로 parameter 테이블 생성
    """
    
    name = "column_classification"
    description = "컬럼 역할 분류 및 parameter 생성"
    order = 420  # file_classification(400) 이후, data_semantic(600) 이전
    requires_llm = True
    
    # 프롬프트 클래스 연결
    prompt_class = ColumnClassificationPrompt
    
    def __init__(self):
        super().__init__()
        self._file_repo: Optional[FileRepository] = None
        self._column_repo: Optional[ColumnRepository] = None
        self._param_repo: Optional[ParameterRepository] = None
        self._group_repo: Optional[FileGroupRepository] = None
    
    # =========================================================================
    # Main Execution
    # =========================================================================
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        컬럼 역할 분류 및 parameter 생성
        
        수정된 로직:
        1. 그룹에 속한 파일들 → 그룹 단위로 처리 (샘플 1개만 분석)
        2. 그룹에 속하지 않은 파일들 → 기존 로직대로 개별 처리
        
        Args:
            state: AgentState (data_files, file_groups 필요)
        
        Returns:
            업데이트된 상태:
            - column_classification_result: 분류 결과 요약
        """
        self.log("=" * 60)
        self.log("🔍 컬럼 역할 분류 및 parameter 생성")
        self.log("=" * 60)
        
        started_at = datetime.now()
        
        # 초기화
        total_columns = 0
        columns_by_role: Dict[str, int] = {}
        parameters_created = 0
        parameters_from_column_name = 0
        parameters_from_column_value = 0
        parameters_from_group = 0
        llm_calls = 0
        batches_processed = 0
        groups_processed = 0
        ungrouped_files_processed = 0
        
        # Config
        batch_size = ColumnClassificationConfig.COLUMN_BATCH_SIZE
        
        # =====================================================================
        # Phase 1: 그룹에 속한 파일들 처리 (그룹 단위)
        # =====================================================================
        file_groups = state.get("file_groups", [])
        
        if file_groups:
            self.log(f"📦 Processing {len(file_groups)} file groups...", indent=1)
            
            for group in file_groups:
                group_result = self._process_group(group, batch_size)
                
                if group_result:
                    groups_processed += 1
                    total_columns += group_result['columns']
                    parameters_from_group += group_result['parameters']
                    parameters_created += group_result['parameters']
                    llm_calls += group_result['llm_calls']
                    batches_processed += group_result['batches']
                    
                    # columns_by_role 병합
                    for role, count in group_result.get('columns_by_role', {}).items():
                        columns_by_role[role] = columns_by_role.get(role, 0) + count
        
        # =====================================================================
        # Phase 2: 그룹에 속하지 않은 파일들 처리 (개별)
        # =====================================================================
        ungrouped_files = self._get_file_repo().get_ungrouped_data_files()
        
        if ungrouped_files:
            self.log(f"📄 Processing {len(ungrouped_files)} ungrouped files...", indent=1)
            
            for file_path in ungrouped_files:
                file_result = self._process_single_file(file_path, batch_size)
                
                if file_result:
                    ungrouped_files_processed += 1
                    total_columns += file_result['columns']
                    parameters_from_column_name += file_result.get('params_from_name', 0)
                    parameters_from_column_value += file_result.get('params_from_value', 0)
                    parameters_created += file_result['parameters']
                    llm_calls += file_result['llm_calls']
                    batches_processed += file_result['batches']
                    
                    # columns_by_role 병합
                    for role, count in file_result.get('columns_by_role', {}).items():
                        columns_by_role[role] = columns_by_role.get(role, 0) + count
        
        if not file_groups and not ungrouped_files:
            self.log("⚠️ No files to process", indent=1)
            return self._create_empty_result("No files to process")
        
        # =====================================================================
        # 결과 요약
        # =====================================================================
        completed_at = datetime.now()
        duration = (completed_at - started_at).total_seconds()
        
        result = ColumnClassificationResult(
            total_files=groups_processed + ungrouped_files_processed,
            total_columns=total_columns,
            columns_by_role=columns_by_role,
            parameters_created=parameters_created,
            parameters_from_column_name=parameters_from_column_name,
            parameters_from_column_value=parameters_from_column_value,
            llm_calls=llm_calls,
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat()
        )
        
        self.log("✅ Complete!")
        self.log(f"📦 Groups processed: {groups_processed}", indent=1)
        self.log(f"📄 Ungrouped files processed: {ungrouped_files_processed}", indent=1)
        self.log(f"📊 Total columns: {total_columns}", indent=1)
        self.log("🏷️  Columns by role:", indent=1)
        for role, count in sorted(columns_by_role.items()):
            self.log(f"- {role}: {count}", indent=2)
        self.log(f"📌 Parameters created: {parameters_created}", indent=1)
        self.log(f"- from group_common: {parameters_from_group}", indent=2)
        self.log(f"- from column_name: {parameters_from_column_name}", indent=2)
        self.log(f"- from column_value: {parameters_from_column_value}", indent=2)
        self.log(f"📦 Batches processed: {batches_processed}", indent=1)
        self.log(f"⏱️  Duration: {duration:.1f}s ({llm_calls} LLM calls)", indent=1)
        self.log("=" * 60)
        
        return {
            "column_classification_result": result.model_dump(),
            "logs": [
                f"🔍 [Column Classification] Processed {groups_processed} groups + "
                f"{ungrouped_files_processed} files, created {parameters_created} parameters"
            ]
        }
    
    # =========================================================================
    # Repository Access
    # =========================================================================
    
    def _get_file_repo(self) -> FileRepository:
        """FileRepository 싱글톤 반환"""
        if self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo
    
    def _get_column_repo(self) -> ColumnRepository:
        """ColumnRepository 싱글톤 반환"""
        if self._column_repo is None:
            self._column_repo = ColumnRepository()
        return self._column_repo
    
    def _get_param_repo(self) -> ParameterRepository:
        """ParameterRepository 싱글톤 반환"""
        if self._param_repo is None:
            self._param_repo = ParameterRepository()
        return self._param_repo
    
    def _get_group_repo(self) -> FileGroupRepository:
        """FileGroupRepository 싱글톤 반환"""
        if self._group_repo is None:
            self._group_repo = FileGroupRepository()
        return self._group_repo
    
    # =========================================================================
    # Column Info Collection
    # =========================================================================
    
    def _process_group(self, group: Dict[str, Any], batch_size: int) -> Optional[Dict[str, Any]]:
        """
        파일 그룹 단위로 컬럼 분류 및 parameter 생성
        
        그룹의 샘플 파일 1개만 분석하고, 결과는 그룹(group_id) 단위로 저장
        → 6,388개 파일을 1번만 분석하여 비용 절감
        
        Args:
            group: file_group 정보 (group_id, group_name, sample_file_ids 등)
            batch_size: LLM 배치 크기
            
        Returns:
            처리 결과 딕셔너리 또는 None
        """
        group_id = group.get('group_id')
        group_name = group.get('group_name', 'Unknown')
        sample_file_ids = group.get('sample_file_ids', [])
        
        self.log(f"📦 Group: {group_name} (files: {group.get('file_count', '?')})", indent=2)
        
        # 샘플 파일 선택
        if not sample_file_ids:
            # sample_file_ids가 없으면 그룹의 첫 번째 파일 사용
            group_repo = self._get_group_repo()
            files_in_group = group_repo.get_files_in_group(str(group_id))
            if not files_in_group:
                self.log(f"⚠️ No files in group {group_name}", indent=3)
                return None
            sample_file_path = files_in_group[0].get('file_path')
        else:
            # sample_file_ids의 첫 번째 파일 사용
            file_repo = self._get_file_repo()
            file_info = file_repo.get_file_by_id(str(sample_file_ids[0]))
            if not file_info:
                self.log(f"⚠️ Sample file not found for group {group_name}", indent=3)
                return None
            sample_file_path = file_info.get('file_path')
        
        self.log(f"🎯 Sample file: {sample_file_path.split('/')[-1]}", indent=3)
        
        # 샘플 파일의 컬럼 정보 수집
        columns_info = self._get_columns_info_for_file(sample_file_path)
        if not columns_info:
            self.log(f"⚠️ No columns found for sample file", indent=3)
            return None
        
        n_cols = len(columns_info)
        self.log(f"📊 Columns: {n_cols}", indent=3)
        
        # 결과 집계
        result = {
            'columns': n_cols,
            'parameters': 0,
            'llm_calls': 0,
            'batches': 0,
            'columns_by_role': {}
        }
        
        # 배치 분할
        batches = [columns_info[i:i+batch_size] for i in range(0, n_cols, batch_size)]
        
        for batch_idx, batch_cols in enumerate(batches):
            # LLM 호출
            classifications = self._call_llm_for_classification(batch_cols, f"[GROUP] {group_name}")
            result['llm_calls'] += 1
            result['batches'] += 1
            
            if not classifications:
                continue
            
            for clf in classifications:
                role = clf.column_role
                result['columns_by_role'][role] = result['columns_by_role'].get(role, 0) + 1
                
                # parameter 생성 (group_id 사용)
                if clf.is_parameter_name:
                    # Wide-format: 컬럼명 → group parameter
                    self._create_group_parameter(
                        group_id=str(group_id),
                        param_key=clf.column_name,
                        source_type=SourceType.GROUP_COMMON.value,
                        source_column=clf.column_name
                    )
                    result['parameters'] += 1
                    self.log(f"📌 {clf.column_name} → group parameter", indent=4)
                    
                elif clf.is_parameter_container:
                    # Long-format: 컬럼 값들 → group parameters
                    col_info = next(
                        (c for c in batch_cols if c['name'] == clf.column_name), 
                        None
                    )
                    if col_info:
                        all_unique_values = col_info.get('unique_values', [])
                        for param_key in all_unique_values:
                            self._create_group_parameter(
                                group_id=str(group_id),
                                param_key=str(param_key),
                                source_type=SourceType.GROUP_COMMON.value,
                                source_column=clf.column_name
                            )
                            result['parameters'] += 1
                        self.log(f"📌 {clf.column_name} → {len(all_unique_values)} group parameters", indent=4)
        
        self.log(f"✅ Group processed: {result['parameters']} parameters created", indent=3)
        return result
    
    def _process_single_file(self, file_path: str, batch_size: int) -> Optional[Dict[str, Any]]:
        """
        단일 파일의 컬럼 분류 및 parameter 생성 (기존 로직)
        
        Args:
            file_path: 파일 경로
            batch_size: LLM 배치 크기
            
        Returns:
            처리 결과 딕셔너리 또는 None
        """
        file_name = file_path.split('/')[-1]
        self.log(f"📄 Processing: {file_name}", indent=2)
        
        # 파일의 컬럼 정보 수집
        columns_info = self._get_columns_info_for_file(file_path)
        if not columns_info:
            self.log(f"⚠️ No columns found for {file_name}", indent=3)
            return None
        
        n_cols = len(columns_info)
        self.log(f"📊 Columns: {n_cols}", indent=3)
        
        # 결과 집계
        result = {
            'columns': n_cols,
            'parameters': 0,
            'params_from_name': 0,
            'params_from_value': 0,
            'llm_calls': 0,
            'batches': 0,
            'columns_by_role': {}
        }
        
        # 배치 분할
        batches = [columns_info[i:i+batch_size] for i in range(0, n_cols, batch_size)]
        
        for batch_idx, batch_cols in enumerate(batches):
            # LLM 호출
            classifications = self._call_llm_for_classification(batch_cols, file_name)
            result['llm_calls'] += 1
            result['batches'] += 1
            
            if not classifications:
                continue
            
            for clf in classifications:
                role = clf.column_role
                result['columns_by_role'][role] = result['columns_by_role'].get(role, 0) + 1
                
                # column_metadata.column_role 업데이트
                self._update_column_role(
                    file_path=file_path,
                    column_name=clf.column_name,
                    column_role=clf.column_role,
                    reasoning=clf.reasoning
                )
                
                # parameter 생성 (file_id 사용 - 기존 로직)
                if clf.is_parameter_name:
                    self._create_parameter_from_column_name(
                        file_path=file_path,
                        column_name=clf.column_name
                    )
                    result['parameters'] += 1
                    result['params_from_name'] += 1
                    self.log(f"📌 {clf.column_name} → parameter (column_name)", indent=4)
                    
                elif clf.is_parameter_container:
                    col_info = next(
                        (c for c in batch_cols if c['name'] == clf.column_name), 
                        None
                    )
                    if col_info:
                        all_unique_values = col_info.get('unique_values', [])
                        for param_key in all_unique_values:
                            self._create_parameter_from_column_value(
                                file_path=file_path,
                                container_column=clf.column_name,
                                param_key=str(param_key)
                            )
                            result['parameters'] += 1
                            result['params_from_value'] += 1
                        self.log(f"📌 {clf.column_name} → {len(all_unique_values)} parameters", indent=4)
        
        self.log(f"✅ File processed: {result['parameters']} parameters", indent=3)
        return result
    
    def _create_group_parameter(
        self, 
        group_id: str, 
        param_key: str, 
        source_type: str,
        source_column: str = None  # 참고용 (DB에는 저장 안 함)
    ) -> None:
        """
        그룹 단위 parameter 생성 (file_id=NULL, group_id=group_id)
        
        Args:
            group_id: 파일 그룹 ID
            param_key: 파라미터 키 (예: "Solar8000/HR")
            source_type: 출처 타입 (group_common)
            source_column: 출처 컬럼명 (참고용, DB에는 저장 안 함)
        """
        param_repo = self._get_param_repo()
        group_repo = self._get_group_repo()
        
        # 중복 체크
        existing = param_repo._execute_query("""
            SELECT param_id FROM parameter 
            WHERE group_id = %s::uuid AND param_key = %s
        """, (group_id, param_key), fetch="one")
        
        if existing:
            return  # 이미 존재
        
        # parameter 생성 (group_id 사용, source_column_id는 NULL)
        # INSERT 문이므로 fetch=None으로 명시 (fetchall 호출 방지)
        param_repo._execute_query("""
            INSERT INTO parameter (file_id, group_id, param_key, source_type, source_column_id)
            VALUES (NULL, %s::uuid, %s, %s, NULL)
        """, (group_id, param_key, source_type), fetch=None)

    def _get_columns_info_for_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        파일의 컬럼 정보 수집
        
        Returns:
            [{"name": str, "unique_values": list, "stats": dict}, ...]
        """
        column_repo = self._get_column_repo()
        
        try:
            # DB에서 컬럼 정보 조회 (file_path로 검색)
            columns = column_repo.get_columns_by_file_path(file_path)
            
            result = []
            for col in columns:
                result.append({
                    "name": col.get("column_name", ""),
                    "col_id": col.get("col_id"),
                    "unique_values": col.get("unique_values", []),
                    "stats": {
                        "count": col.get("total_count", 0),
                        "null_count": col.get("null_count", 0),
                        "dtype": col.get("data_type", "unknown"),
                        "unique_count": col.get("unique_count", 0),
                    }
                })
            
            return result
            
        except Exception as e:
            self.log(f"❌ Error getting columns info: {e}", indent=2)
            return []
    
    # =========================================================================
    # LLM Methods
    # =========================================================================
    
    def _call_llm_for_classification(
        self,
        columns_info: List[Dict[str, Any]],
        file_name: str
    ) -> List[ColumnClassificationItem]:
        """LLM을 호출하여 컬럼 역할 분류"""
        llm = get_llm_client()
        
        # 프롬프트 빌드
        columns_info_text = build_columns_info_batch(columns_info)
        prompt = self.prompt_class.build(
            columns_info=columns_info_text,
            file_name=file_name
        )
        
        try:
            data = llm.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
            
            if data.get("error"):
                self.log(f"❌ LLM returned error: {data.get('error')}", indent=2)
                return []
            
            # PromptTemplate의 parse_response 사용
            classifications = self.prompt_class.parse_response(data)
            
            if classifications is None:
                self.log("⚠️ Failed to parse LLM response", indent=2)
                return []
            
            # column_role 값 검증 (ColumnRole enum)
            validated = []
            for clf in classifications:
                validated_clf = self._validate_column_role(clf)
                validated.append(validated_clf)
            
            return validated
            
        except Exception as e:
            self.log(f"❌ LLM call error: {e}", indent=2)
            return []
    
    def _validate_column_role(
        self,
        clf: ColumnClassificationItem
    ) -> ColumnClassificationItem:
        """
        LLM 응답의 column_role 값 검증
        
        유효하지 않은 값은 'other'로 변경
        """
        valid_roles = ColumnRole.values()
        
        if clf.column_role not in valid_roles:
            self.log(f"⚠️ Invalid column_role '{clf.column_role}' → 'other'", indent=3)
            clf.column_role = ColumnRole.OTHER.value
        
        return clf
    
    # =========================================================================
    # DB Update Methods
    # =========================================================================
    
    def _update_column_role(
        self,
        file_path: str,
        column_name: str,
        column_role: str,
        reasoning: Optional[str] = None
    ):
        """column_metadata.column_role 업데이트"""
        column_repo = self._get_column_repo()
        
        try:
            column_repo.update_column_role(
                file_path=file_path,
                column_name=column_name,
                column_role=column_role,
                column_role_reasoning=reasoning
            )
        except Exception as e:
            print(f"         ❌ Error updating column_role: {e}")
    
    def _create_parameter_from_column_name(
        self,
        file_path: str,
        column_name: str
    ):
        """
        Wide-format: 컬럼명을 parameter로 생성
        
        source_type = 'column_name'
        """
        param_repo = self._get_param_repo()
        column_repo = self._get_column_repo()
        
        try:
            # file_id 조회
            file_info = self._get_file_repo().get_file_by_path(file_path)
            if not file_info:
                self.log(f"⚠️ File not found: {file_path}", indent=3)
                return
            
            file_id = file_info.get("file_id")
            
            # col_id 조회
            col_info = column_repo.get_column_by_name(file_path, column_name)
            col_id = col_info.get("col_id") if col_info else None
            
            # parameter 생성
            param_repo.create_parameter(
                file_id=file_id,
                param_key=column_name,
                source_type=SourceType.COLUMN_NAME.value,
                source_column_id=col_id
            )
            
        except Exception as e:
            self.log(f"❌ Error creating parameter: {e}", indent=3)
    
    def _create_parameter_from_column_value(
        self,
        file_path: str,
        container_column: str,
        param_key: str
    ):
        """
        Long-format: 컬럼 값을 parameter로 생성
        
        source_type = 'column_value'
        """
        param_repo = self._get_param_repo()
        column_repo = self._get_column_repo()
        
        try:
            # file_id 조회
            file_info = self._get_file_repo().get_file_by_path(file_path)
            if not file_info:
                self.log(f"⚠️ File not found: {file_path}", indent=3)
                return
            
            file_id = file_info.get("file_id")
            
            # col_id 조회
            col_info = column_repo.get_column_by_name(file_path, container_column)
            col_id = col_info.get("col_id") if col_info else None
            
            # parameter 생성
            param_repo.create_parameter(
                file_id=file_id,
                param_key=param_key,
                source_type=SourceType.COLUMN_VALUE.value,
                source_column_id=col_id
            )
            
        except Exception as e:
            self.log(f"❌ Error creating parameter: {e}", indent=3)
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _create_empty_result(self, error_msg: str) -> Dict[str, Any]:
        """빈 결과 생성"""
        return {
            "column_classification_result": {
                "total_files": 0,
                "total_columns": 0,
                "columns_by_role": {},
                "parameters_created": 0,
                "error": error_msg
            },
            "logs": [f"⚠️ [Column Classification] {error_msg}"]
        }
    
    # =========================================================================
    # Convenience Methods (Standalone Execution)
    # =========================================================================
    
    @classmethod
    def run_standalone(cls, data_files: List[str] = None) -> Dict[str, Any]:
        """
        독립 실행 (테스트용)
        
        Args:
            data_files: 처리할 파일 경로 목록 (None이면 DB에서 data 파일 조회)
        
        Returns:
            분류 결과
        """
        node = cls()
        
        if data_files is None:
            file_repo = node._get_file_repo()
            data_files = file_repo.get_data_file_paths()
        
        state = {"data_files": data_files}
        return node.execute(state)

