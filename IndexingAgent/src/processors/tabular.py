# src/processors/tabular.py
import os
import re
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime
from .base import BaseDataProcessor
from src.config import ProcessingConfig


class TabularProcessor(BaseDataProcessor):
    """
    테이블 형태의 데이터(.csv, .xlsx, .parquet)에서 최대한 많은 메타데이터를 추출하는 프로세서.
    
    추출 정보:
    - 파일 기본 정보: 경로, 크기, 행/열 개수
    - 컬럼별 상세 정보: dtype, categorical/continuous, 통계, 결측치
    - 날짜/시간 컬럼 자동 감지
    - 텍스트 컬럼 길이 통계
    - ID 컬럼 후보 감지 (unique ratio 기반)
    """
    
    # 날짜/시간 패턴 (컬럼명 기반 감지)
    DATETIME_COLUMN_PATTERNS = [
        r'.*date.*', r'.*time.*', r'.*_at$', r'.*_on$',
        r'^dt.*', r'.*timestamp.*', r'.*datetime.*',
        r'created', r'updated', r'modified', r'started', r'ended',
    ]
    
    # 날짜 형식 패턴 (값 기반 감지)
    DATETIME_VALUE_PATTERNS = [
        r'^\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
        r'^\d{2}/\d{2}/\d{4}',  # MM/DD/YYYY
        r'^\d{2}-\d{2}-\d{4}',  # DD-MM-YYYY
    ]

    def can_handle(self, file_path: str) -> bool:
        ext = file_path.lower().split('.')[-1]
        return ext in ProcessingConfig.TABULAR_EXTENSIONS
    
    def _is_potential_datetime_column(self, col_name: str, series: pd.Series) -> bool:
        """날짜/시간 컬럼인지 판단"""
        col_lower = col_name.lower()
        
        # 1. 컬럼명 패턴 매칭
        for pattern in self.DATETIME_COLUMN_PATTERNS:
            if re.match(pattern, col_lower):
                return True
        
        # 2. 이미 datetime dtype인 경우
        if pd.api.types.is_datetime64_any_dtype(series):
            return True
        
        # 3. 문자열 값 패턴 매칭 (샘플 기반)
        if series.dtype == 'object':
            sample_values = series.dropna().head(5).astype(str).tolist()
            for val in sample_values:
                for pattern in self.DATETIME_VALUE_PATTERNS:
                    if re.match(pattern, str(val)):
                        return True
        
        return False
    
    def _try_parse_datetime(self, series: pd.Series) -> Optional[Dict[str, Any]]:
        """날짜/시간 컬럼 파싱 시도 및 범위 추출"""
        try:
            # 이미 datetime인 경우
            if pd.api.types.is_datetime64_any_dtype(series):
                dt_series = series
            else:
                # 문자열 → datetime 변환 시도
                dt_series = pd.to_datetime(series, errors='coerce')
            
            valid_dt = dt_series.dropna()
            if len(valid_dt) == 0:
                return None
            
            return {
                "is_datetime": True,
                "min_date": str(valid_dt.min()),
                "max_date": str(valid_dt.max()),
                "date_range_days": (valid_dt.max() - valid_dt.min()).days if len(valid_dt) > 1 else 0,
                "valid_datetime_count": len(valid_dt),
                "invalid_datetime_count": len(series) - len(valid_dt),
            }
        except Exception:
            return None
    
    def _analyze_column(self, series: pd.Series, col_name: str, total_rows: int) -> Dict[str, Any]:
        """
        컬럼을 분석하여 최대한 많은 정보를 추출
        
        추출 정보:
        - 기본: dtype, categorical/continuous
        - 결측치: null_count, null_ratio
        - 통계: min, max, mean, std, median, quartiles (연속형)
        - 분포: unique values, value_counts (범주형)
        - 텍스트: 평균/최대 길이 (문자열)
        - 날짜: 날짜 범위 (날짜형)
        - ID 후보: unique_ratio
        """
        dtype = str(series.dtype)
        non_null_series = series.dropna()
        unique_values = non_null_series.unique()
        n_unique = len(unique_values)
        n_total = len(series)
        n_null = series.isna().sum()
        
        # 기본 정보
        base_info = {
            'column_name': col_name,
            'dtype': dtype,
            'total_count': n_total,
            'null_count': int(n_null),
            'null_ratio': round(n_null / n_total, 4) if n_total > 0 else 0,
            'non_null_count': len(non_null_series),
            'n_unique': n_unique,
            'unique_ratio': round(n_unique / n_total, 4) if n_total > 0 else 0,
        }
        
        # ID 컬럼 후보 감지 (unique_ratio가 0.9 이상이면 ID 후보)
        base_info['is_potential_id'] = base_info['unique_ratio'] >= 0.9 and n_unique > 1
        
        # 날짜/시간 컬럼 감지
        if self._is_potential_datetime_column(col_name, series):
            datetime_info = self._try_parse_datetime(series)
            if datetime_info:
                base_info.update(datetime_info)
                base_info['column_type'] = 'datetime'
                base_info['samples'] = non_null_series.head(5).astype(str).tolist()
                return base_info
        
        # Categorical vs Continuous 판단
        is_categorical = (
            series.dtype == 'object' or 
            series.dtype == 'bool' or 
            str(series.dtype).startswith('category') or
            (pd.api.types.is_numeric_dtype(series) and n_unique <= 10)
        )
        
        if is_categorical:
            # === Categorical 컬럼 ===
            base_info['column_type'] = 'categorical'
            
            # Unique values 추출 (최대 20개)
            unique_list = unique_values[:20].tolist()
            if n_unique > 20:
                unique_list.append(f"... and {n_unique - 20} more")
            base_info['unique_values'] = unique_list
            
            # Value counts (상위 10개)
            try:
                value_counts = series.value_counts().head(10)
                base_info['value_counts'] = {
                    str(k): int(v) for k, v in value_counts.items()
                }
                base_info['most_common_value'] = str(value_counts.index[0]) if len(value_counts) > 0 else None
                base_info['most_common_count'] = int(value_counts.iloc[0]) if len(value_counts) > 0 else 0
            except Exception:
                base_info['value_counts'] = {}
            
            # 문자열인 경우 길이 통계
            if series.dtype == 'object':
                try:
                    str_lengths = non_null_series.astype(str).str.len()
                    base_info['text_stats'] = {
                        'min_length': int(str_lengths.min()),
                        'max_length': int(str_lengths.max()),
                        'mean_length': round(float(str_lengths.mean()), 2),
                        'median_length': int(str_lengths.median()),
                    }
                except Exception:
                    pass
            
            base_info['samples'] = unique_values[:5].tolist()
            
        else:
            # === Continuous 컬럼 ===
            base_info['column_type'] = 'continuous'
            
            try:
                # 기본 통계
                base_info['min'] = float(non_null_series.min())
                base_info['max'] = float(non_null_series.max())
                base_info['mean'] = round(float(non_null_series.mean()), 4)
                base_info['std'] = round(float(non_null_series.std()), 4)
                base_info['median'] = float(non_null_series.median())
                
                # 사분위수
                q1 = non_null_series.quantile(0.25)
                q3 = non_null_series.quantile(0.75)
                base_info['quartiles'] = {
                    'q1': float(q1),
                    'q2': float(non_null_series.median()),  # median
                    'q3': float(q3),
                    'iqr': float(q3 - q1),  # Interquartile Range
                }
                
                # 이상치 범위 힌트 (IQR 기반)
                iqr = q3 - q1
                base_info['outlier_bounds'] = {
                    'lower': float(q1 - 1.5 * iqr),
                    'upper': float(q3 + 1.5 * iqr),
                }
                
                # 분포 특성
                base_info['distribution'] = {
                    'skewness': round(float(non_null_series.skew()), 4),
                    'kurtosis': round(float(non_null_series.kurtosis()), 4),
                }
                
                # 범위
                base_info['range'] = base_info['max'] - base_info['min']
                
            except Exception as e:
                base_info['stats_error'] = str(e)
            
            base_info['samples'] = non_null_series.head(5).tolist()
        
        return base_info
    
    def _load_full_dataframe(self, file_path: str) -> pd.DataFrame:
        """파일 전체를 로드합니다."""
        ext = file_path.lower().split('.')[-1]
        
        if ext == 'csv':
            return pd.read_csv(file_path)
        elif ext == 'parquet':
            return pd.read_parquet(file_path)
        elif ext in ['xlsx', 'xls']:
            return pd.read_excel(file_path)
        else:
            raise ValueError(f"Unsupported file extension: {ext}")
    
    def _get_file_info(self, file_path: str) -> Dict[str, Any]:
        """파일 기본 정보 추출"""
        stat = os.stat(file_path)
        return {
            "file_path": file_path,
            "file_name": os.path.basename(file_path),
            "file_extension": file_path.split('.')[-1].lower(),
            "file_size_bytes": stat.st_size,
            "file_size_mb": round(stat.st_size / (1024 * 1024), 2),
            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }

    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        테이블 파일에서 최대한 많은 메타데이터를 추출합니다.
        
        추출 정보:
        - 파일 기본 정보: 경로, 크기, 행/열 개수
        - 컬럼별 상세 정보: dtype, 통계, 결측치, unique ratio
        - 컬럼 타입별 분류: categorical, continuous, datetime
        - ID 컬럼 후보: unique_ratio 기반 감지
        - 데이터 품질: 결측치 요약
        
        Entity Identifier 감지와 시맨틱 분석은 Analyzer에서 수행합니다.
        """
        try:
            # 1. 파일 기본 정보
            file_info = self._get_file_info(file_path)
            
            # 2. 전체 데이터 로드
            df = self._load_full_dataframe(file_path)
            total_rows = len(df)
            total_cols = len(df.columns)
            
            # 3. 컬럼별 상세 분석
            column_details = []
            categorical_cols = []
            continuous_cols = []
            datetime_cols = []
            potential_id_cols = []
            high_null_cols = []  # 결측치 50% 이상
            
            for col in df.columns:
                col_info = self._analyze_column(df[col], col, total_rows)
                column_details.append(col_info)
                
                # 타입별 분류
                col_type = col_info.get('column_type', 'unknown')
                if col_type == 'categorical':
                    categorical_cols.append(col)
                elif col_type == 'continuous':
                    continuous_cols.append(col)
                elif col_type == 'datetime':
                    datetime_cols.append(col)
                
                # ID 후보
                if col_info.get('is_potential_id', False):
                    potential_id_cols.append(col)
                
                # 높은 결측치 컬럼
                if col_info.get('null_ratio', 0) >= 0.5:
                    high_null_cols.append({
                        'column': col,
                        'null_ratio': col_info['null_ratio']
                    })
            
            # 4. 전체 결측치 요약
            total_nulls = df.isna().sum().sum()
            total_cells = total_rows * total_cols
            
            # 5. 데이터 품질 요약
            quality_summary = {
                "total_cells": total_cells,
                "total_null_cells": int(total_nulls),
                "overall_null_ratio": round(total_nulls / total_cells, 4) if total_cells > 0 else 0,
                "complete_rows": int((~df.isna().any(axis=1)).sum()),
                "complete_row_ratio": round((~df.isna().any(axis=1)).sum() / total_rows, 4) if total_rows > 0 else 0,
                "columns_with_nulls": int((df.isna().sum() > 0).sum()),
                "high_null_columns": high_null_cols,
            }
            
            # 6. 샘플 데이터 (첫 5행)
            sample_rows = df.head(5).to_dict(orient='records')
            # NaN을 None으로 변환 (JSON 호환)
            for row in sample_rows:
                for key, value in row.items():
                    if pd.isna(value):
                        row[key] = None
            
            # 7. 결과 정리
            result = {
                "processor_type": "tabular",
                **file_info,
                
                # 크기 정보
                "row_count": total_rows,
                "column_count": total_cols,
                
                # 컬럼 정보
                "columns": list(df.columns),
                "column_details": column_details,
                
                # 컬럼 타입별 요약
                "column_type_summary": {
                    "categorical_count": len(categorical_cols),
                    "categorical_columns": categorical_cols,
                    "continuous_count": len(continuous_cols),
                    "continuous_columns": continuous_cols,
                    "datetime_count": len(datetime_cols),
                    "datetime_columns": datetime_cols,
                },
                
                # ID 후보
                "potential_id_columns": potential_id_cols,
                
                # 데이터 품질
                "quality_summary": quality_summary,
                
                # 샘플 데이터
                "sample_rows": sample_rows,
                
                # dtype 분포
                "dtype_distribution": df.dtypes.astype(str).value_counts().to_dict(),
                
                # NOTE: entity_info는 Analyzer에서 LLM이 결정
            }
            
            return result

        except Exception as e:
            import traceback
            return {
                "error": str(e),
                "error_traceback": traceback.format_exc(),
                "processor_type": "tabular",
                "file_path": file_path,
            }
