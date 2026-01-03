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
from src.database.repositories import ParameterRepository
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
    
    # =========================================================================
    # Main Execution
    # =========================================================================
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        컬럼 역할 분류 및 parameter 생성
        
        Args:
            state: AgentState (data_files 필요)
        
        Returns:
            업데이트된 상태:
            - column_classification_result: 분류 결과 요약
        """
        self.log("=" * 60)
        self.log("🔍 컬럼 역할 분류 및 parameter 생성")
        self.log("=" * 60)
        
        started_at = datetime.now()
        
        # data_files에서 처리할 파일 경로들
        data_files = state.get("data_files", [])
        
        if not data_files:
            self.log("⚠️ No data files to process", indent=1)
            return self._create_empty_result("No data files to process")
        
        self.log(f"📂 Files to process: {len(data_files)}", indent=1)
        
        # 초기화
        total_columns = 0
        columns_by_role: Dict[str, int] = {}
        parameters_created = 0
        parameters_from_column_name = 0
        parameters_from_column_value = 0
        llm_calls = 0
        batches_processed = 0
        
        # Config
        batch_size = ColumnClassificationConfig.COLUMN_BATCH_SIZE
        
        # 각 파일별 처리
        for file_path in data_files:
            file_name = file_path.split('/')[-1]
            self.log(f"📄 Processing: {file_name}", indent=1)
            
            # 1. 파일의 컬럼 정보 수집
            columns_info = self._get_columns_info_for_file(file_path)
            
            if not columns_info:
                self.log(f"⚠️ No columns found for {file_name}", indent=2)
                continue
            
            n_cols = len(columns_info)
            self.log(f"📊 Columns: {n_cols}", indent=2)
            total_columns += n_cols
            
            # 2. 배치 분할 (컬럼 수가 많으면)
            batches = [columns_info[i:i+batch_size] for i in range(0, n_cols, batch_size)]
            
            if len(batches) > 1:
                self.log(f"📦 Splitting into {len(batches)} batches (batch_size={batch_size})", indent=2)
            
            # 3. 배치별 LLM 호출
            for batch_idx, batch_cols in enumerate(batches):
                if len(batches) > 1:
                    self.log(f"🔄 Batch {batch_idx + 1}/{len(batches)} ({len(batch_cols)} columns)", indent=2)
                
                # LLM 호출
                classifications = self._call_llm_for_classification(batch_cols, file_name)
                llm_calls += 1
                batches_processed += 1
                
                if not classifications:
                    self.log(f"❌ LLM classification failed for batch {batch_idx + 1}", indent=3)
                    continue
                
                # 4. 결과 처리 (배치별로 즉시 DB 업데이트)
                for clf in classifications:
                    role = clf.column_role
                    columns_by_role[role] = columns_by_role.get(role, 0) + 1
                    
                    # 4a. column_metadata.column_role 업데이트
                    self._update_column_role(
                        file_path=file_path,
                        column_name=clf.column_name,
                        column_role=clf.column_role,
                        reasoning=clf.reasoning
                    )
                    
                    # 4b. parameter 테이블 생성 (rule-based 후처리)
                    if clf.is_parameter_name:
                        # Wide-format: 컬럼명 → parameter
                        self._create_parameter_from_column_name(
                            file_path=file_path,
                            column_name=clf.column_name
                        )
                        parameters_created += 1
                        parameters_from_column_name += 1
                        self.log(f"📌 {clf.column_name} → parameter (column_name)", indent=3)
                    
                    elif clf.is_parameter_container:
                        # Long-format: 컬럼의 전체 unique values → parameter(s)
                        # LLM 응답의 parameters가 아닌, DB에서 조회한 전체 unique_values 사용
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
                                    param_key=str(param_key)  # 값을 문자열로 변환
                                )
                                parameters_created += 1
                                parameters_from_column_value += 1
                            self.log(f"📌 {clf.column_name} → {len(all_unique_values)} parameters (column_values)", indent=3)
                
                if len(batches) > 1:
                    self.log(f"✅ Classified {len(classifications)} columns in batch", indent=3)
            
            self.log(f"✅ Classified {n_cols} columns total", indent=2)
        
        # 4. 결과 요약
        completed_at = datetime.now()
        duration = (completed_at - started_at).total_seconds()
        
        result = ColumnClassificationResult(
            total_files=len(data_files),
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
        self.log(f"📊 Total columns: {total_columns}", indent=1)
        self.log("🏷️  Columns by role:", indent=1)
        for role, count in sorted(columns_by_role.items()):
            self.log(f"- {role}: {count}", indent=2)
        self.log(f"📌 Parameters created: {parameters_created}", indent=1)
        self.log(f"- from column_name: {parameters_from_column_name}", indent=2)
        self.log(f"- from column_value: {parameters_from_column_value}", indent=2)
        self.log(f"📦 Batches processed: {batches_processed}", indent=1)
        self.log(f"⏱️  Duration: {duration:.1f}s ({llm_calls} LLM calls)", indent=1)
        self.log("=" * 60)
        
        return {
            "column_classification_result": result.model_dump(),
            "logs": [
                f"🔍 [Column Classification] Classified {total_columns} columns, "
                f"created {parameters_created} parameters"
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
    
    # =========================================================================
    # Column Info Collection
    # =========================================================================
    
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

