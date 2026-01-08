# AnalysisAgent/src/context/builder.py
"""
Context Builder

DataContext 또는 직접 제공된 DataFrame에서 AnalysisContext를 구축합니다.

Usage:
    # DataContext에서 구축
    from shared.data.context import DataContext
    from AnalysisAgent.src.context import ContextBuilder
    
    data_ctx = DataContext()
    data_ctx.load_from_plan(execution_plan)
    
    builder = ContextBuilder()
    analysis_ctx = builder.build_from_data_context(data_ctx)
    
    # 직접 DataFrame에서 구축
    analysis_ctx = builder.build_from_dataframes(
        dataframes={"df": signal_df, "cohort": cohort_df},
        descriptions={"df": "Signal data", "cohort": "Cohort metadata"}
    )
"""

import logging
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import pandas as pd
import numpy as np

from .schema import ColumnInfo, DataFrameSchema, AnalysisContext, ToolInfo

if TYPE_CHECKING:
    from shared.data.context import DataContext

logger = logging.getLogger(__name__)


class ContextBuilder:
    """AnalysisContext 구축기"""
    
    def __init__(
        self,
        max_sample_values: int = 5,
        max_unique_values: int = 20,
        max_sample_rows: int = 3,
        compute_statistics: bool = True,
    ):
        """
        Args:
            max_sample_values: 컬럼당 최대 샘플 값 개수
            max_unique_values: Categorical 컬럼의 최대 고유값 개수
            max_sample_rows: DataFrame당 최대 샘플 행 개수
            compute_statistics: Numeric 컬럼 통계 계산 여부
        """
        self.max_sample_values = max_sample_values
        self.max_unique_values = max_unique_values
        self.max_sample_rows = max_sample_rows
        self.compute_statistics = compute_statistics
        
        # Tool Registry가 있으면 여기서 주입 (Phase 4에서 구현)
        self._tool_registry = None
    
    def set_tool_registry(self, registry: Any) -> None:
        """ToolRegistry 설정 (향후 사용)"""
        self._tool_registry = registry
    
    def build_from_data_context(
        self,
        data_context: "DataContext",
        additional_hints: Optional[str] = None,
        previous_results: Optional[List[Dict[str, Any]]] = None,
    ) -> AnalysisContext:
        """
        DataContext에서 AnalysisContext 구축
        
        Args:
            data_context: shared.data.context.DataContext 인스턴스
            additional_hints: 추가 힌트 (Orchestrator에서 전달)
            previous_results: 이전 분석 결과 목록
        
        Returns:
            AnalysisContext
        """
        logger.info("📊 Building AnalysisContext from DataContext...")
        
        dataframes: Dict[str, pd.DataFrame] = {}
        descriptions: Dict[str, str] = {}
        
        # Cohort data
        cohort = data_context.get_cohort()
        if cohort is not None and not cohort.empty:
            dataframes["cohort"] = cohort
            descriptions["cohort"] = "Cohort metadata"
            logger.debug(f"   Cohort: {cohort.shape}")
        
        # Signal data (merged)
        try:
            signals = data_context.get_merged_data()
            if signals is not None and not signals.empty:
                dataframes["df"] = signals
                descriptions["df"] = "Signal data (merged)"
                logger.debug(f"   Signal (merged): {signals.shape}")
        except Exception as e:
            logger.warning(f"   Could not get merged data: {e}")
        
        # Join 키 추출
        join_keys = self._find_join_keys(dataframes)
        
        return self.build_from_dataframes(
            dataframes=dataframes,
            descriptions=descriptions,
            join_keys=join_keys,
            additional_hints=additional_hints,
            previous_results=previous_results,
        )
    
    def build_from_dataframes(
        self,
        dataframes: Dict[str, pd.DataFrame],
        descriptions: Optional[Dict[str, str]] = None,
        join_keys: Optional[List[str]] = None,
        additional_hints: Optional[str] = None,
        previous_results: Optional[List[Dict[str, Any]]] = None,
    ) -> AnalysisContext:
        """
        DataFrame 딕셔너리에서 AnalysisContext 구축
        
        Args:
            dataframes: {"df": DataFrame, "cohort": DataFrame, ...}
            descriptions: {"df": "Signal data", ...}
            join_keys: 공통 Join 키 목록
            additional_hints: 추가 힌트
            previous_results: 이전 분석 결과
        
        Returns:
            AnalysisContext
        """
        descriptions = descriptions or {}
        
        # 데이터 스키마 구축
        data_schemas: Dict[str, DataFrameSchema] = {}
        for name, df in dataframes.items():
            if df is not None and not df.empty:
                schema = self._build_dataframe_schema(
                    df=df,
                    name=name,
                    description=descriptions.get(name, "")
                )
                data_schemas[name] = schema
                logger.debug(f"   Schema built for '{name}': {len(schema.columns)} columns")
        
        # Join 키 자동 탐지 (제공되지 않은 경우)
        if join_keys is None:
            join_keys = self._find_join_keys(dataframes)
        
        # 사용 가능한 Tools
        available_tools = self._get_available_tools()
        
        ctx = AnalysisContext(
            data_schemas=data_schemas,
            join_keys=join_keys,
            available_tools=available_tools,
            additional_hints=additional_hints,
            previous_results=previous_results or [],
        )
        
        logger.info(f"✅ AnalysisContext built: {len(data_schemas)} schemas, {len(join_keys)} join keys")
        
        return ctx
    
    def _build_dataframe_schema(
        self,
        df: pd.DataFrame,
        name: str,
        description: str = "",
    ) -> DataFrameSchema:
        """DataFrame에서 스키마 추출"""
        
        # 컬럼 정보 추출
        columns: List[ColumnInfo] = []
        for col_name in df.columns:
            col_info = self._analyze_column(df[col_name], col_name)
            columns.append(col_info)
        
        # 샘플 행 추출
        sample_rows = self._get_sample_rows(df)
        
        # 인덱스 컬럼 탐지
        index_column = None
        if df.index.name and df.index.name in df.columns:
            index_column = df.index.name
        
        return DataFrameSchema(
            name=name,
            description=description,
            shape=(len(df), len(df.columns)),
            columns=columns,
            sample_rows=sample_rows,
            index_column=index_column,
        )
    
    def _analyze_column(self, series: pd.Series, name: str) -> ColumnInfo:
        """개별 컬럼 분석"""
        
        # 원본 dtype
        original_dtype = str(series.dtype)
        
        # 타입 추론
        dtype = self._infer_column_type(series)
        
        # Nullable 체크
        nullable = series.isnull().any()
        
        # 샘플 값
        sample_values = self._get_sample_values(series)
        
        # 통계 (numeric만)
        statistics = None
        if dtype == "numeric" and self.compute_statistics:
            statistics = self._compute_statistics(series)
        
        # 고유값 (categorical만)
        unique_values = None
        unique_count = None
        if dtype == "categorical":
            unique_count = series.nunique()
            if unique_count <= self.max_unique_values:
                unique_values = series.dropna().unique().tolist()[:self.max_unique_values]
        
        return ColumnInfo(
            name=name,
            dtype=dtype,
            original_dtype=original_dtype,
            nullable=nullable,
            sample_values=sample_values,
            statistics=statistics,
            unique_values=unique_values,
            unique_count=unique_count,
        )
    
    def _infer_column_type(self, series: pd.Series) -> str:
        """컬럼 타입 추론"""
        dtype = series.dtype
        
        # Numeric
        if pd.api.types.is_numeric_dtype(dtype):
            return "numeric"
        
        # Boolean
        if pd.api.types.is_bool_dtype(dtype):
            return "boolean"
        
        # Datetime
        if pd.api.types.is_datetime64_any_dtype(dtype):
            return "datetime"
        
        # Object → Categorical or Text
        if dtype == object:
            # 샘플링해서 판단
            sample = series.dropna().head(100)
            if len(sample) == 0:
                return "unknown"
            
            # 고유값 비율로 판단
            unique_ratio = sample.nunique() / len(sample)
            
            # 대부분 고유하면 Text, 아니면 Categorical
            if unique_ratio > 0.5:
                # 평균 문자열 길이도 고려
                avg_len = sample.astype(str).str.len().mean()
                if avg_len > 50:
                    return "text"
            
            return "categorical"
        
        # Categorical dtype
        if pd.api.types.is_categorical_dtype(dtype):
            return "categorical"
        
        return "unknown"
    
    def _get_sample_values(self, series: pd.Series) -> List[Any]:
        """샘플 값 추출"""
        non_null = series.dropna()
        if len(non_null) == 0:
            return []
        
        # 랜덤 샘플 대신 첫 N개 사용 (재현성)
        samples = non_null.head(self.max_sample_values).tolist()
        
        # numpy 타입을 Python 기본 타입으로 변환
        return self._convert_to_python_types(samples)
    
    def _convert_to_python_types(self, values: List[Any]) -> List[Any]:
        """numpy 타입을 Python 기본 타입으로 변환"""
        result = []
        for v in values:
            if isinstance(v, (np.integer,)):
                result.append(int(v))
            elif isinstance(v, (np.floating,)):
                result.append(float(v))
            elif isinstance(v, (np.bool_,)):
                result.append(bool(v))
            elif pd.isna(v):
                result.append(None)
            else:
                result.append(v)
        return result
    
    def _compute_statistics(self, series: pd.Series) -> Dict[str, float]:
        """Numeric 컬럼 통계 계산"""
        try:
            non_null = series.dropna()
            total_count = len(series)
            null_count = series.isnull().sum()
            
            if len(non_null) == 0:
                return {
                    "null_count": int(null_count),
                    "null_ratio": 1.0,
                }
            
            return {
                "min": float(non_null.min()),
                "max": float(non_null.max()),
                "mean": float(non_null.mean()),
                "std": float(non_null.std()) if len(non_null) > 1 else 0.0,
                "median": float(non_null.median()),
                "null_count": int(null_count),
                "null_ratio": float(null_count / total_count) if total_count > 0 else 0.0,
            }
        except Exception as e:
            logger.warning(f"Could not compute statistics: {e}")
            return {}
    
    def _get_sample_rows(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """샘플 행 추출"""
        sample_df = df.head(self.max_sample_rows)
        
        # numpy 타입 변환
        records = sample_df.to_dict(orient="records")
        
        return [
            {
                k: (float(v) if isinstance(v, (np.floating,)) else
                    int(v) if isinstance(v, (np.integer,)) else
                    None if pd.isna(v) else v)
                for k, v in record.items()
            }
            for record in records
        ]
    
    def _find_join_keys(self, dataframes: Dict[str, pd.DataFrame]) -> List[str]:
        """공통 Join 키 탐지"""
        if len(dataframes) < 2:
            return []
        
        # 모든 DataFrame의 컬럼 수집
        all_columns = [set(df.columns) for df in dataframes.values() if df is not None]
        
        if not all_columns:
            return []
        
        # 교집합 (모든 DataFrame에 있는 컬럼)
        common_columns = set.intersection(*all_columns)
        
        # 일반적인 키 컬럼 이름 패턴
        key_patterns = ["id", "caseid", "case_id", "subject_id", "patient_id", "key"]
        
        join_keys = []
        for col in common_columns:
            col_lower = col.lower()
            if any(pattern in col_lower for pattern in key_patterns):
                join_keys.append(col)
        
        return join_keys
    
    def _get_available_tools(self) -> List[ToolInfo]:
        """사용 가능한 Tools 목록 (ToolRegistry에서)"""
        # Phase 4에서 구현
        # 현재는 빈 목록 반환
        if self._tool_registry is None:
            return []
        
        # TODO: ToolRegistry.list_tools() 호출
        return []
