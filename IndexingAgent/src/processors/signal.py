# src/processors/signal.py
import os
from typing import Dict, Any
from .base import BaseDataProcessor

# MNE 라이브러리 (생체신호 처리용)
try:
    import mne
    MNE_AVAILABLE = True
except ImportError:
    MNE_AVAILABLE = False

class SignalProcessor(BaseDataProcessor):
    def can_handle(self, file_path: str) -> bool:
        ext = file_path.lower().split('.')[-1]
        return ext in ['edf', 'bdf', 'wfdb', 'hea']

    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        filename = os.path.basename(file_path)
        header_text = ""
        channels = []

        # 1. 헤더 정보 추출 (기술적 파싱)
        if MNE_AVAILABLE and file_path.endswith(('.edf', '.bdf')):
            try:
                raw = mne.io.read_raw_edf(file_path, preload=False, verbose=False)
                channels = raw.ch_names
                
                # LLM에게 줄 힌트 수집
                info = raw.info
                header_text += f"Subject Info Object: {info.get('subject_info', 'None')}\n"
                header_text += f"Experimenter: {info.get('experimenter', 'None')}\n"
                header_text += f"Measurement Date: {info.get('meas_date', 'None')}\n"
                
            except Exception:
                header_text += "Could not parse internal header (Format Error).\n"
        
        # 2. LLM을 위한 문맥(Context) 생성
        # 파일명도 매우 중요한 힌트이므로 포함
        context_summary = f"""
        Dataset Type: Bio-Signal (Waveform)
        File Name: {filename}
        
        Internal Header Metadata:
        {header_text}
        
        Channel Names (for context):
        {channels[:10]} ... (total {len(channels)})
        """

        # 3. LLM에게 물어보기
        # 생체신호는 보통 시계열(Time-series)이 기본이므로, LLM이 이를 인지하는지도 확인
        anchor_result = self._ask_llm_to_identify_anchor(context_summary)

        # 생체신호 특화 보정: 파일명에서 찾았을 수도 있고, 헤더에서 찾았을 수도 있음
        # LLM의 reasoning을 그대로 신뢰
        
        return {
            "processor_type": "signal",
            "file_path": file_path,
            "anchor_info": {
                "status": anchor_result.status,
                "target_column": anchor_result.column_name, # 여기선 컬럼명이 아니라 '추출된 ID 값'일 수 있음
                "is_time_series": True, # 생체신호는 본질적으로 시계열
                "reasoning": anchor_result.reasoning,
                "needs_human_confirmation": anchor_result.needs_human_confirmation
            }
        }