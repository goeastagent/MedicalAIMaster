# shared/data/context.py
"""
DataContext - Execution Plan 기반 데이터 로드 및 관리

역할:
1. ExtractionAgent의 execution_plan JSON 해석 → PlanParser 위임
2. DB에서 파일 경로 resolve
3. Processor를 사용하여 데이터 로드
4. 캐싱 (클래스 레벨, 모든 인스턴스 공유)
5. AnalysisAgent를 위한 분석 컨텍스트 제공 → AnalysisContextBuilder 위임

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
import logging
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
from shared.data.plan_parser import PlanParser
from shared.data.analysis_context import AnalysisContextBuilder
from shared.models.plan import ParsedPlan
from shared.utils import lazy_property

logger = logging.getLogger(__name__)


class DataContext:
    """
    Execution Plan 기반 데이터 로드 및 관리
    
    특징:
    - 클래스 레벨 캐시: 모든 인스턴스가 signal/cohort 데이터 공유
    - Lazy Loading: 요청 시에만 데이터 로드
    - Temporal Filter: procedure_window 등 자동 적용
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
        self._parsed_plan: Optional[ParsedPlan] = None  # PlanParser 결과
        self._loaded_at: Optional[datetime] = None
        
        # ═══════════════════════════════════════════════════════════════════════════
        # Metadata from Execution Plan (ExtractionAgent가 DB에서 조회한 정보)
        # _parsed_plan에서 복사되어 기존 코드와의 호환성 유지
        # ═══════════════════════════════════════════════════════════════════════════
        # Cohort metadata
        self._cohort_file_id: Optional[str] = None
        self._cohort_file_path: Optional[str] = None
        self._cohort_file_name: Optional[str] = None
        self._cohort_entity_id: Optional[str] = None  # entity_identifier (예: "caseid")
        self._cohort_row_represents: Optional[str] = None  # 행이 나타내는 것 (예: "surgical_case")
        self._cohort_filters: List[Dict[str, Any]] = []
        
        # Signal metadata
        self._signal_group_id: Optional[str] = None
        self._signal_group_name: Optional[str] = None  # 그룹명 (예: "vital_signals_by_case")
        self._signal_entity_id_key: Optional[str] = None  # entity_identifier_key (예: "caseid")
        self._signal_row_represents: Optional[str] = None  # 행이 나타내는 것
        self._signal_files: List[Dict[str, Any]] = []  # [{file_id, file_path, caseid}, ...]
        self._param_keys: List[str] = []
        self._param_info: List[Dict[str, Any]] = []  # [{term, param_key, semantic_name, unit}, ...]
        self._temporal_config: Dict[str, Any] = {}
        
        # Join configuration
        self._join_config: Dict[str, Any] = {}
        
        # ═══════════════════════════════════════════════════════════════════════════
        # Processors & Helpers
        # ═══════════════════════════════════════════════════════════════════════════
        self._signal_processor = SignalProcessor()
        self._tabular_processor = TabularProcessor()
        self._plan_parser: Optional[PlanParser] = None
        self._analysis_builder: Optional[AnalysisContextBuilder] = None
        
        # DB
        self._db = None
    
    @lazy_property
    def db(self):
        """Lazy DB connection"""
        return get_db_manager()
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Metadata Properties (Execution Plan에서 추출한 정보)
    # ═══════════════════════════════════════════════════════════════════════════
    
    @property
    def entity_id_column(self) -> Optional[str]:
        """
        주요 엔티티 식별자 컬럼명 반환
        
        Signal의 entity_identifier_key를 우선 사용, 없으면 cohort의 entity_identifier
        
        Returns:
            식별자 컬럼명 (예: "caseid", "subject_id") 또는 None
        """
        return self._signal_entity_id_key or self._cohort_entity_id
    
    @property
    def cohort_entity_column(self) -> Optional[str]:
        """Cohort 테이블의 엔티티 식별자 컬럼명"""
        return self._cohort_entity_id
    
    @property
    def signal_entity_column(self) -> Optional[str]:
        """Signal 파일의 엔티티 식별자 키"""
        return self._signal_entity_id_key
    
    @property
    def join_keys(self) -> Dict[str, str]:
        """
        Join에 사용할 키 반환
        
        Returns:
            {"cohort_key": "caseid", "signal_key": "caseid"}
        """
        return {
            "cohort_key": self._join_config.get("cohort_key"),
            "signal_key": self._join_config.get("signal_key"),
        }
    
    def get_plan_metadata(self) -> Dict[str, Any]:
        """
        Execution Plan에서 추출한 메타데이터 반환
        
        동적 가이드 생성, 힌트 생성 등에서 활용
        
        Returns:
            {
                "entity_id_column": "caseid",
                "cohort": {"file_name": "clinical_data.csv", "entity_identifier": "caseid", ...},
                "signal": {"group_name": "vital_signals_by_case", "entity_identifier_key": "caseid", ...},
                "join": {"cohort_key": "caseid", "signal_key": "caseid"},
                "parameters": [...]
            }
        """
        return {
            "entity_id_column": self.entity_id_column,
            "cohort": {
                "file_id": self._cohort_file_id,
                "file_name": self._cohort_file_name,
                "file_path": self._cohort_file_path,
                "entity_identifier": self._cohort_entity_id,
                "row_represents": self._cohort_row_represents,
            },
            "signal": {
                "group_id": self._signal_group_id,
                "group_name": self._signal_group_name,
                "entity_identifier_key": self._signal_entity_id_key,
                "row_represents": self._signal_row_represents,
                "file_count": len(self._signal_files),
            },
            "join": self._join_config,
            "parameters": self._param_info,
            "param_keys": self._param_keys,
        }
    
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
        
        PlanParser를 사용하여 파싱하고, 결과를 내부 속성에 매핑합니다.
        
        Args:
            execution_plan: ExtractionAgent가 생성한 plan JSON
            preload_cohort: cohort 데이터를 미리 로드할지 (기본 True)
        
        Returns:
            self (method chaining 지원)
        """
        self._plan = execution_plan
        
        # ═══════════════════════════════════════════════════════════════════════════
        # PlanParser를 사용하여 파싱
        # ═══════════════════════════════════════════════════════════════════════════
        if self._plan_parser is None:
            self._plan_parser = PlanParser(db_manager=self._db)
        
        self._parsed_plan = self._plan_parser.parse(execution_plan, resolve_paths=True)
        
        # ═══════════════════════════════════════════════════════════════════════════
        # ParsedPlan에서 내부 속성으로 복사 (기존 코드 호환성 유지)
        # ═══════════════════════════════════════════════════════════════════════════
        # Cohort metadata
        cohort = self._parsed_plan.cohort
        self._cohort_file_id = cohort.file_id
        self._cohort_file_path = cohort.file_path
        self._cohort_file_name = cohort.file_name
        self._cohort_entity_id = cohort.entity_identifier
        self._cohort_row_represents = cohort.row_represents
        self._cohort_filters = cohort.filters
        
        # Signal metadata
        signal = self._parsed_plan.signal
        self._signal_group_id = signal.group_id
        self._signal_group_name = signal.group_name
        self._signal_entity_id_key = signal.entity_identifier_key
        self._signal_row_represents = signal.row_represents
        self._signal_files = signal.files
        self._param_keys = signal.param_keys
        self._param_info = signal.param_info
        self._temporal_config = signal.temporal_config
        
        # Join configuration
        join = self._parsed_plan.join
        self._join_config = {
            "cohort_key": join.cohort_key,
            "signal_key": join.signal_key,
            "type": join.join_type
        }
        
        self._loaded_at = datetime.now()
        
        # ═══════════════════════════════════════════════════════════════════════════
        # AnalysisContextBuilder 초기화
        # ═══════════════════════════════════════════════════════════════════════════
        self._analysis_builder = AnalysisContextBuilder(self)
        
        # Cohort 미리 로드 (선택적)
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
        apply_temporal: bool = True,
        max_cases: Optional[int] = None,
        parallel: bool = True,
        max_workers: int = 4
    ) -> pd.DataFrame:
        """
        Signal 데이터 반환
        
        cohort 필터가 적용된 경우, 필터된 케이스 중 signal 파일이 있는 케이스만 로드합니다.
        
        Args:
            caseid: 특정 케이스만 (None이면 cohort 필터 적용된 유효 케이스)
            param_keys: 특정 파라미터만 (None이면 plan의 모든 파라미터)
            apply_temporal: temporal_alignment 적용 여부
            max_cases: 최대 로드할 케이스 수 (None이면 전체)
            parallel: 병렬 로딩 활성화 (기본 True)
            max_workers: 병렬 처리 워커 수 (기본 4)
        
        Returns:
            DataFrame with columns: [caseid, Time, param1, param2, ...]
        """
        params = param_keys or self._param_keys
        
        if caseid:
            # 단일 케이스
            logger.info(f"📡 Loading signal for case: {caseid}")
            return self._get_signal_for_case(caseid, params, apply_temporal)
        else:
            # cohort 필터가 적용된 케이스 중 signal 파일이 있는 케이스만 (교집합)
            case_ids = self.get_available_case_ids()
            total_cases = len(case_ids)
            
            # 케이스 수 제한
            if max_cases and total_cases > max_cases:
                logger.warning(f"⚠️ Limiting to {max_cases} cases (total: {total_cases})")
                case_ids = case_ids[:max_cases]
            
            n_cases = len(case_ids)
            
            if parallel and n_cases > 1:
                return self._load_signals_parallel(case_ids, params, apply_temporal, max_workers)
            else:
                return self._load_signals_sequential(case_ids, params, apply_temporal)
    
    def _load_signals_parallel(
        self,
        case_ids: List[Any],
        params: List[str],
        apply_temporal: bool,
        max_workers: int
    ) -> pd.DataFrame:
        """병렬로 Signal 로드"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time
        
        n_cases = len(case_ids)
        logger.info(f"📡 Loading signals for {n_cases} cases (parallel, {max_workers} workers)...")
        start_time = time.time()
        
        all_signals = []
        completed = 0
        
        def load_case(cid):
            df = self._get_signal_for_case(str(cid), params, apply_temporal)
            if not df.empty:
                df[self._join_config["signal_key"]] = cid
            return cid, df
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(load_case, cid): cid for cid in case_ids}
            
            for future in as_completed(futures):
                cid, df = future.result()
                completed += 1
                
                if not df.empty:
                    all_signals.append(df)
                
                # 진행률 로그 (25% 단위)
                if completed % max(1, n_cases // 4) == 0 or completed == n_cases:
                    elapsed = time.time() - start_time
                    logger.info(f"   Progress: {completed}/{n_cases} cases ({elapsed:.1f}s)")
        
        if all_signals:
            result = pd.concat(all_signals, ignore_index=True)
            total_time = time.time() - start_time
            logger.info(f"✅ Signal loading complete: {len(result)} rows from {len(all_signals)} cases ({total_time:.1f}s)")
            return result
        
        logger.warning("⚠️ No signal data loaded")
        return pd.DataFrame()
    
    def _load_signals_sequential(
        self,
        case_ids: List[Any],
        params: List[str],
        apply_temporal: bool
    ) -> pd.DataFrame:
        """순차적으로 Signal 로드"""
        import time
        
        n_cases = len(case_ids)
        logger.info(f"📡 Loading signals for {n_cases} cases (sequential)...")
        start_time = time.time()
        
        all_signals = []
        for i, cid in enumerate(case_ids):
            logger.debug(f"   [{i+1}/{n_cases}] Loading case {cid}...")
            df = self._get_signal_for_case(str(cid), params, apply_temporal)
            if not df.empty:
                df[self._join_config["signal_key"]] = cid
                all_signals.append(df)
                
            # 진행률 로그 (매 5개마다)
            if (i + 1) % 5 == 0:
                elapsed = time.time() - start_time
                logger.info(f"   Progress: {i+1}/{n_cases} cases ({elapsed:.1f}s)")
        
        if all_signals:
            result = pd.concat(all_signals, ignore_index=True)
            total_time = time.time() - start_time
            logger.info(f"✅ Signal loading complete: {len(result)} rows from {len(all_signals)} cases ({total_time:.1f}s)")
            return result
        
        logger.warning("⚠️ No signal data loaded")
        return pd.DataFrame()
    
    def get_signals_dict(
        self,
        case_ids: Optional[List[str]] = None,
        param_keys: Optional[List[str]] = None,
        apply_temporal: bool = True,
        max_cases: Optional[int] = None,
        parallel: bool = True,
        max_workers: int = 4
    ) -> Dict[str, pd.DataFrame]:
        """
        케이스별 DataFrame Dict 반환 (케이스 단위 보존)
        
        cohort 필터가 적용된 경우, 필터된 케이스 중 signal 파일이 있는 케이스만 로드합니다.
        
        Args:
            case_ids: 로드할 케이스 ID 목록 (None이면 cohort 필터 적용된 유효 케이스)
            param_keys: 특정 파라미터만 (None이면 plan의 모든 파라미터)
            apply_temporal: temporal_alignment 적용 여부
            max_cases: 최대 로드할 케이스 수 (None이면 전체)
            parallel: 병렬 로딩 활성화 (기본 True)
            max_workers: 병렬 처리 워커 수 (기본 4)
        
        Returns:
            Dict[caseid, DataFrame] - 각 케이스별 독립 시계열 DataFrame
            예: {"case1": DataFrame([Time, HR, SpO2, ...]), "case2": ...}
        """
        params = param_keys or self._param_keys
        # cohort 필터가 적용된 케이스 중 signal 파일이 있는 케이스만 (교집합)
        target_cases = case_ids or self.get_available_case_ids()
        total_cases = len(target_cases)
        
        # 케이스 수 제한
        if max_cases and total_cases > max_cases:
            logger.warning(f"⚠️ Limiting to {max_cases} cases (total: {total_cases})")
            target_cases = target_cases[:max_cases]
        
        n_cases = len(target_cases)
        
        if parallel and n_cases > 1:
            return self._load_signals_dict_parallel(target_cases, params, apply_temporal, max_workers)
        else:
            return self._load_signals_dict_sequential(target_cases, params, apply_temporal)
    
    def _load_signals_dict_parallel(
        self,
        case_ids: List[Any],
        params: List[str],
        apply_temporal: bool,
        max_workers: int
    ) -> Dict[str, pd.DataFrame]:
        """병렬로 Signal Dict 로드"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import time
        
        n_cases = len(case_ids)
        logger.info(f"📡 Loading signals dict for {n_cases} cases (parallel, {max_workers} workers)...")
        start_time = time.time()
        
        result_dict: Dict[str, pd.DataFrame] = {}
        completed = 0
        
        def load_case(cid):
            df = self._get_signal_for_case(str(cid), params, apply_temporal)
            return str(cid), df
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(load_case, cid): cid for cid in case_ids}
            
            for future in as_completed(futures):
                cid, df = future.result()
                completed += 1
                
                if not df.empty:
                    result_dict[cid] = df
                
                # 진행률 로그 (25% 단위)
                if completed % max(1, n_cases // 4) == 0 or completed == n_cases:
                    elapsed = time.time() - start_time
                    logger.info(f"   Progress: {completed}/{n_cases} cases ({elapsed:.1f}s)")
        
        total_time = time.time() - start_time
        total_rows = sum(len(df) for df in result_dict.values())
        logger.info(f"✅ Signal dict loading complete: {len(result_dict)} cases, {total_rows} total rows ({total_time:.1f}s)")
        
        return result_dict
    
    def _load_signals_dict_sequential(
        self,
        case_ids: List[Any],
        params: List[str],
        apply_temporal: bool
    ) -> Dict[str, pd.DataFrame]:
        """순차적으로 Signal Dict 로드"""
        import time
        
        n_cases = len(case_ids)
        logger.info(f"📡 Loading signals dict for {n_cases} cases (sequential)...")
        start_time = time.time()
        
        result_dict: Dict[str, pd.DataFrame] = {}
        
        for i, cid in enumerate(case_ids):
            logger.debug(f"   [{i+1}/{n_cases}] Loading case {cid}...")
            df = self._get_signal_for_case(str(cid), params, apply_temporal)
            if not df.empty:
                result_dict[str(cid)] = df
                
            # 진행률 로그 (매 5개마다)
            if (i + 1) % 5 == 0:
                elapsed = time.time() - start_time
                logger.info(f"   Progress: {i+1}/{n_cases} cases ({elapsed:.1f}s)")
        
        total_time = time.time() - start_time
        total_rows = sum(len(df) for df in result_dict.values())
        logger.info(f"✅ Signal dict loading complete: {len(result_dict)} cases, {total_rows} total rows ({total_time:.1f}s)")
        
        return result_dict
    
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
        
        # 메타데이터 기반 join 키 (fallback: entity_id_column)
        default_key = self.entity_id_column or "id"
        cohort_key = self._join_config.get("cohort_key") or self._cohort_entity_id or default_key
        signal_key = self._join_config.get("signal_key") or self._signal_entity_id_key or default_key
        
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
                "entity_id": str,         # 엔티티 식별자 값
                "cohort": pd.Series,      # 해당 케이스의 메타데이터
                "signals": pd.DataFrame,  # 해당 케이스의 신호 데이터
                "temporal_range": (start, end) or None
            }
        """
        cohort_df = self.get_cohort()
        case_ids = self.get_case_ids()
        
        # 메타데이터 기반 cohort 키
        default_key = self.entity_id_column or "id"
        cohort_key = self._join_config.get("cohort_key") or self._cohort_entity_id or default_key
        
        for cid in case_ids:
            # Cohort row
            cohort_row = cohort_df[cohort_df[cohort_key].astype(str) == str(cid)] if cohort_key in cohort_df.columns else pd.DataFrame()
            cohort_series = cohort_row.iloc[0] if not cohort_row.empty else pd.Series()
            
            # Signals
            signals = self._get_signal_for_case(str(cid), param_keys, apply_temporal)
            
            # Temporal range
            temporal_range = None
            if apply_temporal and not cohort_series.empty:
                temporal_range = self._get_temporal_range(cohort_series)
            
            yield {
                "entity_id": str(cid),
                "cohort": cohort_series,
                "signals": signals,
                "temporal_range": temporal_range
            }
    
    def iter_cases_batch(
        self,
        batch_size: int = 100,
        param_keys: Optional[List[str]] = None,
        apply_temporal: bool = True,
        max_cases: Optional[int] = None,
        parallel: bool = True,
        max_workers: int = 4,
    ) -> Iterator[Dict[str, Any]]:
        """
        케이스를 배치 단위로 순회 (대용량 Map-Reduce 처리용)
        
        메모리 효율적인 처리를 위해 배치 단위로 시그널을 로드하고,
        각 배치 처리 후 메모리를 해제할 수 있도록 합니다.
        
        Args:
            batch_size: 배치당 케이스 수 (기본 100)
            param_keys: 로드할 파라미터 목록 (None이면 plan의 모든 파라미터)
            apply_temporal: temporal_alignment 적용 여부
            max_cases: 최대 처리할 케이스 수 (None이면 전체)
            parallel: 배치 내 병렬 로딩 활성화
            max_workers: 병렬 처리 워커 수
        
        Yields:
            {
                "batch_index": int,           # 현재 배치 인덱스 (0부터 시작)
                "total_batches": int,         # 전체 배치 수
                "batch_size": int,            # 현재 배치의 케이스 수
                "entity_ids": List[str],      # 배치 내 엔티티 ID 목록
                "signals": Dict[str, DataFrame],  # 배치 내 시그널 {entity_id: df}
                "metadata_rows": DataFrame,   # 배치 내 메타데이터 행들
            }
        
        Example:
            # 대용량 데이터 Map-Reduce 처리
            import gc
            
            all_results = []
            for batch in ctx.iter_cases_batch(batch_size=100):
                print(f"Processing batch {batch['batch_index']+1}/{batch['total_batches']}")
                
                for entity_id, signals_df in batch["signals"].items():
                    # map_func 호출
                    result = map_func(entity_id, signals_df, ...)
                    all_results.append(result)
                
                # 배치 처리 후 메모리 해제
                del batch
                gc.collect()
            
            # 최종 집계
            final = reduce_func(all_results, cohort)
        """
        # 사용 가능한 케이스 ID (cohort + signal 교집합)
        all_case_ids = self.get_available_case_ids()
        
        # max_cases 적용
        if max_cases and len(all_case_ids) > max_cases:
            logger.warning(f"⚠️ Limiting to {max_cases} cases (total: {len(all_case_ids)})")
            all_case_ids = all_case_ids[:max_cases]
        
        total_cases = len(all_case_ids)
        total_batches = (total_cases + batch_size - 1) // batch_size
        
        if total_cases == 0:
            logger.warning("⚠️ No cases available for batch iteration")
            return
        
        logger.info(f"📦 Starting batch iteration: {total_cases} cases in {total_batches} batches (size={batch_size})")
        
        # Cohort 전체 로드 (메타데이터는 작으므로 전체 로드)
        cohort_df = self.get_cohort()
        
        # 메타데이터 기반 cohort 키
        default_key = self.entity_id_column or "id"
        cohort_key = self._join_config.get("cohort_key") or self._cohort_entity_id or default_key
        
        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, total_cases)
            batch_case_ids = all_case_ids[start_idx:end_idx]
            
            # 배치 내 시그널 로드
            signals_dict = self.get_signals_dict(
                case_ids=batch_case_ids,
                param_keys=param_keys,
                apply_temporal=apply_temporal,
                parallel=parallel,
                max_workers=max_workers,
            )
            
            # 배치 내 메타데이터 행 추출
            metadata_rows = pd.DataFrame()
            if not cohort_df.empty and cohort_key in cohort_df.columns:
                batch_case_ids_str = [str(c) for c in batch_case_ids]
                metadata_rows = cohort_df[
                    cohort_df[cohort_key].astype(str).isin(batch_case_ids_str)
                ].copy()
            
            # 실제 로드된 entity_ids (시그널이 있는 것만)
            loaded_entity_ids = list(signals_dict.keys())
            
            yield {
                "batch_index": batch_idx,
                "total_batches": total_batches,
                "batch_size": len(loaded_entity_ids),
                "entity_ids": loaded_entity_ids,
                "signals": signals_dict,
                "metadata_rows": metadata_rows,
            }
    
    def get_batch_metadata_row(
        self,
        metadata_rows: pd.DataFrame,
        entity_id: str,
    ) -> pd.Series:
        """배치 메타데이터에서 특정 엔티티의 행 추출
        
        iter_cases_batch()와 함께 사용하는 헬퍼 메서드.
        
        Args:
            metadata_rows: iter_cases_batch()가 반환한 metadata_rows
            entity_id: 엔티티 ID
        
        Returns:
            해당 엔티티의 메타데이터 Series (없으면 빈 Series)
        
        Example:
            for batch in ctx.iter_cases_batch():
                for entity_id, signals in batch["signals"].items():
                    metadata_row = ctx.get_batch_metadata_row(
                        batch["metadata_rows"], 
                        entity_id
                    )
                    result = map_func(entity_id, signals, metadata_row)
        """
        if metadata_rows.empty:
            return pd.Series()
        
        # 메타데이터 기반 cohort 키
        default_key = self.entity_id_column or "id"
        cohort_key = self._join_config.get("cohort_key") or self._cohort_entity_id or default_key
        
        if cohort_key not in metadata_rows.columns:
            return pd.Series()
        
        row = metadata_rows[metadata_rows[cohort_key].astype(str) == str(entity_id)]
        
        if row.empty:
            return pd.Series()
        
        return row.iloc[0]
    
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
            # Signal 파일이 있는 케이스만 (entity_id 키 사용)
            return [f.get("entity_id") for f in self._signal_files if f.get("entity_id")]
        else:
            # Cohort 전체 케이스
            cohort = self.get_cohort()
            if cohort.empty:
                return []
            
            # 메타데이터 기반 entity 컬럼
            entity_col = self._cohort_entity_id or self.entity_id_column or "id"
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
        
        AnalysisContextBuilder에 위임합니다.
        
        Returns:
            {
                "description": str,
                "cohort": {...},
                "signals": {...},
                "original_query": str
            }
        """
        if self._analysis_builder is None:
            self._analysis_builder = AnalysisContextBuilder(self)
        
        return self._analysis_builder.build_analysis_context().to_dict()
    
    def generate_access_guide(
        self,
        signals_dict: Optional[Dict[str, pd.DataFrame]] = None,
        cohort_df: Optional[pd.DataFrame] = None,
        include_examples: bool = True
    ) -> str:
        """
        현재 데이터 구조에 기반한 동적 접근 가이드 생성
        
        AnalysisContextBuilder에 위임합니다.
        
        Args:
            signals_dict: 케이스별 Signal DataFrame Dict
            cohort_df: Cohort DataFrame
            include_examples: 코드 예시 포함 여부
        
        Returns:
            LLM 프롬프트에 삽입할 데이터 접근 가이드 문자열
        """
        if self._analysis_builder is None:
            self._analysis_builder = AnalysisContextBuilder(self)
        
        return self._analysis_builder.generate_access_guide(
            signals_dict=signals_dict,
            cohort_df=cohort_df,
            include_examples=include_examples
        )
    
    def compute_statistics(
        self,
        param_keys: Optional[List[str]] = None,
        percentiles: List[float] = [0.25, 0.5, 0.75],
        sample_size: Optional[int] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        파라미터별 통계 계산
        
        AnalysisContextBuilder에 위임합니다.
        
        Args:
            param_keys: 계산할 파라미터 (None이면 전체)
            percentiles: 계산할 백분위수
            sample_size: 샘플링할 케이스 수 (None이면 전체)
        
        Returns:
            파라미터별 통계 딕셔너리
        """
        if self._analysis_builder is None:
            self._analysis_builder = AnalysisContextBuilder(self)
        
        return self._analysis_builder.compute_statistics(
            param_keys=param_keys,
            percentiles=percentiles,
            sample_size=sample_size
        )
    
    def get_sample_data(
        self,
        n_cases: int = 3,
        n_rows_per_case: int = 5
    ) -> List[Dict[str, Any]]:
        """
        LLM에게 보여줄 샘플 데이터
        
        AnalysisContextBuilder에 위임합니다.
        
        Args:
            n_cases: 샘플링할 케이스 수
            n_rows_per_case: 케이스당 샘플 행 수
        
        Returns:
            케이스별 샘플 데이터 리스트
        """
        if self._analysis_builder is None:
            self._analysis_builder = AnalysisContextBuilder(self)
        
        return self._analysis_builder.get_sample_data(
            n_cases=n_cases,
            n_rows_per_case=n_rows_per_case
        )
    
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
    
    def to_execution_context(
        self,
        include_signals: bool = True,
        sample_rows: int = 3,
        max_signal_cases: int = 3
    ) -> Dict[str, Any]:
        """
        Code Generation을 위한 ExecutionContext 데이터 생성
        
        AnalysisAgent의 ExecutionContext 모델과 호환되는 딕셔너리 반환.
        DataSchema 정보를 포함하여 LLM이 정확한 컬럼명을 알 수 있도록 함.
        
        Args:
            include_signals: Signal 데이터 스키마 포함 여부
            sample_rows: 샘플 데이터 행 수
            max_signal_cases: Signal 샘플링할 최대 케이스 수
        
        Returns:
            ExecutionContext 생성에 필요한 딕셔너리
            {
                "available_variables": {...},
                "available_imports": [...],
                "data_schemas": {
                    "df": {...},
                    "cohort": {...}
                }
            }
        
        Example:
            ctx_data = data_context.to_execution_context()
            from AnalysisAgent.src.models import ExecutionContext, DataSchema
            exec_ctx = ExecutionContext(
                available_variables=ctx_data["available_variables"],
                data_schemas={k: DataSchema(**v) for k, v in ctx_data["data_schemas"].items()}
            )
        """
        cohort = self.get_cohort()
        case_ids = self.get_case_ids()
        
        # 1. Available Variables
        available_variables = {}
        
        if not cohort.empty:
            available_variables["cohort"] = (
                f"pandas DataFrame - Cohort 메타데이터, "
                f"{len(cohort)} rows × {len(cohort.columns)} columns"
            )
        
        if include_signals and case_ids:
            available_variables["df"] = (
                f"pandas DataFrame - Signal 데이터, "
                f"columns: [Time, {', '.join(self._param_keys[:5])}{'...' if len(self._param_keys) > 5 else ''}]"
            )
        
        available_variables["case_ids"] = f"List[str] - {len(case_ids)}개 케이스 ID"
        available_variables["param_keys"] = f"List[str] - {self._param_keys}"
        
        # 2. Data Schemas
        data_schemas = {}
        
        # Cohort 스키마
        if not cohort.empty:
            cohort_schema = self._build_data_schema(
                name="cohort",
                description="Cohort 메타데이터 (환자 정보)",
                df=cohort,
                sample_rows=sample_rows
            )
            data_schemas["cohort"] = cohort_schema
        
        # Signal 스키마 (샘플 케이스에서 추출)
        if include_signals and case_ids:
            sample_case = case_ids[0] if case_ids else None
            if sample_case:
                signals = self._get_signal_for_case(sample_case, apply_temporal=True)
                if not signals.empty:
                    # 여러 케이스의 shape 추정
                    total_rows = len(signals) * len(case_ids)
                    signals_schema = self._build_data_schema(
                        name="df",
                        description=f"Signal 데이터 (생체신호, {len(case_ids)} cases)",
                        df=signals,
                        sample_rows=sample_rows,
                        override_shape=(total_rows, len(signals.columns))
                    )
                    data_schemas["df"] = signals_schema
        
        # 3. Available Imports
        available_imports = [
            "pandas as pd",
            "numpy as np", 
            "scipy.stats as stats",
            "datetime",
            "math",
        ]
        
        return {
            "available_variables": available_variables,
            "available_imports": available_imports,
            "data_schemas": data_schemas,
            "case_ids": case_ids,
            "param_keys": self._param_keys,
        }
    
    def _build_data_schema(
        self,
        name: str,
        description: str,
        df: pd.DataFrame,
        sample_rows: int = 3,
        override_shape: Optional[Tuple[int, int]] = None
    ) -> Dict[str, Any]:
        """DataFrame에서 DataSchema 딕셔너리 생성"""
        # 컬럼 정보
        columns = list(df.columns)
        dtypes = {col: str(df[col].dtype) for col in columns}
        
        # Shape
        shape = override_shape or (len(df), len(df.columns))
        
        # 샘플 행
        sample_data = None
        if sample_rows > 0 and not df.empty:
            sample_df = df.head(sample_rows)
            sample_data = sample_df.to_dict(orient="records")
            # 숫자 반올림
            for row in sample_data:
                for k, v in row.items():
                    if isinstance(v, float):
                        row[k] = round(v, 4)
        
        # 컬럼 통계
        column_stats = {}
        for col in columns[:10]:  # 최대 10개 컬럼만
            if pd.api.types.is_numeric_dtype(df[col]):
                column_stats[col] = {
                    "type": "numeric",
                    "mean": round(df[col].mean(), 4) if not df[col].isna().all() else None,
                    "min": round(df[col].min(), 4) if not df[col].isna().all() else None,
                    "max": round(df[col].max(), 4) if not df[col].isna().all() else None,
                }
            else:
                column_stats[col] = {
                    "type": "categorical",
                    "unique_count": df[col].nunique(),
                    "sample_values": df[col].dropna().head(5).tolist(),
                }
        
        return {
            "name": name,
            "description": description,
            "columns": columns,
            "dtypes": dtypes,
            "shape": shape,
            "sample_rows": sample_data,
            "column_stats": column_stats,
        }
    
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
            
            # 메타데이터에서 entity_id 키 결정 (동적)
            # DB의 filename_values에서 어떤 키로 엔티티 ID를 가져올지
            entity_key = self._signal_entity_id_key or "caseid"  # plan에서 받은 키 사용
            
            files = []
            for row in rows:
                file_id, file_path, filename_values = row
                entity_id = None
                if filename_values and isinstance(filename_values, dict):
                    # entity_key로 먼저 시도, 없으면 일반적인 ID 패턴들 시도
                    entity_id = filename_values.get(entity_key)
                    if entity_id is None:
                        # fallback: 다른 ID 패턴 시도
                        for key in ["caseid", "case_id", "subject_id", "id"]:
                            if key in filename_values:
                                entity_id = filename_values[key]
                                break
                
                files.append({
                    "file_id": str(file_id),
                    "file_path": file_path,
                    "entity_id": str(entity_id) if entity_id else None
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
        entity_id: str, 
        param_keys: Optional[List[str]] = None,
        apply_temporal: bool = True
    ) -> pd.DataFrame:
        """특정 엔티티의 signal 데이터 로드"""
        params = param_keys or self._param_keys
        
        # 캐시 확인
        if entity_id in DataContext._signal_cache:
            df = DataContext._signal_cache[entity_id]
        else:
            # 파일 찾기
            file_info = None
            for f in self._signal_files:
                if f.get("entity_id") == entity_id:
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
                DataContext._signal_cache[entity_id] = df
            except Exception as e:
                print(f"[DataContext] Error loading signal for {entity_id}: {e}")
                return pd.DataFrame()
        
        # 파라미터 필터링
        if params:
            # Time 컬럼이 존재하는 경우에만 포함 (일부 데이터셋에는 없을 수 있음)
            time_cols = ["Time"] if "Time" in df.columns else []
            available_cols = time_cols + [p for p in params if p in df.columns]
            if available_cols:
                df = df[available_cols]
        
        # Temporal 필터 적용
        if apply_temporal and self._temporal_config.get("type", "full_record") != "full_record":
            cohort = self.get_cohort()
            # 메타데이터 기반 cohort 키
            default_key = self.entity_id_column or "id"
            cohort_key = self._join_config.get("cohort_key") or self._cohort_entity_id or default_key
            cohort_row = cohort[cohort[cohort_key].astype(str) == str(entity_id)] if cohort_key in cohort.columns else pd.DataFrame()
            
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
        start_sec = self._to_seconds(start_time)
        end_sec = self._to_seconds(end_time)
        
        if start_sec is None or end_sec is None:
            return signals_df
        
        # margin 적용
        start_sec = start_sec - margin
        end_sec = end_sec + margin
        
        # 시간 컬럼 동적 감지
        time_column = self._find_time_column(signals_df)
        
        if time_column:
            return signals_df[
                (signals_df[time_column] >= start_sec) & 
                (signals_df[time_column] <= end_sec)
            ].copy()
        
        return signals_df
    
    def _find_time_column(self, df: pd.DataFrame) -> Optional[str]:
        """
        DataFrame에서 시간/timestamp 컬럼을 동적으로 감지
        
        감지 우선순위:
        1. 'Time' (기존 호환성)
        2. datetime64 dtype 컬럼
        3. 시간 관련 이름 패턴 매칭
        
        Args:
            df: 분석할 DataFrame
            
        Returns:
            시간 컬럼명 (없으면 None)
        """
        # 시간 관련 컬럼명 패턴 (우선순위 순)
        time_patterns = [
            'Time', 'time',  # 기존 호환성 우선
            'timestamp', 'Timestamp', 'TIMESTAMP',
            'datetime', 'DateTime', 'DATETIME',
            'date', 'Date', 'DATE',
            'dt', 'DT',
        ]
        
        # 1. 우선순위 패턴과 정확히 일치하는 컬럼
        for pattern in time_patterns:
            if pattern in df.columns:
                return pattern
        
        # 2. datetime64 dtype 컬럼
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                return col
        
        # 3. 컬럼명에 시간 관련 키워드 포함 (소문자 비교)
        for col in df.columns:
            col_lower = col.lower()
            if any(p in col_lower for p in ['time', 'timestamp', 'datetime']):
                return col
        
        return None
    
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
            "procedure_window": f"시술/수술 시간 범위 (마진: {margin}초)",
            "treatment_window": f"치료 시간 범위 (마진: {margin}초)",
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

