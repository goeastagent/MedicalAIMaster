# src/processors/base.py
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# 가상의 LLM 클라이언트 인터페이스 (실제 구현 시 LangChain 등을 사용)
class AbstractLLMClient(ABC):
    @abstractmethod
    def ask_json(self, prompt: str) -> Dict:
        """프롬프트를 받아 JSON 형태로 응답을 반환"""
        pass

@dataclass
class AnchorResult:
    status: str  # FOUND, MISSING, AMBIGUOUS
    column_name: Optional[str]
    is_time_series: bool
    reasoning: str
    confidence: float
    needs_human_confirmation: bool

class BaseDataProcessor(ABC):
    """
    모든 데이터 프로세서는 LLM을 활용하여 메타데이터를 분석합니다.
    Rule-based 로직(정규식 등)은 제거되었습니다.
    """

    def __init__(self, llm_client: AbstractLLMClient):
        self.llm = llm_client

    @abstractmethod
    def can_handle(self, file_path: str) -> bool:
        pass

    @abstractmethod
    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        데이터를 로드하고 LLM에게 분석을 요청하여 메타데이터를 반환합니다.
        """
        pass

    def _ask_llm_to_identify_anchor(self, data_context_summary: str) -> AnchorResult:
        """
        [Core Logic]
        LLM에게 데이터 요약본(컬럼명+샘플)을 주고 Anchor(Patient ID)를 찾게 시킵니다.
        """
        prompt = f"""
        You are a generic Data Engineer for Medical AI.
        Analyze the following dataset summary and identify the 'Anchor Column' (Patient ID or Subject ID).
        
        [Data Context]
        {data_context_summary}

        [Task]
        1. Identify which column represents the unique Patient/Subject Identifier.
        2. Determine if this dataset is 'Longitudinal/Time-Series' (multiple rows per patient) or 'Cross-Sectional' (one row per patient).
        3. Provide a confidence score (0.0 to 1.0).

        [Output Format (JSON Only)]
        {{
            "found_anchor": true/false,
            "anchor_column_name": "column_name_here" or null,
            "is_time_series": true/false,
            "reasoning": "Explain why you chose this column based on name and sample values.",
            "confidence": 0.95
        }}
        
        If you are unsure or multiple columns look like IDs, set confidence low (< 0.8).
        """

        try:
            # LLM 호출 (JSON 응답 기대)
            response = self.llm.ask_json(prompt)
            
            confidence = response.get("confidence", 0.0)
            found = response.get("found_anchor", False)
            
            # 확신이 부족하거나 못 찾은 경우 -> 사람에게 물어봄
            if not found or confidence < 0.85:
                status = "AMBIGUOUS" if found else "MISSING"
                needs_human = True
            else:
                status = "FOUND"
                needs_human = False

            return AnchorResult(
                status=status,
                column_name=response.get("anchor_column_name"),
                is_time_series=response.get("is_time_series", False),
                reasoning=response.get("reasoning", ""),
                confidence=confidence,
                needs_human_confirmation=needs_human
            )

        except Exception as e:
            # LLM 에러 시 안전하게 사람에게 넘김
            return AnchorResult(
                status="ERROR",
                column_name=None,
                is_time_series=False,
                reasoning=f"LLM Processing Error: {str(e)}",
                confidence=0.0,
                needs_human_confirmation=True
            )