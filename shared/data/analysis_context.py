# shared/data/analysis_context.py
"""
AnalysisContextBuilder - LLM 분석을 위한 컨텍스트 생성 모듈

역할:
1. DataContext 정보를 LLM이 이해할 수 있는 형태로 변환
2. 동적 데이터 접근 가이드 생성
3. 통계 및 샘플 데이터 추출

DataContext에서 분석 컨텍스트 생성 로직을 분리하여 단일 책임 원칙 준수
"""

import logging
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import pandas as pd
import numpy as np

from shared.models.plan import AnalysisContext, CohortColumnInfo

if TYPE_CHECKING:
    from .context import DataContext

logger = logging.getLogger(__name__)


class AnalysisContextBuilder:
    """
    LLM 분석 컨텍스트 빌더
    
    DataContext의 정보를 기반으로 LLM이 분석에 활용할 수 있는
    컨텍스트, 가이드, 통계 등을 생성합니다.
    
    Usage:
        builder = AnalysisContextBuilder(data_context)
        ctx = builder.build_analysis_context()
        guide = builder.generate_access_guide(signals_dict, cohort_df)
    """
    
    # Temporal type 설명 매핑
    TEMPORAL_DESCRIPTIONS = {
        "full_record": "전체 기록 (시간 제한 없음)",
        "procedure_window": "시술/수술 시간 범위",
        "treatment_window": "치료 시간 범위",
        "custom_window": "사용자 지정 시간 범위"
    }
    
    # 시간/datetime 관련 컬럼명 패턴 (소문자로 비교)
    DATETIME_COLUMN_PATTERNS = {
        'time', 'timestamp', 'datetime', 'date', 'dt',
        'created_at', 'updated_at', 'recorded_at',
        'start_time', 'end_time', 'event_time',
        'opstart', 'opend', 'casestart', 'caseend',
    }
    
    def __init__(self, data_context: "DataContext"):
        """
        Args:
            data_context: DataContext 인스턴스
        """
        self._ctx = data_context
    
    def _detect_datetime_columns(self, df: pd.DataFrame) -> List[str]:
        """
        DataFrame에서 datetime/시간 관련 컬럼을 동적으로 감지
        
        감지 방법:
        1. dtype이 datetime64인 컬럼
        2. 컬럼명이 시간 관련 패턴과 일치하는 경우
        3. 숫자형이지만 이름이 시간 관련인 경우 (예: Time, timestamp 등)
        
        Args:
            df: 분석할 DataFrame
            
        Returns:
            시간 관련 컬럼명 리스트
        """
        datetime_cols = []
        
        for col in df.columns:
            # 1. dtype이 datetime64인 경우
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                datetime_cols.append(col)
                continue
            
            # 2. 컬럼명이 시간 관련 패턴과 일치하는 경우
            col_lower = col.lower()
            if col_lower in self.DATETIME_COLUMN_PATTERNS:
                datetime_cols.append(col)
                continue
            
            # 3. 컬럼명에 시간 관련 키워드가 포함된 경우
            for pattern in ['time', 'timestamp', 'datetime', 'date']:
                if pattern in col_lower:
                    datetime_cols.append(col)
                    break
        
        return datetime_cols
    
    def build_analysis_context(self) -> AnalysisContext:
        """
        LLM 분석을 위한 전체 컨텍스트 생성
        
        Returns:
            AnalysisContext 객체
        """
        cohort = self._ctx.get_cohort()
        case_ids = self._ctx.get_case_ids()
        
        # Cohort 정보
        cohort_info = {
            "total_cases": len(case_ids),
            "filters_applied": self._ctx._cohort_filters,
            "entity_identifier": self._ctx._cohort_entity_id,
            "columns": self._get_cohort_column_info(cohort)
        }
        
        # Signal 정보
        signal_info = {
            "parameters": self._ctx._param_info,
            "param_keys": self._ctx._param_keys,
            "temporal_setting": self._build_temporal_setting(),
            "available_files": len(self._ctx._signal_files)
        }
        
        # Description 생성
        description = self._generate_description(cohort_info, signal_info)
        
        # 원본 쿼리
        original_query = self._ctx._plan.get("original_query", "") if self._ctx._plan else ""
        
        return AnalysisContext(
            description=description,
            cohort_info=cohort_info,
            signal_info=signal_info,
            original_query=original_query
        )
    
    def generate_access_guide(
        self,
        signals_dict: Optional[Dict[str, pd.DataFrame]] = None,
        cohort_df: Optional[pd.DataFrame] = None,
        include_examples: bool = True
    ) -> str:
        """
        현재 데이터 구조에 기반한 동적 접근 가이드 생성
        
        LLM이 코드를 생성할 때 데이터 접근 방식을 이해할 수 있도록
        실제 데이터 구조를 분석하여 가이드를 자동 생성합니다.
        
        Args:
            signals_dict: 케이스별 Signal DataFrame Dict
            cohort_df: Cohort DataFrame
            include_examples: 코드 예시 포함 여부
        
        Returns:
            LLM 프롬프트에 삽입할 데이터 접근 가이드 문자열
        """
        guide_parts = ["## Available Data\n"]
        
        # 메타데이터에서 동적으로 식별자 컬럼 가져오기
        entity_col = self._ctx.entity_id_column or "id"
        cohort_entity = self._ctx._cohort_entity_id or entity_col
        signal_entity = self._ctx._signal_entity_id_key or entity_col
        
        # Signals 가이드
        guide_parts.extend(self._build_signals_guide(
            signals_dict, signal_entity, cohort_entity, include_examples
        ))
        
        # Cohort 가이드
        guide_parts.extend(self._build_cohort_guide(
            cohort_df, cohort_entity, include_examples
        ))
        
        # 일반 가이드라인
        guide_parts.append(self._build_general_guidelines(entity_col))
        
        return "\n".join(guide_parts)
    
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
            파라미터별 통계 딕셔너리
        """
        import random
        
        params = param_keys or self._ctx._param_keys
        case_ids = self._ctx.get_case_ids()
        
        if sample_size and sample_size < len(case_ids):
            case_ids = random.sample(case_ids, sample_size)
        
        # 모든 케이스의 데이터 수집
        all_data = {p: [] for p in params}
        
        for cid in case_ids:
            signals = self._ctx._get_signal_for_case(str(cid), params, apply_temporal=True)
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
            케이스별 샘플 데이터 리스트
        """
        case_ids = self._ctx.get_case_ids()[:n_cases]
        cohort = self._ctx.get_cohort()
        
        # 메타데이터 기반 cohort 키
        default_key = self._ctx.entity_id_column or "id"
        cohort_key = self._ctx._join_config.get("cohort_key") or self._ctx._cohort_entity_id or default_key
        
        samples = []
        for cid in case_ids:
            # Cohort 샘플
            cohort_row = cohort[cohort[cohort_key].astype(str) == str(cid)] if cohort_key in cohort.columns else pd.DataFrame()
            cohort_sample = cohort_row.iloc[0].to_dict() if not cohort_row.empty else {}
            
            # Signal 샘플
            signals = self._ctx._get_signal_for_case(str(cid), apply_temporal=True)
            signal_sample = []
            if not signals.empty:
                sample_df = signals.head(n_rows_per_case)
                signal_sample = sample_df.to_dict(orient="records")
            
            samples.append({
                "entity_id": str(cid),
                "cohort_sample": cohort_sample,
                "signal_sample": signal_sample
            })
        
        return samples
    
    def build_mapreduce_context(
        self,
        entity_sample: Optional[pd.DataFrame] = None,
        cohort: Optional[pd.DataFrame] = None,
        total_cases: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Map-Reduce 코드 생성을 위한 풍부한 데이터 컨텍스트 생성
        
        힌트 대신 실제 데이터 구조를 분석하여 LLM이 스스로 추론할 수 있도록
        충분한 정보를 제공합니다. 범용적으로 동작합니다.
        
        Args:
            entity_sample: 샘플 entity DataFrame (None이면 자동 로드)
            cohort: Cohort DataFrame (None이면 자동 로드)
            total_cases: 전체 케이스 수 (None이면 자동 계산)
        
        Returns:
            {
                "entity_data_sample": str,      # entity 데이터 설명 + 샘플
                "entity_data_columns": List[str],
                "entity_data_dtypes": Dict[str, str],
                "metadata_sample": str,         # cohort 데이터 설명 + 샘플
                "metadata_columns": List[str],
                "metadata_dtypes": Dict[str, str],
                "dataset_description": str,     # 데이터셋 요약 설명
                "entity_id_column": str,
            }
        """
        # 데이터 로드 (없으면)
        if cohort is None:
            cohort = self._ctx.get_cohort()
        
        if entity_sample is None:
            # 첫 번째 케이스의 데이터 로드
            case_ids = self._ctx.get_case_ids()
            if case_ids:
                entity_sample = self._ctx._get_signal_for_case(
                    str(case_ids[0]), 
                    apply_temporal=True
                )
        
        if total_cases is None:
            total_cases = len(self._ctx.get_case_ids())
        
        entity_id_column = self._ctx.entity_id_column or "id"
        
        result = {
            "entity_data_sample": None,
            "entity_data_columns": [],
            "entity_data_dtypes": {},
            "metadata_sample": None,
            "metadata_columns": [],
            "metadata_dtypes": {},
            "dataset_description": "",
            "entity_id_column": entity_id_column,
        }
        
        desc_parts = [f"Dataset with {total_cases} entities"]
        
        # === Entity Data Context ===
        if entity_sample is not None and not entity_sample.empty:
            entity_context = self._build_entity_data_context(entity_sample)
            result["entity_data_sample"] = entity_context["sample_text"]
            result["entity_data_columns"] = entity_context["columns"]
            result["entity_data_dtypes"] = entity_context["dtypes"]
            desc_parts.append(f"each with ~{entity_sample.shape[0]} time-series rows")
        
        # === Cohort (Metadata) Context ===
        if cohort is not None and not cohort.empty:
            metadata_context = self._build_metadata_context(cohort)
            result["metadata_sample"] = metadata_context["sample_text"]
            result["metadata_columns"] = metadata_context["columns"]
            result["metadata_dtypes"] = metadata_context["dtypes"]
            desc_parts.append(f"with {cohort.shape[1]} metadata columns")
        
        result["dataset_description"] = ", ".join(desc_parts)
        
        return result
    
    def _build_entity_data_context(self, entity_sample: pd.DataFrame) -> Dict[str, Any]:
        """
        Entity 데이터 컨텍스트 빌드 (범용)
        
        데이터 구조를 자동 분석하여 LLM이 이해할 수 있는 형태로 변환합니다.
        """
        columns = list(entity_sample.columns)
        dtypes = {col: str(entity_sample[col].dtype) for col in columns}
        
        lines = []
        lines.append(f"Shape: {entity_sample.shape} (rows × columns)")
        lines.append(f"Columns: {columns}")
        lines.append(f"Index: {entity_sample.index.name or 'RangeIndex'} (type: {type(entity_sample.index).__name__})")
        lines.append("")
        
        # 컬럼 타입별 분류 (범용)
        numeric_cols = entity_sample.select_dtypes(include=['number']).columns.tolist()
        datetime_cols = entity_sample.select_dtypes(include=['datetime64']).columns.tolist()
        other_cols = [c for c in columns if c not in numeric_cols and c not in datetime_cols]
        
        if numeric_cols:
            lines.append(f"Numeric columns: {numeric_cols}")
        if datetime_cols:
            lines.append(f"Datetime columns: {datetime_cols}")
        if other_cols:
            lines.append(f"Other columns: {other_cols}")
        
        lines.append("")
        lines.append("Sample data (first 5 rows):")
        lines.append(entity_sample.head(5).to_string())
        
        # 숫자 컬럼 기본 통계 (처음 3개만)
        if len(numeric_cols) > 0:
            lines.append("")
            lines.append("Numeric column stats (sample):")
            for col in numeric_cols[:3]:
                col_data = entity_sample[col].dropna()
                if len(col_data) > 0:
                    lines.append(f"  {col}: min={col_data.min():.2f}, max={col_data.max():.2f}, mean={col_data.mean():.2f}")
        
        return {
            "sample_text": "\n".join(lines),
            "columns": columns,
            "dtypes": dtypes,
        }
    
    def _build_metadata_context(self, cohort: pd.DataFrame) -> Dict[str, Any]:
        """
        Metadata (Cohort) 데이터 컨텍스트 빌드 (범용)
        
        datetime 컬럼을 자동 감지하여 temporal filtering에 활용할 수 있도록 합니다.
        """
        columns = list(cohort.columns)
        dtypes = {col: str(cohort[col].dtype) for col in columns}
        
        lines = []
        lines.append(f"Shape: {cohort.shape} (rows × columns)")
        lines.append(f"Columns: {columns}")
        lines.append("")
        
        # Datetime 컬럼 자동 감지 및 강조
        datetime_cols = []
        for col in cohort.columns:
            dtype_str = str(cohort[col].dtype)
            if 'datetime' in dtype_str:
                datetime_cols.append(col)
        
        if datetime_cols:
            lines.append(f"⏰ Datetime columns detected: {datetime_cols}")
            lines.append("   (These can be used for time-based filtering)")
            
            # 각 datetime 컬럼의 샘플 값 표시
            for col in datetime_cols:
                if len(cohort) > 0:
                    sample_val = cohort[col].iloc[0]
                    lines.append(f"   - {col}: e.g. {sample_val}")
            lines.append("")
        
        # 컬럼 타입별 분류
        id_cols = [c for c in columns if 'id' in c.lower() or 'case' in c.lower()]
        numeric_cols = cohort.select_dtypes(include=['number']).columns.tolist()
        categorical_cols = cohort.select_dtypes(include=['object', 'category']).columns.tolist()
        
        if id_cols:
            lines.append(f"ID columns: {id_cols}")
        if numeric_cols:
            lines.append(f"Numeric columns: {numeric_cols[:10]}{'...' if len(numeric_cols) > 10 else ''}")
        if categorical_cols:
            lines.append(f"Categorical columns: {categorical_cols[:10]}{'...' if len(categorical_cols) > 10 else ''}")
        
        lines.append("")
        lines.append("Sample data (first 3 rows):")
        lines.append(cohort.head(3).to_string())
        
        return {
            "sample_text": "\n".join(lines),
            "columns": columns,
            "dtypes": dtypes,
        }
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Private Methods
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
    
    def _build_temporal_setting(self) -> Dict[str, Any]:
        """Temporal 설정 정보 빌드"""
        temp_type = self._ctx._temporal_config.get("type", "full_record")
        margin = self._ctx._temporal_config.get("margin_seconds", 0)
        
        description = self.TEMPORAL_DESCRIPTIONS.get(temp_type, temp_type)
        if margin > 0 and temp_type != "full_record":
            description += f" (마진: {margin}초)"
        
        return {
            "type": temp_type,
            "margin_seconds": margin,
            "start_column": self._ctx._temporal_config.get("start_column"),
            "end_column": self._ctx._temporal_config.get("end_column"),
            "description": description
        }
    
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
    
    def _build_signals_guide(
        self,
        signals_dict: Optional[Dict[str, pd.DataFrame]],
        signal_entity: str,
        cohort_entity: str,
        include_examples: bool
    ) -> List[str]:
        """Signals 가이드 빌드"""
        if not signals_dict or len(signals_dict) == 0:
            return []
        
        guide_parts = []
        case_ids = list(signals_dict.keys())
        sample_cid = case_ids[0]
        sample_df = signals_dict[sample_cid]
        columns = list(sample_df.columns)
        
        # 동적으로 datetime/시간 컬럼 감지
        datetime_cols = self._detect_datetime_columns(sample_df)
        
        # 컬럼별 타입 분석 (시간 컬럼 제외)
        numeric_cols = [
            c for c in columns 
            if c not in datetime_cols and sample_df[c].dtype in ['float64', 'int64', 'float32', 'int32']
        ]
        
        # datetime 컬럼 정보 구성
        datetime_info = ""
        if datetime_cols:
            datetime_info = f"\n  - Datetime/Time columns: {datetime_cols}"
        
        guide_parts.append(f"""### signals: Dict[{signal_entity} → DataFrame]
- **Type**: Case-level independent time series data
- **Entity identifier key**: `{signal_entity}`
- **Loaded cases**: {case_ids[:5]}{'...' if len(case_ids) > 5 else ''} (total: {len(case_ids)})
- **Total cases in dataset**: {len(self._ctx.get_case_ids())}
- **Each DataFrame**:
  - Columns: {columns}
  - Numeric columns for analysis: {numeric_cols}{datetime_info}
  - Sample shape: {sample_df.shape}
""")
        
        if include_examples:
            guide_parts.append(f"""
**Access Patterns:**
```python
# Single case access
signals['{sample_cid}']['ColumnName'].mean()

# Iterate all cases (RECOMMENDED for statistics)
case_stats = {{cid: df['ColumnName'].mean() for cid, df in signals.items()}}
overall_mean = np.mean(list(case_stats.values()))  # Mean of case means

# Conditional analysis (with cohort)
target_cases = cohort[cohort['column'] == 'value']['{cohort_entity}'].astype(str).tolist()
filtered_signals = {{cid: signals[cid] for cid in target_cases if cid in signals}}

# Per-case correlation
case_corrs = {{cid: df['Col1'].corr(df['Col2']) for cid, df in signals.items()}}
mean_corr = np.nanmean(list(case_corrs.values()))
```

⚠️ **WARNING**: Do NOT concat all cases into one DataFrame and compute statistics directly.
   Each case has independent time axis. Use per-case computation then aggregate.
""")
        
        return guide_parts
    
    def _build_cohort_guide(
        self,
        cohort_df: Optional[pd.DataFrame],
        cohort_entity: str,
        include_examples: bool
    ) -> List[str]:
        """Cohort 가이드 빌드"""
        if cohort_df is None or cohort_df.empty:
            return []
        
        guide_parts = []
        cohort_columns = list(cohort_df.columns)
        
        # 주요 컬럼 분류
        id_cols = [c for c in cohort_columns if 'id' in c.lower() or 'case' in c.lower()]
        numeric_cols = [c for c in cohort_columns if cohort_df[c].dtype in ['float64', 'int64', 'float32', 'int32']][:10]
        categorical_cols = [c for c in cohort_columns if cohort_df[c].dtype == 'object'][:10]
        
        guide_parts.append(f"""
### cohort: DataFrame
- **Shape**: {cohort_df.shape}
- **Entity identifier column**: `{cohort_entity}`
- **ID columns**: {id_cols}
- **Sample numeric columns**: {numeric_cols}{'...' if len(numeric_cols) >= 10 else ''}
- **Sample categorical columns**: {categorical_cols}{'...' if len(categorical_cols) >= 10 else ''}
- **All columns**: {cohort_columns[:20]}{'...' if len(cohort_columns) > 20 else ''}
""")
        
        if include_examples:
            guide_parts.append(f"""
**Access Patterns:**
```python
# Filter by condition
filtered = cohort[cohort['column'] == 'value']
case_list = cohort[cohort['age'] > 60]['{cohort_entity}'].astype(str).tolist()

# Get metadata for specific case
case_info = cohort[cohort['{cohort_entity}'] == target_id].iloc[0]
```
""")
        
        return guide_parts
    
    def _build_general_guidelines(self, entity_col: str) -> str:
        """일반 가이드라인 빌드"""
        return f"""
## Analysis Guidelines

1. **Statistics across cases**: Always compute per-case first, then aggregate
2. **Join signals with cohort**: Use `{entity_col}` to link cohort metadata with signal data
3. **Handle missing data**: Use `dropna()` or check for NaN before calculations
4. **Result variable**: Assign final result to `result` variable
"""
