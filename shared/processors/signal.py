# shared/processors/signal.py
"""
Signal Processor - 생체신호 데이터 처리 (.vital, .edf)

두 가지 모드:
1. extract_metadata(): 헤더만 읽어 메타데이터 추출 (빠름, IndexingAgent용)
2. load_data(): 실제 신호 데이터 로드 (느림, DataContext용)
"""

import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
import pandas as pd

from .base import BaseDataProcessor

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
    생체신호 데이터(.vital, .edf)를 처리하는 프로세서.
    
    기능:
    1. extract_metadata(): 메타데이터 추출 (녹화 정보, 장치, 트랙 등)
    2. load_data(): 실제 신호 데이터 로드 (선택적 트랙, 시간 범위)
    
    추출 정보:
    - Global: 녹화 시작/종료 시간, duration, GMT offset
    - Device: 장치 목록, 타입, 포트
    - Track: 이름, 단위, 샘플링 레이트, 타입, 스케일링 정보
    """
    
    # 지원 확장자
    SUPPORTED_EXTENSIONS = {"vital", "edf", "bdf"}

    # Track type 매핑 (vitaldb 내부 타입 코드)
    TRACK_TYPE_MAP = {
        1: "waveform",      # 고주파 파형 데이터
        2: "numeric",       # 숫자형 트렌드 데이터
        5: "event",         # 이벤트 마커
    }

    def can_handle(self, file_path: str) -> bool:
        """처리 가능한 파일 확장자 확인"""
        ext = file_path.lower().split('.')[-1]
        return ext in self.SUPPORTED_EXTENSIONS
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 1. extract_metadata() - IndexingAgent용
    # ═══════════════════════════════════════════════════════════════════════════
    
    def extract_filename_info(self, file_path: str) -> Dict[str, Any]:
        """파일명 정보를 추출합니다."""
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
        생체신호 파일에서 메타데이터를 추출합니다.
        
        Returns:
            메타데이터 딕셔너리
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
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 2. load_data() - DataContext용
    # ═══════════════════════════════════════════════════════════════════════════
    
    def load_data(
        self,
        file_path: str,
        columns: Optional[List[str]] = None,
        time_range: Optional[Tuple[float, float]] = None,
        resample_interval: float = 1.0
    ) -> pd.DataFrame:
        """
        .vital 파일에서 실제 신호 데이터 로드
        
        Args:
            file_path: .vital 파일 경로
            columns: 로드할 트랙 이름 (None이면 전체)
                예: ["Solar8000/HR", "Solar8000/NIBP_SBP"]
            time_range: (start_sec, end_sec) 시간 범위 (None이면 전체)
            resample_interval: 리샘플링 간격 (초, 기본 1초)
        
        Returns:
            DataFrame with columns: [Time, track1, track2, ...]
        """
        ext = file_path.lower().split('.')[-1]
        
        if ext == 'vital':
            return self._load_vital_data(file_path, columns, time_range, resample_interval)
        elif ext in ['edf', 'bdf']:
            return self._load_edf_data(file_path, columns, time_range, resample_interval)
        else:
            raise ValueError(f"Unsupported file extension: {ext}")
    
    def _load_vital_data(
        self,
        file_path: str,
        columns: Optional[List[str]] = None,
        time_range: Optional[Tuple[float, float]] = None,
        resample_interval: float = 1.0
    ) -> pd.DataFrame:
        """VitalDB .vital 파일 데이터 로드"""
        if not VITALDB_AVAILABLE:
            raise ImportError("vitaldb library required. Install with: pip install vitaldb")
        
        # 전체 데이터 로드 (header_only=False)
        vf = vitaldb.VitalFile(file_path)
        
        # 사용 가능한 트랙 확인
        available = list(vf.trks.keys())
        
        # 트랙 선택
        if columns:
            selected = [c for c in columns if c in available]
            if not selected:
                print(f"Warning: No matching tracks found. Available: {available[:10]}...")
                return pd.DataFrame()
        else:
            selected = available
        
        # 데이터 추출
        data = {}
        for track_name in selected:
            try:
                # vitaldb.to_numpy(): 지정된 interval로 리샘플링된 데이터 반환
                vals = vf.to_numpy(track_name, interval=resample_interval)
                if vals is not None and len(vals) > 0:
                    # vitaldb는 (N, 1) 형태의 2D 배열을 반환할 수 있음 -> 1D로 평탄화
                    import numpy as np
                    if isinstance(vals, np.ndarray) and vals.ndim == 2 and vals.shape[1] == 1:
                        vals = vals.flatten()
                    data[track_name] = vals
            except Exception as e:
                print(f"Warning: Failed to load {track_name}: {e}")
        
        if not data:
            return pd.DataFrame()
        
        # DataFrame 생성
        max_len = max(len(v) for v in data.values())
        df = pd.DataFrame({
            "Time": [i * resample_interval for i in range(max_len)]
        })
        
        for track_name, vals in data.items():
            # 길이 맞추기 (padding with NaN)
            padded = list(vals) + [None] * (max_len - len(vals))
            df[track_name] = padded
        
        # 시간 범위 필터링
        if time_range:
            start, end = time_range
            df = df[(df["Time"] >= start) & (df["Time"] <= end)]
        
        return df
    
    def _load_edf_data(
        self,
        file_path: str,
        columns: Optional[List[str]] = None,
        time_range: Optional[Tuple[float, float]] = None,
        resample_interval: float = 1.0
    ) -> pd.DataFrame:
        """MNE .edf/.bdf 파일 데이터 로드"""
        if not MNE_AVAILABLE:
            raise ImportError("mne library required. Install with: pip install mne")
        
        ext = file_path.lower().split('.')[-1]
        if ext == 'edf':
            raw = mne.io.read_raw_edf(file_path, preload=True, verbose=False)
        else:
            raw = mne.io.read_raw_bdf(file_path, preload=True, verbose=False)
        
        # 채널 선택
        if columns:
            available = raw.ch_names
            selected = [c for c in columns if c in available]
            if selected:
                raw = raw.pick_channels(selected)
        
        # 데이터 추출
        data, times = raw.get_data(return_times=True)
        
        # DataFrame 생성
        df = pd.DataFrame({"Time": times})
        for i, ch_name in enumerate(raw.ch_names):
            df[ch_name] = data[i]
        
        # 시간 범위 필터링
        if time_range:
            start, end = time_range
            df = df[(df["Time"] >= start) & (df["Time"] <= end)]
        
        # 리샘플링 (간단한 다운샘플링)
        if resample_interval > 0:
            current_interval = times[1] - times[0] if len(times) > 1 else 1.0
            if resample_interval > current_interval:
                step = int(resample_interval / current_interval)
                df = df.iloc[::step].reset_index(drop=True)
        
        return df
    
    def get_available_columns(self, file_path: str) -> List[str]:
        """
        파일에서 사용 가능한 트랙 목록 반환 (데이터 로드 없이)
        
        header_only=True로 빠르게 조회
        """
        ext = file_path.lower().split('.')[-1]
        
        if ext == 'vital':
            if not VITALDB_AVAILABLE:
                return []
            vf = vitaldb.VitalFile(file_path, header_only=True)
            return list(vf.trks.keys())
        
        elif ext in ['edf', 'bdf']:
            if not MNE_AVAILABLE:
                return []
            if ext == 'edf':
                raw = mne.io.read_raw_edf(file_path, preload=False, verbose=False)
            else:
                raw = mne.io.read_raw_bdf(file_path, preload=False, verbose=False)
            return raw.ch_names
        
        return []
    
    def get_recording_info(self, file_path: str) -> Dict[str, Any]:
        """
        녹화 정보만 빠르게 조회 (시작/종료 시간, duration 등)
        """
        metadata = self.extract_metadata(file_path)
        return {
            "recording_info": metadata.get("recording_info", {}),
            "duration": metadata.get("duration", 0),
            "duration_minutes": metadata.get("duration_minutes", 0),
            "duration_hours": metadata.get("duration_hours", 0),
        }

