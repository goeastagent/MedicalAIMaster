# src/agents/nodes/classification.py
"""
File Classification Node

파일을 metadata/data로 분류합니다.
- metadata: 데이터 사전, 파라미터 정의 파일 (clinical_parameters.csv 등)
- data: 실제 측정/기록 데이터 파일 (clinical_data.csv 등)

✅ LLM 사용: is_metadata 판단
"""

from typing import Dict, Any, List
from datetime import datetime

from src.agents.state import AgentState
from src.database import FileRepository
from src.config import LLMConfig
from src.agents.models.llm_responses import (
    FileClassificationItem,
    FileClassificationResult,
)
from src.utils.llm_client import get_llm_client

from ..base import BaseNode, LLMMixin, DatabaseMixin
from ..registry import register_node


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
    
    # =========================================================================
    # Prompt Template
    # =========================================================================
    
    CLASSIFICATION_PROMPT = """You are a Medical Data Expert specializing in healthcare informatics.

[Task]
Classify each file as "metadata" or "data":

**metadata** files:
- Data dictionaries, codebooks, parameter definitions, lookup tables
- Typically contain columns like: Parameter, Description, Unit, Code, Category
- Values are mostly text descriptions, definitions, or codes
- Purpose: Define or describe what data means
- Examples: clinical_parameters.csv, lab_parameters.csv, track_names.csv

**data** files:
- Actual measurements, patient records, lab results, vital signs
- Typically contain columns like: patient_id, timestamp, measured values
- Values are mostly numbers, IDs, dates, measurements
- Purpose: Store actual recorded data
- Examples: clinical_data.csv, lab_data.csv, vitals.csv

[Files to Classify]
{files_info}

[Output Format]
Return ONLY valid JSON (no markdown, no explanation):
{{
  "classifications": [
    {{
      "file_name": "example.csv",
      "is_metadata": true,
      "confidence": 0.95,
      "reasoning": "Contains Parameter, Description, Unit columns typical of a data dictionary"
    }}
  ]
}}
"""
    
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
            state: AgentState (phase2_file_ids 필요)
        
        Returns:
            업데이트된 상태:
            - phase4_result: 분류 결과 요약
            - metadata_files: metadata 파일 경로 목록
            - data_files: data 파일 경로 목록
        """
        print("\n" + "=" * 60)
        print("🏷️  [File Classification] metadata vs data 분류")
        print("=" * 60)
        
        started_at = datetime.now()
        
        # file_catalog에서 처리된 파일 ID들
        file_ids = state.get("phase2_file_ids", [])
        
        if not file_ids:
            print("   ⚠️ No files to classify")
            return self._create_empty_result("No files to classify")
        
        print(f"   📂 Files to classify: {len(file_ids)}")
        
        # 1. 파일 정보 수집
        print("\n   📊 Collecting file information...")
        file_infos = self._get_files_info(file_ids)
        
        # file_name → file_path 매핑
        file_id_to_path = {info['file_name']: info['file_path'] for info in file_infos}
        
        for info in file_infos:
            print(f"      ✅ {info['file_name']} ({info['column_count']} cols, {info['row_count']} rows)")
        
        if len(file_infos) < len(file_ids):
            print(f"      ⚠️ Failed to get info for {len(file_ids) - len(file_infos)} files")
        
        if not file_infos:
            print("   ❌ No file info collected")
            return self._create_empty_result("No file info collected")
        
        # 2. LLM 호출
        print(f"\n   🤖 Calling LLM for classification...")
        classifications = self._call_llm_for_classification(file_infos)
        
        if not classifications:
            print("   ❌ LLM classification failed")
            return self._create_empty_result("LLM classification failed")
        
        # 3. 결과 처리 및 DB 업데이트
        print(f"\n   📝 Processing {len(classifications)} classifications...")
        
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
            
            print(f"      {marker}: {file_name} (conf={confidence:.2f})")
            
            classifications_dict[file_name] = {
                "file_path": file_path,
                "is_metadata": is_metadata,
                "confidence": confidence,
                "reasoning": reasoning
            }
        
        # 4. 결과 요약
        completed_at = datetime.now()
        duration = (completed_at - started_at).total_seconds()
        
        result = FileClassificationResult(
            total_files=len(file_infos),
            metadata_files=metadata_files,
            data_files=data_files,
            classifications=classifications_dict,
            llm_calls=1,
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat()
        )
        
        print(f"\n✅ [File Classification] Complete!")
        print(f"   📋 Metadata files: {len(metadata_files)}")
        for f in metadata_files:
            print(f"      - {f.split('/')[-1]}")
        print(f"   📊 Data files: {len(data_files)}")
        for f in data_files:
            print(f"      - {f.split('/')[-1]}")
        print(f"   ⏱️  Duration: {duration:.1f}s")
        print("=" * 60 + "\n")
        
        return {
            "phase4_result": result.model_dump(),
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
            print(f"   ❌ Error getting files info: {e}")
            return []
    
    # =========================================================================
    # LLM Methods
    # =========================================================================
    
    def _call_llm_for_classification(
        self,
        file_infos: List[Dict[str, Any]]
    ) -> List[FileClassificationItem]:
        """LLM을 호출하여 파일 분류"""
        llm = get_llm_client()
        
        files_info_text = self._build_files_info_text(file_infos)
        prompt = self.CLASSIFICATION_PROMPT.format(files_info=files_info_text)
        
        try:
            data = llm.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
            
            if data.get("error"):
                print(f"   ❌ LLM returned error: {data.get('error')}")
                return []
            
            classifications = []
            for item in data.get('classifications', []):
                try:
                    classification = FileClassificationItem(**item)
                    classifications.append(classification)
                except Exception as e:
                    print(f"   ⚠️ Failed to parse classification for {item.get('file_name', '?')}: {e}")
            
            return classifications
            
        except Exception as e:
            print(f"   ❌ LLM call error: {e}")
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
            "phase4_result": {
                "total_files": 0,
                "metadata_files": [],
                "data_files": [],
                "error": error_msg
            },
            "metadata_files": [],
            "data_files": [],
            "logs": [f"⚠️ [File Classification] {error_msg}"]
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
        
        state = {"phase2_file_ids": file_ids}
        return node.execute(state)
