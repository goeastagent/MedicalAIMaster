import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# Base Class 임포트
from .base import BaseDataProcessor
from src.config import ProcessingConfig

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
    생체신호 데이터(.vital, .edf)를 파싱하여 최대한 많은 메타데이터를 추출하는 프로세서.
    
    추출 정보:
    - Global: 녹화 시작/종료 시간, duration, GMT offset
    - Device: 장치 목록, 타입, 포트
    - Track: 이름, 단위, 샘플링 레이트, 타입, 스케일링 정보, 표시 범위, 통계
    
    파일명 기반 식별:
    - 파일명 자체를 식별자로 사용 (다양한 데이터셋 대응)
    - 파일명이 ID일 수도 있고 아닐 수도 있으므로, 일반적으로 filename으로 처리
    """

    # Track type 매핑 (vitaldb 내부 타입 코드)
    TRACK_TYPE_MAP = {
        1: "waveform",      # 고주파 파형 데이터
        2: "numeric",       # 숫자형 트렌드 데이터
        5: "event",         # 이벤트 마커
    }

    def can_handle(self, file_path: str) -> bool:
        """처리 가능한 파일 확장자 확인"""
        ext = file_path.lower().split('.')[-1]
        return ext in ProcessingConfig.SIGNAL_EXTENSIONS
    
    def extract_filename_info(self, file_path: str) -> Dict[str, Any]:
        """
        파일명 정보를 추출합니다.
        
        다양한 데이터셋에서 파일명이 반드시 ID 형태가 아닐 수 있으므로,
        단순히 파일명 자체를 식별자로 사용합니다.
        
        Returns:
            {
                "filename": str,           # 전체 파일명 (확장자 포함)
                "name_without_ext": str    # 확장자 제외 파일명
            }
        """
        basename = os.path.basename(file_path)
        name_without_ext = os.path.splitext(basename)[0]
        
        return {
            "filename": basename,
            "name_without_ext": name_without_ext
        }
    
    def _unix_to_datetime_str(self, unix_timestamp: float) -> Optional[str]:
        """Unix timestamp를 ISO 형식 문자열로 변환"""
        try:
            if unix_timestamp and unix_timestamp > 0:
                dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
                return dt.isoformat().replace("+00:00", "Z")
        except (ValueError, OSError):
            pass
        return None
    
    def _extract_vital_metadata(self, file_path: str, metadata: Dict[str, Any]) -> Optional[str]:
        """
        VitalDB .vital 파일에서 모든 메타데이터를 추출합니다.
        
        Returns:
            error_msg: 에러 발생 시 에러 메시지, 정상이면 None
        """
        if not VITALDB_AVAILABLE:
            return "vitaldb library is not installed. Please install it with: pip install vitaldb"
        
        try:
            # VitalFile 로드 (header_only=True로 빠르게 헤더만 읽기)
            vf = vitaldb.VitalFile(file_path, header_only=True)
            
            # ===== 1. Global Info 추출 =====
            metadata["recording_info"] = {
                "start_time_unix": vf.dtstart if hasattr(vf, 'dtstart') else None,
                "end_time_unix": vf.dtend if hasattr(vf, 'dtend') else None,
                "start_time_iso": self._unix_to_datetime_str(vf.dtstart) if hasattr(vf, 'dtstart') else None,
                "end_time_iso": self._unix_to_datetime_str(vf.dtend) if hasattr(vf, 'dtend') else None,
                "gmt_offset": vf.dgmt if hasattr(vf, 'dgmt') else None,
            }
            
            # Duration 계산 (초 단위)
            if hasattr(vf, 'dtstart') and hasattr(vf, 'dtend') and vf.dtend and vf.dtstart:
                duration_sec = vf.dtend - vf.dtstart
                metadata["duration"] = round(duration_sec, 2)
                metadata["duration_minutes"] = round(duration_sec / 60, 2)
                metadata["duration_hours"] = round(duration_sec / 3600, 2)
            
            # ===== 2. Device Info 추출 =====
            devices = {}
            if hasattr(vf, 'devs'):
                for dev_name, dev in vf.devs.items():
                    devices[dev_name] = {
                        "name": dev.name if hasattr(dev, 'name') else dev_name,
                        "type": dev.type if hasattr(dev, 'type') else None,
                        "port": dev.port if hasattr(dev, 'port') else None,
                    }
            metadata["devices"] = devices
            metadata["device_count"] = len(devices)
            metadata["device_names"] = list(devices.keys())
            
            # ===== 3. Track Info 추출 =====
            track_names = []
            track_details = {}
            
            # Track 타입별 분류
            waveform_tracks = []
            numeric_tracks = []
            event_tracks = []
            
            for trk_name, trk in vf.trks.items():
                track_names.append(trk_name)
                
                # Track 객체에서 속성 추출
                srate = trk.srate if hasattr(trk, 'srate') else 0.0
                trk_type = trk.type if hasattr(trk, 'type') else 0
                trk_type_name = self.TRACK_TYPE_MAP.get(trk_type, f"unknown_{trk_type}")
                
                # Track 상세 정보
                track_info = {
                    "column_name": trk_name,
                    "short_name": trk.name if hasattr(trk, 'name') else trk_name,
                    "device_name": trk.dname if hasattr(trk, 'dname') else None,
                    "unit": trk.unit if hasattr(trk, 'unit') else "",
                    "sample_rate": srate,
                    "track_type_code": trk_type,
                    "track_type": trk_type_name,
                    "column_type": "waveform" if srate > 1 else "numeric_trend",
                    
                    # 스케일링 정보
                    "scaling": {
                        "gain": trk.gain if hasattr(trk, 'gain') else 1.0,
                        "offset": trk.offset if hasattr(trk, 'offset') else 0.0,
                        "format": trk.fmt if hasattr(trk, 'fmt') else None,
                    },
                    
                    # 표시 범위 (의료 기기의 정상 범위 힌트)
                    "display_range": {
                        "min": trk.mindisp if hasattr(trk, 'mindisp') else None,
                        "max": trk.maxdisp if hasattr(trk, 'maxdisp') else None,
                    },
                    
                    # 모니터 타입
                    "monitor_type": trk.montype if hasattr(trk, 'montype') else None,
                    
                    # 레코드 수 (header_only=True면 0일 수 있음)
                    "record_count": len(trk.recs) if hasattr(trk, 'recs') else 0,
                    
                    # 샘플 데이터 (나중에 추가 가능)
                    "samples": [],
                }
                
                track_details[trk_name] = track_info
                
                # 타입별 분류
                if trk_type == 1:
                    waveform_tracks.append(trk_name)
                elif trk_type == 2:
                    numeric_tracks.append(trk_name)
                elif trk_type == 5:
                    event_tracks.append(trk_name)
            
            metadata["columns"] = track_names
            metadata["column_details"] = track_details
            metadata["track_count"] = len(track_names)
            
            # Track 타입별 요약
            metadata["track_summary"] = {
                "waveform_count": len(waveform_tracks),
                "waveform_tracks": waveform_tracks,
                "numeric_count": len(numeric_tracks),
                "numeric_tracks": numeric_tracks,
                "event_count": len(event_tracks),
                "event_tracks": event_tracks,
            }
            
            # 샘플링 레이트 요약
            sample_rates = [t["sample_rate"] for t in track_details.values() if t["sample_rate"] > 0]
            if sample_rates:
                metadata["sample_rate_summary"] = {
                    "unique_rates": sorted(list(set(sample_rates))),
                    "max_rate": max(sample_rates),
                    "min_rate": min(sample_rates),
                }
            
            # 단위 요약
            units = [t["unit"] for t in track_details.values() if t["unit"]]
            metadata["unique_units"] = sorted(list(set(units)))
            
            return None  # 성공
            
        except Exception as e:
            return f"VitalDB parsing error: {str(e)}"
    
    def _extract_edf_metadata(self, file_path: str, metadata: Dict[str, Any]) -> Optional[str]:
        """
        MNE를 사용하여 .edf/.bdf 파일에서 메타데이터를 추출합니다.
        
        Returns:
            error_msg: 에러 발생 시 에러 메시지, 정상이면 None
        """
        if not MNE_AVAILABLE:
            return "mne library is not installed. Please install it to process .edf/.bdf files."
        
        try:
            # preload=False로 설정하여 헤더만 읽음
            ext = file_path.lower().split('.')[-1]
            if ext == 'edf':
                raw = mne.io.read_raw_edf(file_path, preload=False, verbose=False)
            else:  # bdf
                raw = mne.io.read_raw_bdf(file_path, preload=False, verbose=False)
            
            # Global info
            metadata["recording_info"] = {
                "meas_date": str(raw.info['meas_date']) if raw.info.get('meas_date') else None,
                "subject_info": raw.info.get('subject_info', {}),
            }
            
            metadata["duration"] = raw.times[-1] if raw.times.size > 0 else 0
            metadata["duration_minutes"] = round(metadata["duration"] / 60, 2)
            metadata["duration_hours"] = round(metadata["duration"] / 3600, 2)
            
            # Channel info
            metadata["columns"] = raw.ch_names
            metadata["track_count"] = len(raw.ch_names)
            
            column_details = {}
            for ch in raw.ch_names:
                ch_idx = raw.ch_names.index(ch)
                sr = raw.info['sfreq']
                
                column_details[ch] = {
                    "column_name": ch,
                    "sample_rate": sr,
                    "unit": "V",  # EDF는 기본적으로 전압
                    "column_type": "waveform",
                    "track_type": "waveform",
                    "channel_type": mne.channel_type(raw.info, ch_idx) if hasattr(mne, 'channel_type') else None,
                    "samples": [],
                }
            
            metadata["column_details"] = column_details
            metadata["sample_rate_summary"] = {
                "unique_rates": [raw.info['sfreq']],
                "max_rate": raw.info['sfreq'],
                "min_rate": raw.info['sfreq'],
            }
            
            return None  # 성공
            
        except Exception as e:
            return f"MNE parsing error: {str(e)}"

    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        생체신호 파일에서 최대한 많은 메타데이터를 추출합니다.
        
        추출 정보:
        - 파일 기본 정보: 경로, 크기, 확장자
        - 녹화 정보: 시작/종료 시간, duration
        - 장치 정보: 장치 목록, 타입, 포트
        - 트랙 정보: 이름, 단위, 샘플링 레이트, 타입, 스케일링, 표시 범위
        - 요약 정보: 트랙 타입별 개수, 샘플링 레이트 범위
        
        Entity Identifier 감지와 시맨틱 분석은 Analyzer에서 수행합니다.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # 파일명 정보 추출
        filename_info = self.extract_filename_info(file_path)
        ext = file_path.lower().split('.')[-1]
        
        # 기본 메타데이터 구조 초기화
        metadata = {
            "processor_type": "signal",
            "file_path": file_path,
            "file_extension": ext,
            "file_size_bytes": os.path.getsize(file_path),
            "file_size_mb": round(os.path.getsize(file_path) / (1024 * 1024), 2),
            "columns": [],
            "column_details": {},
            "duration": 0.0,
            "duration_minutes": 0.0,
            "duration_hours": 0.0,
            "is_time_series": True,
            "filename_info": filename_info,
            "is_vital_file": ext == 'vital',
            "recording_info": {},
            "devices": {},
            "device_count": 0,
            "device_names": [],
            "track_count": 0,
            "track_summary": {},
            "sample_rate_summary": {},
            "unique_units": [],
            # NOTE: entity_info는 Analyzer에서 LLM이 결정
        }

        error_msg = None

        # --- Strategy 1: VitalDB (.vital) ---
        if ext == 'vital':
            error_msg = self._extract_vital_metadata(file_path, metadata)

        # --- Strategy 2: MNE (.edf, .bdf) ---
        elif ext in ['edf', 'bdf']:
            error_msg = self._extract_edf_metadata(file_path, metadata)

        # 에러 발생 시 기록
        if error_msg:
            metadata["error"] = error_msg

        return metadata
