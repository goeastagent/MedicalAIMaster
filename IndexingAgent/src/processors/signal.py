import os
import numpy as np
from typing import Dict, Any, List, Optional

# Base Class 임포트 (base.py에 정의됨)
from .base import BaseDataProcessor, AnchorResult

# --- 라이브러리 동적 로드 (설치되지 않았을 경우 대비) ---
try:
    import vitaldb
    VITALDB_AVAILABLE = True
except ImportError:
    VITALDB_AVAILABLE = False

try:
    import mne
    MNE_AVAILABLE = True
except ImportError:
    MNE_AVAILABLE = False

class SignalProcessor(BaseDataProcessor):
    """
    생체신호 데이터(.vital, .edf)의 헤더를 파싱하여 메타데이터를 추출하는 프로세서.
    대용량 데이터를 메모리에 올리지 않고 '기술적 사실(Technical Facts)'만 수집하여
    LLM이 데이터의 성격과 Anchor를 추론할 수 있도록 돕습니다.
    """

    def can_handle(self, file_path: str) -> bool:
        """처리 가능한 파일 확장자 확인"""
        ext = file_path.lower().split('.')[-1]
        return ext in ['vital', 'edf', 'bdf', 'wfdb']

    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        [Rule Prepares]
        라이브러리를 사용하여 트랙 정보, 단위, 샘플링 레이트 등을 추출합니다.
        실제 파형 데이터(Waveform)는 로드하지 않습니다.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # 기본 메타데이터 구조 초기화
        metadata = {
            "processor_type": "signal",
            "file_path": file_path,
            "file_size_mb": round(os.path.getsize(file_path) / (1024 * 1024), 2),
            "columns": [],        # 트랙명 리스트 (LLM이 의미 추론용) -> Tabular의 columns와 매핑
            "column_details": {}, # 트랙별 상세 정보 (단위, SR)
            "duration": 0.0,
            "is_time_series": True # 신호 데이터는 본질적으로 시계열
        }

        ext = file_path.lower().split('.')[-1]
        error_msg = None

        # --- Strategy 1: VitalDB (.vital) ---
        if ext == 'vital':
            if not VITALDB_AVAILABLE:
                error_msg = "vitaldb library is not installed. Please install it to process .vital files."
            else:
                try:
                    # VitalFile을 생성하면 헤더만 파싱하므로 매우 빠름 (Lazy Loading)
                    vf = vitaldb.VitalFile(file_path)
                    
                    # 트랙 정보 추출
                    # vf.trks 구조: {track_name: {'unit': str, 'dt': float, 'min': float, 'max': float, ...}}
                    track_names = []
                    
                    for trk_name, trk_info in vf.trks.items():
                        track_names.append(trk_name)
                        
                        # 샘플링 레이트 계산 (1 / dt)
                        dt = trk_info.get('dt', 0)
                        sr = round(1 / dt, 1) if dt > 0 else 0
                        
                        # 상세 정보 저장 (LLM 및 Catalog용)
                        metadata["column_details"][trk_name] = {
                            "column_name": trk_name, # 통일성을 위해 추가
                            "unit": trk_info.get('unit', ''),
                            "sample_rate": sr,
                            "min_val": trk_info.get('min'),
                            "max_val": trk_info.get('max'),
                            "column_type": "waveform" if sr > 1 else "numeric_trend",
                            "samples": [] # 신호 데이터는 샘플 값을 직접 보여주기 어려우므로 비워둠
                        }
                    
                    metadata["columns"] = track_names
                    # Duration 추정 (첫 번째 트랙 기준, 필요 시 로직 보강)
                    metadata["duration"] = 0.0 # 헤더만으로는 정확한 duration 알기 어려울 수 있음

                except Exception as e:
                    error_msg = f"VitalDB parsing error: {str(e)}"

        # --- Strategy 2: MNE (.edf, .bdf) ---
        elif ext in ['edf', 'bdf'] and MNE_AVAILABLE:
            try:
                # preload=False로 설정하여 헤더만 읽음 (핵심)
                raw = mne.io.read_raw_edf(file_path, preload=False, verbose=False)
                
                metadata["columns"] = raw.ch_names
                metadata["duration"] = raw.times[-1] if raw.times.size > 0 else 0
                
                for ch in raw.ch_names:
                    # 채널 정보 추출
                    ch_idx = raw.ch_names.index(ch)
                    ch_info = raw.info['chs'][ch_idx]
                    sr = raw.info['sfreq'] 
                    
                    # 단위 추출 시도 (MNE는 보통 V, uV 등으로 자동 변환됨)
                    unit_mul = ch_info.get('unit_mul', 0)
                    unit = "V" # 기본값
                    
                    metadata["column_details"][ch] = {
                        "column_name": ch,
                        "sample_rate": sr,
                        "unit": unit,
                        "column_type": "waveform",
                        "samples": []
                    }
            except Exception as e:
                error_msg = f"MNE parsing error: {str(e)}"
        
        elif ext in ['edf', 'bdf'] and not MNE_AVAILABLE:
            error_msg = "mne library is not installed. Please install it to process .edf/.bdf files."

        # 에러 발생 시 처리
        if error_msg:
            return {"error": error_msg, "processor_type": "signal"}

        # --- [Core] LLM에게 판단 요청 (Anchor 식별) ---
        # Rule이 수집한 '파일명'과 '트랙 리스트'를 바탕으로 LLM이 의미를 해석
        
        # 1. LLM을 위한 문맥 생성
        context_summary = self._create_signal_context(metadata)
        
        # 2. LLM에게 질문 (BaseDataProcessor의 메서드 활용)
        # base.py의 _ask_llm_to_identify_anchor는 JSON 응답을 파싱하여 AnchorResult를 반환함
        anchor_result = self._ask_llm_to_identify_anchor(context_summary)
        
        # 3. 결과 병합
        metadata["anchor_info"] = {
            "status": anchor_result.status,
            "target_column": anchor_result.column_name, # 여기선 컬럼명이 아니라 '파일명에서 추출된 ID 값'일 가능성이 높음
            "is_time_series": True, # 신호는 무조건 시계열
            "reasoning": anchor_result.reasoning,
            "needs_human_confirmation": anchor_result.needs_human_confirmation,
            "msg": f"Reasoning: {anchor_result.reasoning}"
        }

        return metadata

    def _create_signal_context(self, metadata: Dict) -> str:
        """
        LLM에게 보낼 Signal 데이터 요약본 생성.
        Tabular 데이터와 달리 '값(Sample)'보다는 '트랙명(Name)'과 '단위(Unit)'가 결정적 힌트가 됨.
        """
        filename = os.path.basename(metadata["file_path"])
        tracks = metadata["columns"]
        file_size = metadata.get("file_size_mb", 0)
        
        # 트랙 리스트 요약 (너무 길면 자름)
        display_count = 15
        if len(tracks) > display_count:
            track_list_str = ", ".join(tracks[:display_count]) + f", ... (+{len(tracks)-display_count} more)"
        else:
            track_list_str = ", ".join(tracks)
            
        # 트랙별 단위 정보 힌트 구성 (상위 5개만)
        # 예: "SNUADC/ART (mmHg)", "BIS/BIS (None)"
        track_hints = []
        for t in tracks[:5]:
            details = metadata["column_details"].get(t, {})
            unit = details.get("unit", "")
            sr = details.get("sample_rate", "")
            
            hint = f"- {t}"
            if unit: hint += f" (Unit: {unit})"
            if sr: hint += f" (SR: {sr}Hz)"
            track_hints.append(hint)

        context = f"""
        Dataset Type: Bio-Signal (Waveform/Vital)
        File Name: {filename}
        File Size: {file_size} MB
        
        [Structure Information]
        Total Tracks: {len(tracks)}
        Track Names List: [{track_list_str}]
        
        [Detailed Sample Tracks]
        {chr(10).join(track_hints)}
        
        [Reasoning Task]
        1. Identify the Patient ID or Case ID from the 'File Name' or Header.
           (Note: In signal files, the ID is often the filename itself, e.g., 'case01.vital' -> 'case01')
        2. Infer the clinical context based on track names (e.g., Anesthesia, ICU, Sleep Study).
           (Hint: 'ART'/'ABP' usually means Arterial Blood Pressure, 'ECG' means Electrocardiogram)
        """
        return context