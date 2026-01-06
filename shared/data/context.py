# shared/data/context.py
"""
DataContext - Execution Plan 기반 데이터 로드 및 관리

역할:
1. ExtractionAgent의 execution_plan JSON 해석
2. DB에서 파일 경로 resolve
3. Processor를 사용하여 데이터 로드
4. 캐싱 (클래스 레벨, 모든 인스턴스 공유)
5. AnalysisAgent를 위한 분석 컨텍스트 제공

사용 예시:
    ctx = DataContext()
    ctx.load_from_plan(execution_plan)
    
    cohort = ctx.get_cohort()
    signals = ctx.get_signals(caseid="1234")
    merged = ctx.get_merged_data()
    
    # AnalysisAgent용
    analysis_ctx = ctx.get_analysis_context()
    stats = ctx.compute_statistics()
"""

import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Iterator, Tuple
from datetime import datetime
import pandas as pd

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from shared.processors import SignalProcessor, TabularProcessor
from shared.database.connection import get_db_manager


class DataContext:
    """
    Execution Plan 기반 데이터 로드 및 관리
    
    특징:
    - 클래스 레벨 캐시: 모든 인스턴스가 signal/cohort 데이터 공유
    - Lazy Loading: 요청 시에만 데이터 로드
    - Temporal Filter: surgery_window 등 자동 적용
    - AnalysisAgent 지원: LLM용 컨텍스트 생성
    """
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Class-level Cache (모든 인스턴스 공유)
    # ═══════════════════════════════════════════════════════════════════════════
    _signal_cache: Dict[str, pd.DataFrame] = {}   # caseid → signals DataFrame
    _cohort_cache: Dict[str, pd.DataFrame] = {}   # file_id → cohort DataFrame
    
    def __init__(self):
        """DataContext 초기화"""
        # Instance state
        self._plan: Optional[Dict[str, Any]] = None
        self._loaded_at: Optional[datetime] = None
        
        # Parsed plan components
        self._cohort_file_id: Optional[str] = None
        self._cohort_file_path: Optional[str] = None
        self._cohort_entity_id: Optional[str] = None
        self._cohort_filters: List[Dict[str, Any]] = []
        
        self._signal_group_id: Optional[str] = None
        self._signal_files: List[Dict[str, Any]] = []  # [{file_id, file_path, caseid}, ...]
        self._param_keys: List[str] = []
        self._param_info: List[Dict[str, Any]] = []  # [{term, param_key, semantic_name, unit}, ...]
        self._temporal_config: Dict[str, Any] = {}
        
        self._join_config: Dict[str, Any] = {}
        
        # Processors
        self._signal_processor = SignalProcessor()
        self._tabular_processor = TabularProcessor()
        
        # DB
        self._db = None
    
    @property
    def db(self):
        """Lazy DB connection"""
        if self._db is None:
            self._db = get_db_manager()
        return self._db
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Main Interface
    # ═══════════════════════════════════════════════════════════════════════════
    
    def load_from_plan(
        self, 
        execution_plan: Dict[str, Any],
        preload_cohort: bool = True
    ) -> "DataContext":
        """
        Execution Plan을 해석하고 데이터 로드 준비
        
        Args:
            execution_plan: ExtractionAgent가 생성한 plan JSON
            preload_cohort: cohort 데이터를 미리 로드할지 (기본 True)
        
        Returns:
            self (method chaining 지원)
        """
        self._plan = execution_plan
        plan = execution_plan.get("execution_plan", {})
        
        # 1. Cohort source 파싱
        cohort_source = plan.get("cohort_source", {})
        if cohort_source:
            self._cohort_file_id = cohort_source.get("file_id")
            self._cohort_entity_id = cohort_source.get("entity_identifier", "caseid")
            self._cohort_filters = cohort_source.get("filters", [])
            
            # DB에서 파일 경로 resolve
            if self._cohort_file_id:
                self._cohort_file_path = self._resolve_file_path(self._cohort_file_id)
        
        # 2. Signal source 파싱
        signal_source = plan.get("signal_source", {})
        if signal_source:
            self._signal_group_id = signal_source.get("group_id")
            self._temporal_config = signal_source.get("temporal_alignment", {})
            
            # Parameters 파싱
            parameters = signal_source.get("parameters", [])
            self._param_info = parameters
            self._param_keys = []
            for p in parameters:
                self._param_keys.extend(p.get("param_keys", []))
            
            # DB에서 signal 파일들 resolve
            if self._signal_group_id:
                self._signal_files = self._resolve_signal_files(self._signal_group_id)
        
        # 3. Join 설정 파싱
        join_spec = plan.get("join_specification", {})
        self._join_config = {
            "cohort_key": join_spec.get("cohort_key", self._cohort_entity_id),
            "signal_key": join_spec.get("signal_key", self._cohort_entity_id),
            "type": join_spec.get("type", "inner")
        }
        
        self._loaded_at = datetime.now()
        
        # 4. Cohort 미리 로드 (선택적)
        if preload_cohort and self._cohort_file_path:
            self._load_cohort_to_cache()
        
        return self
    
    def get_cohort(self, columns: Optional[List[str]] = None) -> pd.DataFrame:
        """
        필터가 적용된 Cohort 데이터 반환
        
        Args:
            columns: 특정 컬럼만 선택 (None이면 전체)
        
        Returns:
            DataFrame
        """
        if not self._cohort_file_id:
            return pd.DataFrame()
        
        # 캐시 확인
        if self._cohort_file_id not in DataContext._cohort_cache:
            self._load_cohort_to_cache()
        
        df = DataContext._cohort_cache.get(self._cohort_file_id, pd.DataFrame())
        
        # 필터 적용
        df = self._apply_cohort_filters(df)
        
        # 컬럼 선택
        if columns:
            available = [c for c in columns if c in df.columns]
            # 항상 entity_id 포함
            if self._cohort_entity_id and self._cohort_entity_id not in available:
                available.insert(0, self._cohort_entity_id)
            df = df[available]
        
        return df
    
    def get_signals(
        self, 
        caseid: Optional[str] = None,
        param_keys: Optional[List[str]] = None,
        apply_temporal: bool = True
    ) -> pd.DataFrame:
        """
        Signal 데이터 반환
        
        Args:
            caseid: 특정 케이스만 (None이면 로드된 전체)
            param_keys: 특정 파라미터만 (None이면 plan의 모든 파라미터)
            apply_temporal: temporal_alignment 적용 여부
        
        Returns:
            DataFrame with columns: [caseid, Time, param1, param2, ...]
        """
        params = param_keys or self._param_keys
        
        if caseid:
            # 단일 케이스
            return self._get_signal_for_case(caseid, params, apply_temporal)
        else:
            # 모든 케이스
            cohort = self.get_cohort()
            case_ids = self.get_case_ids()
            
            all_signals = []
            for cid in case_ids:
                df = self._get_signal_for_case(str(cid), params, apply_temporal)
                if not df.empty:
                    df[self._join_config["signal_key"]] = cid
                    all_signals.append(df)
            
            if all_signals:
                return pd.concat(all_signals, ignore_index=True)
            return pd.DataFrame()
    
    def get_merged_data(self, how: str = "inner") -> pd.DataFrame:
        """
        Cohort + Signals 조인된 데이터 반환
        
        Args:
            how: 조인 방식 ("inner", "left", "outer")
        
        Returns:
            조인된 DataFrame
        """
        cohort_df = self.get_cohort()
        signals_df = self.get_signals()
        
        if cohort_df.empty:
            return signals_df
        if signals_df.empty:
            return cohort_df
        
        cohort_key = self._join_config.get("cohort_key", "caseid")
        signal_key = self._join_config.get("signal_key", "caseid")
        
        # 키 타입 맞추기
        if cohort_key in cohort_df.columns and signal_key in signals_df.columns:
            cohort_df[cohort_key] = cohort_df[cohort_key].astype(str)
            signals_df[signal_key] = signals_df[signal_key].astype(str)
        
        if cohort_key == signal_key:
            return pd.merge(cohort_df, signals_df, on=cohort_key, how=how)
        else:
            return pd.merge(
                cohort_df, signals_df, 
                left_on=cohort_key, right_on=signal_key, 
                how=how
            )
    
    def iter_cases(
        self,
        param_keys: Optional[List[str]] = None,
        apply_temporal: bool = True
    ) -> Iterator[Dict[str, Any]]:
        """
        케이스별 데이터 Iterator (대용량 처리용)
        
        Yields:
            {
                "caseid": str,
                "cohort": pd.Series,      # 해당 케이스의 메타데이터
                "signals": pd.DataFrame,  # 해당 케이스의 신호 데이터
                "temporal_range": (start, end) or None
            }
        """
        cohort_df = self.get_cohort()
        case_ids = self.get_case_ids()
        
        for cid in case_ids:
            # Cohort row
            cohort_key = self._join_config.get("cohort_key", "caseid")
            cohort_row = cohort_df[cohort_df[cohort_key].astype(str) == str(cid)]
            cohort_series = cohort_row.iloc[0] if not cohort_row.empty else pd.Series()
            
            # Signals
            signals = self._get_signal_for_case(str(cid), param_keys, apply_temporal)
            
            # Temporal range
            temporal_range = None
            if apply_temporal and not cohort_series.empty:
                temporal_range = self._get_temporal_range(cohort_series)
            
            yield {
                "caseid": str(cid),
                "cohort": cohort_series,
                "signals": signals,
                "temporal_range": temporal_range
            }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Query Helpers
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_case_ids(self, signals_only: bool = True) -> List[str]:
        """케이스 ID 목록 반환
        
        Args:
            signals_only: True면 Signal 파일이 있는 케이스만 반환 (기본값)
                         False면 Cohort 전체 케이스 반환
        
        Returns:
            케이스 ID 문자열 리스트
        """
        if signals_only:
            # Signal 파일이 있는 케이스만
            return [f.get("caseid") for f in self._signal_files if f.get("caseid")]
        else:
            # Cohort 전체 케이스
            cohort = self.get_cohort()
            if cohort.empty:
                return []
            
            entity_col = self._cohort_entity_id or "caseid"
            if entity_col in cohort.columns:
                return cohort[entity_col].astype(str).unique().tolist()
            return []
    
    def get_available_case_ids(self) -> List[str]:
        """분석 가능한 케이스 ID (Cohort와 Signal 교집합)"""
        cohort_ids = set(self.get_case_ids(signals_only=False))
        signal_ids = set(self.get_case_ids(signals_only=True))
        return sorted(list(cohort_ids & signal_ids))
    
    def get_available_parameters(self) -> List[str]:
        """사용 가능한 파라미터 키 목록"""
        return self._param_keys.copy()
    
    def is_loaded(self) -> bool:
        """Plan이 로드되었는지 확인"""
        return self._plan is not None
    
    def summary(self) -> Dict[str, Any]:
        """현재 상태 요약"""
        cohort_loaded = self._cohort_file_id in DataContext._cohort_cache
        signals_cached = len([
            cid for cid in self.get_case_ids() 
            if cid in DataContext._signal_cache
        ])
        
        return {
            "loaded_at": self._loaded_at.isoformat() if self._loaded_at else None,
            "cohort": {
                "file_id": self._cohort_file_id,
                "file_path": self._cohort_file_path,
                "loaded": cohort_loaded,
                "filters_count": len(self._cohort_filters),
                "total_cases": len(self.get_case_ids()) if cohort_loaded else 0
            },
            "signals": {
                "group_id": self._signal_group_id,
                "total_files": len(self._signal_files),
                "cached_count": signals_cached,
                "param_keys": self._param_keys,
                "temporal_type": self._temporal_config.get("type", "full_record")
            },
            "cache_stats": {
                "cohort_cache_size": len(DataContext._cohort_cache),
                "signal_cache_size": len(DataContext._signal_cache)
            }
        }
    
    @classmethod
    def clear_cache(cls, cache_type: str = "all") -> None:
        """
        캐시 정리
        
        Args:
            cache_type: "all", "signals", "cohort"
        """
        if cache_type in ("all", "signals"):
            cls._signal_cache.clear()
        if cache_type in ("all", "cohort"):
            cls._cohort_cache.clear()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # AnalysisAgent 지원 메서드
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_analysis_context(self) -> Dict[str, Any]:
        """
        LLM 분석을 위한 전체 컨텍스트 반환
        
        Returns:
            {
                "description": str,
                "cohort": {...},
                "signals": {...},
                "original_query": str
            }
        """
        cohort = self.get_cohort()
        case_ids = self.get_case_ids()
        
        # Cohort 정보
        cohort_info = {
            "total_cases": len(case_ids),
            "filters_applied": self._cohort_filters,
            "entity_identifier": self._cohort_entity_id,
            "columns": self._get_cohort_column_info(cohort)
        }
        
        # Signal 정보
        signal_info = {
            "parameters": self._param_info,
            "param_keys": self._param_keys,
            "temporal_setting": {
                "type": self._temporal_config.get("type", "full_record"),
                "margin_seconds": self._temporal_config.get("margin_seconds", 0),
                "start_column": self._temporal_config.get("start_column"),
                "end_column": self._temporal_config.get("end_column"),
                "description": self._get_temporal_description()
            },
            "available_files": len(self._signal_files)
        }
        
        # Description 생성
        description = self._generate_description(cohort_info, signal_info)
        
        return {
            "description": description,
            "cohort": cohort_info,
            "signals": signal_info,
            "original_query": self._plan.get("original_query", "") if self._plan else ""
        }
    
    def compute_statistics(
        self,
        param_keys: Optional[List[str]] = None,
        percentiles: List[float] = [0.25, 0.5, 0.75],
        sample_size: Optional[int] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        파라미터별 통계 계산
        
        Args:
            param_keys: 계산할 파라미터 (None이면 전체)
            percentiles: 계산할 백분위수
            sample_size: 샘플링할 케이스 수 (None이면 전체)
        
        Returns:
            {
                "Solar8000/HR": {
                    "count": int,
                    "mean": float,
                    "std": float,
                    "min": float,
                    "max": float,
                    "percentiles": {"25%": ..., "50%": ..., "75%": ...}
                }
            }
        """
        params = param_keys or self._param_keys
        case_ids = self.get_case_ids()
        
        if sample_size and sample_size < len(case_ids):
            import random
            case_ids = random.sample(case_ids, sample_size)
        
        # 모든 케이스의 데이터 수집
        all_data = {p: [] for p in params}
        
        for cid in case_ids:
            signals = self._get_signal_for_case(cid, params, apply_temporal=True)
            if signals.empty:
                continue
            
            for p in params:
                if p in signals.columns:
                    values = signals[p].dropna().tolist()
                    all_data[p].extend(values)
        
        # 통계 계산
        stats = {}
        for p in params:
            values = all_data[p]
            if not values:
                stats[p] = {"count": 0, "error": "No data available"}
                continue
            
            series = pd.Series(values)
            pct_dict = {f"{int(q*100)}%": series.quantile(q) for q in percentiles}
            
            stats[p] = {
                "count": len(values),
                "mean": round(series.mean(), 4),
                "std": round(series.std(), 4),
                "min": round(series.min(), 4),
                "max": round(series.max(), 4),
                "percentiles": {k: round(v, 4) for k, v in pct_dict.items()}
            }
        
        return stats
    
    def get_sample_data(
        self,
        n_cases: int = 3,
        n_rows_per_case: int = 5
    ) -> List[Dict[str, Any]]:
        """
        LLM에게 보여줄 샘플 데이터
        
        Args:
            n_cases: 샘플링할 케이스 수
            n_rows_per_case: 케이스당 샘플 행 수
        
        Returns:
            [
                {
                    "caseid": str,
                    "cohort_sample": {...},
                    "signal_sample": [...]
                }
            ]
        """
        case_ids = self.get_case_ids()[:n_cases]
        cohort = self.get_cohort()
        
        samples = []
        for cid in case_ids:
            # Cohort 샘플
            cohort_key = self._join_config.get("cohort_key", "caseid")
            cohort_row = cohort[cohort[cohort_key].astype(str) == str(cid)]
            cohort_sample = cohort_row.iloc[0].to_dict() if not cohort_row.empty else {}
            
            # Signal 샘플
            signals = self._get_signal_for_case(str(cid), apply_temporal=True)
            signal_sample = []
            if not signals.empty:
                sample_df = signals.head(n_rows_per_case)
                signal_sample = sample_df.to_dict(orient="records")
            
            samples.append({
                "caseid": str(cid),
                "cohort_sample": cohort_sample,
                "signal_sample": signal_sample
            })
        
        return samples
    
    def get_parameter_info(self, param_key: str) -> Optional[Dict[str, Any]]:
        """특정 파라미터의 상세 정보"""
        for p in self._param_info:
            if param_key in p.get("param_keys", []):
                return {
                    "term": p.get("term"),
                    "param_key": param_key,
                    "semantic_name": p.get("semantic_name"),
                    "unit": p.get("unit"),
                    "resolution_mode": p.get("resolution_mode"),
                    "confidence": p.get("confidence")
                }
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Private Methods - DB 조회
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _resolve_file_path(self, file_id: str) -> Optional[str]:
        """file_id → 실제 파일 경로 (DB 조회)"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT file_path FROM file_catalog
                WHERE file_id = %s
            """, (file_id,))
            
            row = cursor.fetchone()
            conn.commit()
            
            return row[0] if row else None
        except Exception as e:
            print(f"[DataContext] Error resolving file path: {e}")
            return None
    
    def _resolve_signal_files(self, group_id: str) -> List[Dict[str, Any]]:
        """group_id → 해당 그룹의 모든 signal 파일 조회"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT file_id, file_path, filename_values
                FROM file_catalog
                WHERE group_id = %s
                ORDER BY file_name
            """, (group_id,))
            
            rows = cursor.fetchall()
            conn.commit()
            
            files = []
            for row in rows:
                file_id, file_path, filename_values = row
                caseid = None
                if filename_values and isinstance(filename_values, dict):
                    caseid = filename_values.get("caseid")
                
                files.append({
                    "file_id": str(file_id),
                    "file_path": file_path,
                    "caseid": str(caseid) if caseid else None
                })
            
            return files
        except Exception as e:
            print(f"[DataContext] Error resolving signal files: {e}")
            return []
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Private Methods - 데이터 로드
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _load_cohort_to_cache(self) -> None:
        """Cohort 데이터를 캐시에 로드"""
        if not self._cohort_file_path:
            return
        
        if self._cohort_file_id in DataContext._cohort_cache:
            return  # 이미 캐시됨
        
        try:
            df = self._tabular_processor.load_data(self._cohort_file_path)
            DataContext._cohort_cache[self._cohort_file_id] = df
        except Exception as e:
            print(f"[DataContext] Error loading cohort: {e}")
    
    def _get_signal_for_case(
        self, 
        caseid: str, 
        param_keys: Optional[List[str]] = None,
        apply_temporal: bool = True
    ) -> pd.DataFrame:
        """특정 케이스의 signal 데이터 로드"""
        params = param_keys or self._param_keys
        
        # 캐시 확인
        if caseid in DataContext._signal_cache:
            df = DataContext._signal_cache[caseid]
        else:
            # 파일 찾기
            file_info = None
            for f in self._signal_files:
                if f.get("caseid") == caseid:
                    file_info = f
                    break
            
            if not file_info or not file_info.get("file_path"):
                return pd.DataFrame()
            
            # 로드
            try:
                df = self._signal_processor.load_data(
                    file_info["file_path"],
                    columns=params
                )
                DataContext._signal_cache[caseid] = df
            except Exception as e:
                print(f"[DataContext] Error loading signal for {caseid}: {e}")
                return pd.DataFrame()
        
        # 파라미터 필터링
        if params:
            available_cols = ["Time"] + [p for p in params if p in df.columns]
            df = df[available_cols] if available_cols else df
        
        # Temporal 필터 적용
        if apply_temporal and self._temporal_config.get("type", "full_record") != "full_record":
            cohort = self.get_cohort()
            cohort_key = self._join_config.get("cohort_key", "caseid")
            cohort_row = cohort[cohort[cohort_key].astype(str) == str(caseid)]
            
            if not cohort_row.empty:
                df = self._apply_temporal_filter(df, cohort_row.iloc[0])
        
        return df
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Private Methods - 필터링
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _apply_cohort_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """Cohort 필터 적용"""
        if df.empty or not self._cohort_filters:
            return df
        
        for f in self._cohort_filters:
            col = f.get("column")
            op = f.get("operator", "=")
            val = f.get("value")
            
            if col not in df.columns:
                continue
            
            op_upper = op.upper()
            
            if op_upper == "=" or op == "==":
                df = df[df[col] == val]
            elif op_upper == "!=" or op == "<>":
                df = df[df[col] != val]
            elif op_upper == ">":
                df = df[df[col] > val]
            elif op_upper == ">=":
                df = df[df[col] >= val]
            elif op_upper == "<":
                df = df[df[col] < val]
            elif op_upper == "<=":
                df = df[df[col] <= val]
            elif op_upper == "LIKE":
                pattern = str(val).replace('%', '.*')
                df = df[df[col].astype(str).str.contains(pattern, case=False, na=False, regex=True)]
            elif op_upper == "IN":
                if isinstance(val, list):
                    df = df[df[col].isin(val)]
            elif op_upper == "BETWEEN":
                if isinstance(val, (list, tuple)) and len(val) == 2:
                    df = df[(df[col] >= val[0]) & (df[col] <= val[1])]
        
        return df
    
    def _apply_temporal_filter(
        self, 
        signals_df: pd.DataFrame, 
        cohort_row: pd.Series
    ) -> pd.DataFrame:
        """Temporal alignment 적용"""
        if signals_df.empty:
            return signals_df
        
        temp_type = self._temporal_config.get("type", "full_record")
        if temp_type == "full_record":
            return signals_df
        
        margin = self._temporal_config.get("margin_seconds", 0)
        start_col = self._temporal_config.get("start_column")
        end_col = self._temporal_config.get("end_column")
        
        if not start_col or not end_col:
            return signals_df
        
        start_time = cohort_row.get(start_col)
        end_time = cohort_row.get(end_col)
        
        if pd.isna(start_time) or pd.isna(end_time):
            return signals_df
        
        # Unix timestamp로 변환
        start_sec = self._to_seconds(start_time) - margin
        end_sec = self._to_seconds(end_time) + margin
        
        if start_sec is None or end_sec is None:
            return signals_df
        
        # 필터링
        if "Time" in signals_df.columns:
            return signals_df[
                (signals_df["Time"] >= start_sec) & 
                (signals_df["Time"] <= end_sec)
            ].copy()
        
        return signals_df
    
    def _to_seconds(self, value: Any) -> Optional[float]:
        """값을 초 단위로 변환"""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, str):
            try:
                dt = pd.to_datetime(value)
                return dt.timestamp()
            except:
                pass
        return None
    
    def _get_temporal_range(self, cohort_row: pd.Series) -> Optional[Tuple[float, float]]:
        """Temporal range 계산"""
        start_col = self._temporal_config.get("start_column")
        end_col = self._temporal_config.get("end_column")
        margin = self._temporal_config.get("margin_seconds", 0)
        
        if not start_col or not end_col:
            return None
        
        start_time = cohort_row.get(start_col)
        end_time = cohort_row.get(end_col)
        
        start_sec = self._to_seconds(start_time)
        end_sec = self._to_seconds(end_time)
        
        if start_sec is not None and end_sec is not None:
            return (start_sec - margin, end_sec + margin)
        return None
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Private Methods - 헬퍼
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _get_cohort_column_info(self, cohort: pd.DataFrame) -> List[Dict[str, Any]]:
        """Cohort 컬럼 정보 추출"""
        columns = []
        for col in cohort.columns:
            col_info = {
                "name": col,
                "dtype": str(cohort[col].dtype),
                "null_count": int(cohort[col].isna().sum()),
                "unique_count": int(cohort[col].nunique())
            }
            
            # 숫자형이면 통계 추가
            if pd.api.types.is_numeric_dtype(cohort[col]):
                col_info["type"] = "numeric"
                col_info["stats"] = {
                    "mean": round(cohort[col].mean(), 2) if not cohort[col].isna().all() else None,
                    "min": cohort[col].min() if not cohort[col].isna().all() else None,
                    "max": cohort[col].max() if not cohort[col].isna().all() else None
                }
            else:
                col_info["type"] = "categorical"
                col_info["sample_values"] = cohort[col].dropna().head(5).tolist()
            
            columns.append(col_info)
        
        return columns
    
    def _get_temporal_description(self) -> str:
        """Temporal 설정 설명 생성"""
        temp_type = self._temporal_config.get("type", "full_record")
        margin = self._temporal_config.get("margin_seconds", 0)
        
        descriptions = {
            "full_record": "전체 기록 (시간 제한 없음)",
            "surgery_window": f"수술 시간 범위 (마진: {margin}초)",
            "anesthesia_window": f"마취 시간 범위 (마진: {margin}초)",
            "custom_window": f"사용자 지정 시간 범위 (마진: {margin}초)"
        }
        
        return descriptions.get(temp_type, temp_type)
    
    def _generate_description(
        self, 
        cohort_info: Dict[str, Any], 
        signal_info: Dict[str, Any]
    ) -> str:
        """데이터 설명 텍스트 생성"""
        parts = []
        
        # 케이스 수
        parts.append(f"총 {cohort_info['total_cases']}개 케이스의 데이터")
        
        # 필터
        if cohort_info['filters_applied']:
            filter_strs = []
            for f in cohort_info['filters_applied']:
                filter_strs.append(f"{f.get('column')} {f.get('operator')} {f.get('value')}")
            parts.append(f"필터: {', '.join(filter_strs)}")
        
        # 파라미터
        if signal_info['param_keys']:
            parts.append(f"측정 파라미터: {', '.join(signal_info['param_keys'][:5])}")
            if len(signal_info['param_keys']) > 5:
                parts.append(f"외 {len(signal_info['param_keys']) - 5}개")
        
        # Temporal
        parts.append(f"시간 범위: {signal_info['temporal_setting']['description']}")
        
        return ". ".join(parts)

