# src/processors/tabular.py
import pandas as pd
from typing import Dict, Any
from .base import BaseDataProcessor

class TabularProcessor(BaseDataProcessor):
    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(('.csv', '.xlsx', '.xls', '.parquet'))
    
    def _analyze_column(self, series: pd.Series, col_name: str) -> Dict[str, Any]:
        """
        컬럼을 분석하여 categorical/continuous를 판단하고 관련 정보를 추출
        
        판단 기준:
        - object/string/bool dtype → categorical
        - 숫자형이지만 unique values가 10개 이하 → categorical
        - 숫자형이고 unique values가 많음 → continuous
        """
        dtype = str(series.dtype)
        non_null_series = series.dropna()
        unique_values = non_null_series.unique()
        n_unique = len(unique_values)
        
        # Categorical vs Continuous 판단
        is_categorical = (
            series.dtype == 'object' or 
            series.dtype == 'bool' or 
            str(series.dtype).startswith('category') or
            (pd.api.types.is_numeric_dtype(series) and n_unique <= 10)
        )
        
        if is_categorical:
            # Categorical: unique values 추출 (최대 20개까지만)
            unique_list = unique_values[:20].tolist()
            if n_unique > 20:
                unique_list.append(f"... and {n_unique - 20} more")
            
            return {
                'column_name': col_name,
                'dtype': dtype,
                'column_type': 'categorical',
                'n_unique': n_unique,
                'unique_values': unique_list,
                'samples': unique_values[:5].tolist()
            }
        else:
            # Continuous: min, max, sample values
            try:
                min_val = float(non_null_series.min())
                max_val = float(non_null_series.max())
            except:
                min_val = None
                max_val = None
            
            return {
                'column_name': col_name,
                'dtype': dtype,
                'column_type': 'continuous',
                'n_unique': n_unique,  # ID 컬럼 계층 분석을 위해 추가
                'min': min_val,
                'max': max_val,
                'samples': non_null_series.head(5).tolist()
            }

    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        try:
            # 1. 데이터 로드 (샘플링)
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path, nrows=20) # LLM 토큰 절약을 위해 20행만
            elif file_path.endswith('.parquet'):
                df = pd.read_parquet(file_path).head(20)
            else:
                df = pd.read_excel(file_path, nrows=20)

            # 2. LLM을 위한 문맥(Context) 생성
            # LLM이 판단하려면 '이름'뿐만 아니라 '값의 생김새'가 중요함
            context_summary = "Dataset Type: Tabular Data\nColumns Overview:\n"
            
            column_details = []
            for col in df.columns:
                col_info = self._analyze_column(df[col], col)
                column_details.append(col_info)
                
                # Categorical인 경우 unique values 포함
                if col_info['column_type'] == 'categorical':
                    context_summary += (
                        f"- Column: '{col}' | Data Type: {col_info['dtype']} | "
                        f"Column Type: CATEGORICAL | "
                        f"Unique Values ({col_info['n_unique']}): {col_info['unique_values']}\n"
                    )
                else:  # continuous
                    context_summary += (
                        f"- Column: '{col}' | Data Type: {col_info['dtype']} | "
                        f"Column Type: CONTINUOUS | "
                        f"Range: [{col_info['min']}, {col_info['max']}] | "
                        f"Sample Values: {col_info['samples']}\n"
                    )

            # 3. LLM에게 물어보기 (부모 클래스 메서드 호출)
            anchor_result = self._ask_llm_to_identify_anchor(context_summary)

            # 4. 결과 정리
            return {
                "processor_type": "tabular",
                "file_path": file_path,
                "columns": list(df.columns),
                "column_details": column_details,  # 각 컬럼의 categorical/continuous 정보
                "anchor_info": {
                    "status": anchor_result.status,
                    "target_column": anchor_result.column_name,
                    "is_time_series": anchor_result.is_time_series,
                    "reasoning": anchor_result.reasoning,
                    "needs_human_confirmation": anchor_result.needs_human_confirmation
                }
            }

        except Exception as e:
            return {"error": str(e), "processor_type": "tabular"}