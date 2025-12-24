import os
import re
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
    
    [UPDATED] LLM 기반 유연한 ID 추론:
    - 파일명 패턴을 LLM이 분석하여 ID 타입(caseid, patient_id, subject_id 등) 추론
    - 확신도가 낮으면 사용자에게 확인 요청
    - 다양한 데이터셋에 대응 가능
    """

    def can_handle(self, file_path: str) -> bool:
        """처리 가능한 파일 확장자 확인"""
        ext = file_path.lower().split('.')[-1]
        return ext in ['vital', 'edf', 'bdf', 'wfdb']
    
    def extract_id_from_filename(self, file_path: str) -> Dict[str, Any]:
        """
        [Rule] 파일명에서 ID 후보 추출 (Rule-based preprocessing)
        
        LLM이 최종 판단하기 전에 Rule로 힌트를 수집합니다.
        
        Returns:
            {
                "filename": str,
                "name_without_ext": str,
                "has_numeric_id": bool,
                "numeric_candidates": list,  # 숫자 후보들
                "prefix_hints": list,  # 접두사 힌트 (case_, patient_, subject_ 등)
                "pattern_type": str  # "pure_numeric", "prefixed_numeric", "alphanumeric", "unknown"
            }
        """
        basename = os.path.basename(file_path)
        name_without_ext = os.path.splitext(basename)[0]
        
        result = {
            "filename": basename,
            "name_without_ext": name_without_ext,
            "has_numeric_id": False,
            "numeric_candidates": [],
            "prefix_hints": [],
            "pattern_type": "unknown"
        }
        
        # 패턴 1: 순수 숫자 (0001, 0042, 123)
        if name_without_ext.isdigit():
            result["has_numeric_id"] = True
            result["numeric_candidates"] = [int(name_without_ext)]
            result["pattern_type"] = "pure_numeric"
            return result
        
        # 패턴 2: 접두사 + 숫자 (case_123, patient_0042, subject_001)
        prefix_patterns = [
            (r'^(case)[_-]?(\d+)', "case"),
            (r'^(patient)[_-]?(\d+)', "patient"),
            (r'^(subject)[_-]?(\d+)', "subject"),
            (r'^(subj)[_-]?(\d+)', "subject"),
            (r'^(pt)[_-]?(\d+)', "patient"),
            (r'^(id)[_-]?(\d+)', "id"),
            (r'^(rec)[_-]?(\d+)', "record"),
        ]
        
        for pattern, prefix_type in prefix_patterns:
            match = re.match(pattern, name_without_ext.lower())
            if match:
                result["has_numeric_id"] = True
                result["numeric_candidates"] = [int(match.group(2))]
                result["prefix_hints"].append(prefix_type)
                result["pattern_type"] = "prefixed_numeric"
                return result
        
        # 패턴 3: 일반 숫자 추출 (any_name_123)
        numbers = re.findall(r'\d+', name_without_ext)
        if numbers:
            result["has_numeric_id"] = True
            result["numeric_candidates"] = [int(n) for n in numbers]
            result["pattern_type"] = "alphanumeric"
        
        return result

    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        [Rule Prepares, LLM Decides]
        라이브러리를 사용하여 트랙 정보, 단위, 샘플링 레이트 등을 추출합니다.
        실제 파형 데이터(Waveform)는 로드하지 않습니다.
        
        ID 추론은 LLM이 담당하며, 확신도가 낮으면 사용자에게 확인을 요청합니다.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # [Rule] 파일명에서 ID 힌트 추출
        filename_analysis = self.extract_id_from_filename(file_path)
        
        # 기본 메타데이터 구조 초기화
        metadata = {
            "processor_type": "signal",
            "file_path": file_path,
            "file_size_mb": round(os.path.getsize(file_path) / (1024 * 1024), 2),
            "columns": [],        # 트랙명 리스트 (LLM이 의미 추론용) -> Tabular의 columns와 매핑
            "column_details": {}, # 트랙별 상세 정보 (단위, SR)
            "duration": 0.0,
            "is_time_series": True, # 신호 데이터는 본질적으로 시계열
            "filename_analysis": filename_analysis,  # [NEW] Rule이 분석한 파일명 정보
            "is_vital_file": False  # vitaldb 파일 여부
        }

        ext = file_path.lower().split('.')[-1]
        error_msg = None

        # --- Strategy 1: VitalDB (.vital) ---
        if ext == 'vital':
            metadata["is_vital_file"] = True  # [NEW] vitaldb 파일 마킹
            
            if not VITALDB_AVAILABLE:
                error_msg = "vitaldb library is not installed. Please install it with: pip install vitaldb"
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
                    
                    # [NEW] Duration 계산 개선
                    try:
                        # vitaldb에서 duration 추출 시도
                        if hasattr(vf, 'get_track_names') and len(track_names) > 0:
                            first_track = track_names[0]
                            vals = vf.get_samples(first_track)
                            if vals is not None and len(vals) > 0:
                                dt = vf.trks.get(first_track, {}).get('dt', 1)
                                metadata["duration"] = len(vals) * dt
                    except:
                        metadata["duration"] = 0.0

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
            metadata["error"] = error_msg
            # 에러가 있어도 LLM에게 파일명 분석 요청
            context_summary = self._create_signal_context(metadata, filename_analysis)
            anchor_result = self._ask_llm_to_identify_anchor(context_summary)
            metadata["anchor_info"] = self._format_anchor_result(anchor_result, filename_analysis)
            return metadata

        # --- [LLM Decides] base.py의 통합 메서드 사용 ---
        # Rule이 수집한 정보를 context_summary로 정리하여 LLM에게 전달
        context_summary = self._create_signal_context(metadata, filename_analysis)
        anchor_result = self._ask_llm_to_identify_anchor(context_summary)
        metadata["anchor_info"] = self._format_anchor_result(anchor_result, filename_analysis)

        return metadata
    
    def _format_anchor_result(self, anchor_result, filename_analysis: Dict) -> Dict[str, Any]:
        """
        [Helper] AnchorResult를 signal 파일용 anchor_info로 변환
        
        base.py의 AnchorResult에 signal 파일 특화 정보를 추가합니다.
        """
        # 파일명에서 ID 값 추출 (Rule에서 이미 분석한 결과 사용)
        numeric_candidates = filename_analysis.get("numeric_candidates", [])
        name_without_ext = filename_analysis.get("name_without_ext", "")
        
        # ID 값 결정: LLM이 column_name을 찾았으면 숫자 후보에서 값 추출
        if numeric_candidates:
            id_value = numeric_candidates[-1]  # 마지막 숫자 사용
        else:
            id_value = name_without_ext
        
        return {
            "status": anchor_result.status,
            "target_column": anchor_result.column_name,
            "id_value": id_value,
            "is_time_series": anchor_result.is_time_series,
            "confidence": anchor_result.confidence,
            "reasoning": anchor_result.reasoning,
            "needs_human_confirmation": anchor_result.needs_human_confirmation,
            "msg": f"LLM inferred: {anchor_result.column_name}={id_value} (confidence: {anchor_result.confidence:.0%})"
        }

    def _create_signal_context(self, metadata: Dict, filename_analysis: Dict = None) -> str:
        """
        [Rule Prepares] LLM에게 보낼 Signal 데이터 요약본 생성.
        
        TabularProcessor와 동일한 패턴:
        - Rule이 수집한 정보를 정리하여 context_summary 생성
        - LLM은 이 정보를 바탕으로 Anchor를 결정
        
        Signal 파일의 특성:
        - 파일명에서 ID 추출 (0001.vital → caseid=1)
        - 트랙명과 단위로 임상 맥락 추론 (ECG, SpO2, ART 등)
        """
        filename = os.path.basename(metadata["file_path"])
        tracks = metadata.get("columns", [])
        file_size = metadata.get("file_size_mb", 0)
        column_details = metadata.get("column_details", {})
        
        # 파일명 분석 결과 (Rule에서 추출)
        if filename_analysis is None:
            filename_analysis = metadata.get("filename_analysis", {})
        
        pattern_type = filename_analysis.get("pattern_type", "unknown")
        numeric_candidates = filename_analysis.get("numeric_candidates", [])
        prefix_hints = filename_analysis.get("prefix_hints", [])
        name_without_ext = filename_analysis.get("name_without_ext", "")
        
        # 트랙 상세 정보 구성 (TabularProcessor의 column_details와 유사)
        track_details_str = ""
        for i, track_name in enumerate(tracks[:10]):  # 상위 10개만
            details = column_details.get(track_name, {})
            unit = details.get("unit", "N/A")
            sr = details.get("sample_rate", 0)
            col_type = details.get("column_type", "unknown")
            min_val = details.get("min_val", "N/A")
            max_val = details.get("max_val", "N/A")
            
            track_details_str += (
                f"- Track: '{track_name}' | Unit: {unit} | "
                f"Sample Rate: {sr}Hz | Type: {col_type}"
            )
            if min_val != "N/A" and max_val != "N/A":
                track_details_str += f" | Range: [{min_val}, {max_val}]"
            track_details_str += "\n"
        
        if len(tracks) > 10:
            track_details_str += f"  ... and {len(tracks) - 10} more tracks\n"
        
        # 트랙명 요약 (LLM이 임상 맥락 파악용)
        track_names_summary = ", ".join(tracks[:15])
        if len(tracks) > 15:
            track_names_summary += f", ... (+{len(tracks)-15} more)"

        context = f"""Dataset Type: Bio-Signal (Waveform/Vital Signs)
File Name: {filename}
File Size: {file_size} MB
Duration: {metadata.get('duration', 0):.1f} seconds

[FILENAME ANALYSIS - Pre-processed by Rules]
- Original Name: {name_without_ext}
- Pattern Type: {pattern_type}
- Numeric Candidates: {numeric_candidates}
- Prefix Hints: {prefix_hints}

[SIGNAL TRACKS OVERVIEW]
Total Tracks: {len(tracks)}
Track Names: [{track_names_summary}]

[TRACK DETAILS - Similar to Tabular Columns]
{track_details_str}
[CLINICAL CONTEXT HINTS]
- If tracks include 'ECG', 'SpO2', 'ART', 'NIBP' → Anesthesia/OR monitoring
- If tracks include 'EEG', 'EMG', 'EOG' → Sleep study or neuro monitoring  
- If tracks include 'HR', 'RR', 'Temp' → General vital signs

[IMPORTANT FOR ID IDENTIFICATION]
- Signal files typically use FILENAME as the patient/case identifier
- Pattern '{pattern_type}' with numeric candidates {numeric_candidates} suggests the ID type
- If prefix_hints contains 'patient' or 'subject', use that as the ID column name
- If pure numeric (like '0001'), it's likely a caseid or record_id
"""
        return context