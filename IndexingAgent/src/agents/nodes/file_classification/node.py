# src/agents/nodes/file_classification/node.py
"""
File Classification Node

파일을 metadata/data로 분류합니다.
- metadata: 데이터 사전, 파라미터 정의 파일 (clinical_parameters.csv 등)
- data: 실제 측정/기록 데이터 파일 (clinical_data.csv 등)

✅ LLM 사용: is_metadata 판단
"""

from typing import Dict, Any, List
from datetime import datetime

from shared.database import FileRepository
from shared.config import LLMConfig
from IndexingAgent.src.config import FileClassificationConfig, IndexingConfig
from IndexingAgent.src.models.llm_responses import (
    FileClassificationItem,
    FileClassificationResult,
)
from shared.llm import get_llm_client

from shared.langgraph import BaseNode, LLMMixin, DatabaseMixin
from shared.langgraph import register_node
from .prompts import FileClassificationPrompt


@register_node
class FileClassificationNode(BaseNode, LLMMixin, DatabaseMixin):
    """
    File Classification Node (LLM-based)
    
    파일을 metadata/data로 분류합니다.
    - metadata: 데이터 사전, 파라미터 정의 파일
    - data: 실제 측정/기록 데이터 파일
    """
    
    name = "file_classification"
    description = "파일 분류 (metadata vs data)"
    order = 400
    requires_llm = True
    
    # 프롬프트 클래스 연결
    prompt_class = FileClassificationPrompt
    
    def __init__(self):
        super().__init__()
        self._file_repo = None
    
    # =========================================================================
    # Main Execution
    # =========================================================================
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        파일을 metadata/data로 분류
        
        Args:
            state: AgentState (catalog_file_ids 필요)
        
        Returns:
            업데이트된 상태:
            - file_classification_result: 분류 결과 요약
            - metadata_files: metadata 파일 경로 목록
            - data_files: data 파일 경로 목록
        """
        self.log("=" * 60)
        self.log("🏷️  metadata vs data 분류")
        self.log("=" * 60)
        
        started_at = datetime.now()
        
        # file_catalog에서 처리된 파일 ID들
        file_ids = state.get("catalog_file_ids", [])
        
        if not file_ids:
            self.log("⚠️ No files to classify", indent=1)
            return self._create_empty_result("No files to classify")
        
        self.log(f"📂 Files to classify: {len(file_ids)}", indent=1)
        
        # =====================================================================
        # Skip Already Analyzed (FORCE_REANALYZE=false인 경우)
        # =====================================================================
        skipped_count = 0
        if not IndexingConfig.FORCE_REANALYZE:
            file_repo = self._get_file_repo()
            skipped_count = file_repo.get_already_classified_count(file_ids)
            
            if skipped_count > 0:
                self.log(f"⏭️  Skipping {skipped_count} already classified files", indent=1)
                file_ids = file_repo.get_files_without_classification(file_ids)
                
                if not file_ids:
                    self.log("✅ All files already classified, nothing to do", indent=1)
                    # 기존 결과 조회하여 반환
                    return self._get_existing_classification_result(state.get("catalog_file_ids", []))
                
                self.log(f"📂 Files to analyze: {len(file_ids)}", indent=1)
        
        # 1. 파일 정보 수집
        self.log("📊 Collecting file information...", indent=1)
        file_infos = self._get_files_info(file_ids)
        
        # file_name → file_path 매핑
        file_id_to_path = {info['file_name']: info['file_path'] for info in file_infos}
        
        for info in file_infos:
            self.log(f"✅ {info['file_name']} ({info['column_count']} cols, {info['row_count']} rows)", indent=2)
        
        if len(file_infos) < len(file_ids):
            self.log(f"⚠️ Failed to get info for {len(file_ids) - len(file_infos)} files", indent=2)
        
        if not file_infos:
            self.log("❌ No file info collected", indent=1)
            return self._create_empty_result("No file info collected")
        
        # 2. LLM 호출 (배치 처리)
        self.log("🤖 Calling LLM for classification...", indent=1)
        batch_size = FileClassificationConfig.FILE_BATCH_SIZE
        classifications = self._call_llm_for_classification_batched(file_infos, batch_size)
        
        if not classifications:
            self.log("❌ LLM classification failed", indent=1)
            return self._create_empty_result("LLM classification failed")
        
        # 3. 결과 처리 및 DB 업데이트
        self.log(f"📝 Processing {len(classifications)} classifications...", indent=1)
        
        metadata_files = []
        data_files = []
        classifications_dict = {}
        
        for clf in classifications:
            file_name = clf.file_name
            is_metadata = clf.is_metadata
            confidence = clf.confidence
            reasoning = clf.reasoning
            
            file_path = file_id_to_path.get(file_name, file_name)
            
            # DB 업데이트
            self._update_file_classification(file_name, is_metadata, confidence)
            
            # 결과 분류
            if is_metadata:
                metadata_files.append(file_path)
                marker = "📋 metadata"
            else:
                data_files.append(file_path)
                marker = "📊 data"
            
            self.log(f"{marker}: {file_name} (conf={confidence:.2f})", indent=2)
            
            classifications_dict[file_name] = {
                "file_path": file_path,
                "is_metadata": is_metadata,
                "confidence": confidence,
                "reasoning": reasoning
            }
        
        # 4. 결과 요약
        completed_at = datetime.now()
        duration = (completed_at - started_at).total_seconds()
        
        # LLM 호출 횟수 계산
        batch_size = FileClassificationConfig.FILE_BATCH_SIZE
        llm_calls = (len(file_infos) + batch_size - 1) // batch_size
        
        result = FileClassificationResult(
            total_files=len(file_infos),
            metadata_files=metadata_files,
            data_files=data_files,
            classifications=classifications_dict,
            llm_calls=llm_calls,
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat()
        )
        
        self.log("✅ Complete!")
        self.log(f"📋 Metadata files: {len(metadata_files)}", indent=1)
        for f in metadata_files:
            self.log(f"- {f.split('/')[-1]}", indent=2)
        self.log(f"📊 Data files: {len(data_files)}", indent=1)
        for f in data_files:
            self.log(f"- {f.split('/')[-1]}", indent=2)
        self.log(f"⏱️  Duration: {duration:.1f}s", indent=1)
        self.log("=" * 60)
        
        return {
            "file_classification_result": result.model_dump(),
            "metadata_files": metadata_files,
            "data_files": data_files,
            "logs": [
                f"🏷️ [File Classification] Classified {len(file_infos)} files: "
                f"{len(metadata_files)} metadata, {len(data_files)} data"
            ]
        }
    
    # =========================================================================
    # File Info Collection
    # =========================================================================
    
    def _get_file_repo(self) -> FileRepository:
        """FileRepository 싱글톤 반환"""
        if self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo
    
    def _get_files_info(self, file_ids: List[str]) -> List[Dict[str, Any]]:
        """DB에서 파일 정보 조회"""
        file_repo = self._get_file_repo()
        try:
            return file_repo.get_files_with_classification_info(file_ids)
        except Exception as e:
            self.log(f"❌ Error getting files info: {e}", indent=1)
            return []
    
    # =========================================================================
    # LLM Methods
    # =========================================================================
    
    def _call_llm_for_classification_batched(
        self,
        file_infos: List[Dict[str, Any]],
        batch_size: int
    ) -> List[FileClassificationItem]:
        """
        LLM을 배치로 호출하여 파일 분류
        
        파일 수가 많을 때 배치로 나눠서 처리하여 토큰 제한 문제 방지
        """
        all_classifications = []
        n_files = len(file_infos)
        n_batches = (n_files + batch_size - 1) // batch_size
        
        for batch_idx in range(n_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, n_files)
            batch_infos = file_infos[start:end]
            
            if n_batches > 1:
                self.log(f"📤 Batch {batch_idx + 1}/{n_batches} ({len(batch_infos)} files)", indent=2)
            
            batch_result = self._call_llm_for_classification(batch_infos)
            
            if batch_result:
                self.log(f"✅ Got {len(batch_result)} results", indent=3)
                all_classifications.extend(batch_result)
            else:
                self.log(f"⚠️ Batch {batch_idx + 1} returned no results", indent=3)
        
        return all_classifications
    
    def _call_llm_for_classification(
        self,
        file_infos: List[Dict[str, Any]]
    ) -> List[FileClassificationItem]:
        """LLM을 호출하여 파일 분류 (단일 배치)"""
        llm = get_llm_client()
        
        # 프롬프트 빌드 (PromptTemplate 사용)
        files_info_text = self._build_files_info_text(file_infos)
        prompt = self.prompt_class.build(files_info=files_info_text)
        
        try:
            data = llm.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
            
            if data.get("error"):
                self.log(f"❌ LLM returned error: {data.get('error')}", indent=1)
                return []
            
            # PromptTemplate의 parse_response 사용
            classifications = self.prompt_class.parse_response(data)
            
            if classifications is None:
                self.log("⚠️ Failed to parse LLM response", indent=1)
                return []
            
            return classifications
            
        except Exception as e:
            self.log(f"❌ LLM call error: {e}", indent=1)
            return []
    
    def _build_files_info_text(self, file_infos: List[Dict[str, Any]]) -> str:
        """파일 정보를 LLM 프롬프트용 텍스트로 변환"""
        lines = []
        
        for i, info in enumerate(file_infos, 1):
            file_name = info.get('file_name', '?')
            col_count = info.get('column_count', 0)
            row_count = info.get('row_count', 0)
            columns = info.get('columns', [])
            
            lines.append(f'{i}. "{file_name}" [tabular, {col_count} columns, {row_count} rows]')
            
            col_names = [c['name'] for c in columns]
            lines.append(f"   Columns: {', '.join(col_names[:15])}")
            if len(col_names) > 15:
                lines.append(f"            ... and {len(col_names) - 15} more columns")
            
            lines.append("   Sample values per column:")
            for col in columns[:5]:
                col_name = col['name']
                unique_vals = col.get('unique_values', [])
                vals_str = [str(v)[:30] for v in unique_vals[:5]]
                lines.append(f"   - {col_name}: {vals_str}")
            
            if len(columns) > 5:
                lines.append(f"   ... and {len(columns) - 5} more columns")
            
            lines.append("")
        
        return "\n".join(lines)
    
    # =========================================================================
    # DB Update
    # =========================================================================
    
    def _update_file_classification(
        self,
        file_name: str,
        is_metadata: bool,
        confidence: float
    ):
        """file_catalog.is_metadata 업데이트"""
        file_repo = self._get_file_repo()
        return file_repo.update_is_metadata(file_name, is_metadata, confidence)
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _create_empty_result(self, error_msg: str) -> Dict[str, Any]:
        """빈 결과 생성"""
        return {
            "file_classification_result": {
                "total_files": 0,
                "metadata_files": [],
                "data_files": [],
                "error": error_msg
            },
            "metadata_files": [],
            "data_files": [],
            "logs": [f"⚠️ [File Classification] {error_msg}"]
        }
    
    def _get_existing_classification_result(self, file_ids: List[str]) -> Dict[str, Any]:
        """
        이미 분류된 파일들의 기존 결과 조회하여 반환
        
        FORCE_REANALYZE=false이고 모든 파일이 이미 분류된 경우 사용
        """
        file_repo = self._get_file_repo()
        files = file_repo.get_files_by_ids(file_ids)
        
        metadata_files = []
        data_files = []
        
        for f in files:
            if f.get('is_metadata'):
                metadata_files.append(f['file_path'])
            else:
                data_files.append(f['file_path'])
        
        result = FileClassificationResult(
            total_files=len(files),
            metadata_files=metadata_files,
            data_files=data_files,
            classifications={},  # 기존 분류 결과는 상세 조회 생략
            llm_calls=0,  # LLM 호출 없음 (스킵)
            started_at=datetime.now().isoformat(),
            completed_at=datetime.now().isoformat()
        )
        
        self.log(f"📋 Metadata files (cached): {len(metadata_files)}", indent=1)
        self.log(f"📊 Data files (cached): {len(data_files)}", indent=1)
        
        return {
            "file_classification_result": result.model_dump(),
            "metadata_files": metadata_files,
            "data_files": data_files,
            "logs": [
                f"🏷️ [File Classification] Skipped (already classified): "
                f"{len(metadata_files)} metadata, {len(data_files)} data"
            ]
        }
    
    # =========================================================================
    # Convenience Methods (Standalone Execution)
    # =========================================================================
    
    @classmethod
    def run_standalone(cls, file_ids: List[str] = None) -> Dict[str, Any]:
        """
        독립 실행 (테스트용)
        
        Args:
            file_ids: 분류할 파일 ID 목록 (None이면 DB에서 모든 파일 조회)
        
        Returns:
            분류 결과
        """
        node = cls()
        
        if file_ids is None:
            file_repo = node._get_file_repo()
            file_ids = file_repo.get_all_file_ids()
        
        state = {"catalog_file_ids": file_ids}
        return node.execute(state)

