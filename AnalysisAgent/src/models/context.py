"""실행 컨텍스트 모델 - Code Gen과 Tool이 공유"""

from typing import Dict, List, Any, Optional, Tuple
from pydantic import BaseModel, Field


class ColumnDescription(BaseModel):
    """
    컬럼 상세 설명 - 프롬프트에서 컬럼의 의미를 전달
    
    LLM이 컬럼명을 정확히 이해하고 사용할 수 있도록 의미론적 정보를 포함합니다.
    
    Example:
        col = ColumnDescription(
            name="HR",
            dtype="float64",
            semantic_name="Heart Rate",
            unit="bpm",
            description="분당 심박수"
        )
        print(col.to_prompt_line())
        # → "`HR` (float64) - Heart Rate [bpm]"
    """
    
    name: str
    """실제 컬럼명 (코드에서 사용해야 하는 정확한 이름)"""
    
    dtype: str = "unknown"
    """데이터 타입 (예: "float64", "int64", "object")"""
    
    semantic_name: Optional[str] = None
    """의미론적 이름 (예: "Heart Rate", "Oxygen Saturation")"""
    
    unit: Optional[str] = None
    """측정 단위 (예: "bpm", "%", "mmHg")"""
    
    description: Optional[str] = None
    """상세 설명"""
    
    def to_prompt_line(self) -> str:
        """
        프롬프트용 한 줄 출력
        
        Returns:
            예: "`HR` (float64) - Heart Rate [bpm]"
        """
        parts = [f"`{self.name}` ({self.dtype})"]
        
        if self.semantic_name:
            parts.append(f"- {self.semantic_name}")
        
        if self.unit:
            parts.append(f"[{self.unit}]")
        
        if self.description:
            # 짧은 설명만 포함
            short_desc = self.description[:40] + "..." if len(self.description) > 40 else self.description
            parts.append(f": {short_desc}")
        
        return " ".join(parts)
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ColumnDescription":
        """딕셔너리에서 생성"""
        return cls(
            name=d.get("name", "unknown"),
            dtype=d.get("dtype", "unknown"),
            semantic_name=d.get("semantic_name"),
            unit=d.get("unit"),
            description=d.get("description"),
        )


class DataSchema(BaseModel):
    """데이터 스키마 정보
    
    DataFrame의 구조를 LLM에게 전달하기 위한 모델.
    
    Example:
        schema = DataSchema(
            name="df",
            description="Signal 데이터",
            columns=["Time", "HR", "SpO2", "ABP"],
            dtypes={"Time": "float64", "HR": "float64", "SpO2": "float64"},
            shape=(150000, 4),
            sample_rows=[
                {"Time": 0.0, "HR": 72.5, "SpO2": 98.2},
                {"Time": 0.002, "HR": 73.1, "SpO2": 98.1},
            ]
        )
    """
    
    name: str
    """변수명 (예: "df", "cohort")"""
    
    description: str
    """변수 설명 (예: "Signal 데이터 - 환자별 생체신호")"""
    
    columns: List[str]
    """컬럼 목록"""
    
    dtypes: Dict[str, str] = Field(default_factory=dict)
    """컬럼별 데이터 타입 (예: {"HR": "float64", "age": "int64"})"""
    
    shape: Optional[Tuple[int, int]] = None
    """DataFrame shape (rows, columns)"""
    
    sample_rows: Optional[List[Dict[str, Any]]] = None
    """샘플 데이터 행 (head(n))"""
    
    column_stats: Optional[Dict[str, Dict[str, Any]]] = None
    """컬럼별 통계 (숫자형: mean/min/max, 범주형: unique_count/sample_values)"""
    
    column_descriptions: Dict[str, ColumnDescription] = Field(default_factory=dict)
    """컬럼별 상세 설명 (컬럼명 → ColumnDescription)
    
    LLM이 컬럼의 의미를 정확히 이해할 수 있도록 semantic_name, unit 등 포함.
    예: {"HR": ColumnDescription(name="HR", dtype="float64", semantic_name="Heart Rate", unit="bpm")}
    """
    
    def to_prompt_text(self) -> str:
        """프롬프트용 텍스트 생성 (컬럼 설명 포함)"""
        lines = [f"### `{self.name}` - {self.description}"]
        
        # Shape
        if self.shape:
            lines.append(f"- Shape: {self.shape[0]:,} rows × {self.shape[1]} columns")
        
        # Columns with descriptions
        lines.append("- Columns:")
        for col in self.columns[:15]:  # 최대 15개만 표시
            if col in self.column_descriptions:
                # 상세 설명 포함
                col_desc = self.column_descriptions[col]
                lines.append(f"  - {col_desc.to_prompt_line()}")
            else:
                # 기존 방식 (dtype만)
                dtype = self.dtypes.get(col, "unknown")
                lines.append(f"  - `{col}` ({dtype})")
        
        if len(self.columns) > 15:
            lines.append(f"  - ... and {len(self.columns) - 15} more columns")
        
        # Sample rows
        if self.sample_rows:
            lines.append("- Sample data:")
            for i, row in enumerate(self.sample_rows[:2]):  # 2개만 표시
                # 값 포맷팅 (숫자는 소수점 제한)
                formatted = {k: (round(v, 2) if isinstance(v, float) else v) 
                            for k, v in list(row.items())[:5]}
                lines.append(f"  Row {i}: {formatted}")
        
        return "\n".join(lines)
    
    def set_column_descriptions_from_registry(
        self, 
        column_descs: Dict[str, Dict[str, Any]]
    ) -> None:
        """
        ParameterRegistry에서 가져온 컬럼 설명 설정
        
        Args:
            column_descs: to_column_descriptions() 결과
                {"HR": {"name": "HR", "dtype": "float64", "semantic_name": "Heart Rate", ...}}
        """
        for col in self.columns:
            if col in column_descs:
                self.column_descriptions[col] = ColumnDescription.from_dict(column_descs[col])


class ExecutionContext(BaseModel):
    """코드 생성 시 LLM에게 제공하는 컨텍스트
    
    Agent가 DataContext로부터 추출하여 Generator에게 전달.
    Generator는 이 정보를 기반으로 코드를 생성.
    
    Example:
        context = ExecutionContext(
            available_variables={
                "signals": "Dict[entity_id, DataFrame] - Case-level time series data",
                "cohort": "pandas DataFrame - Cohort metadata",
                "case_ids": "List[str] - Available entity IDs",
            },
            available_imports=["pandas as pd", "numpy as np"],
            sample_data={
                "signals_sample": {"entity_id": "1", "columns": ["Time", "HR", "SpO2"]},
            }
        )
    """
    
    available_variables: Dict[str, str]
    """사용 가능한 변수와 설명
    
    Key: 변수명 (예: "df", "cohort", "case_ids")
    Value: 변수 설명 (예: "pandas DataFrame - Signal 데이터, columns: [Time, HR, SpO2]")
    """
    
    available_imports: List[str] = Field(default_factory=lambda: [
        "pandas as pd",
        "numpy as np",
        "scipy.stats",
        "scipy.signal",
        "scipy.interpolate",
        "datetime",
        "math",
        "vitaldb",
    ])
    """허용된 import 목록
    
    샌드박스에서 허용되는 import만 포함.
    Generator가 코드 생성 시 이 목록만 사용하도록 안내.
    """
    
    sample_data: Optional[Dict[str, Any]] = None
    """LLM에게 보여줄 샘플 데이터 (선택적)
    
    데이터 구조를 이해하는 데 도움이 되는 샘플.
    예: df의 head(), columns, dtypes 등
    """
    
    data_schemas: Dict[str, DataSchema] = Field(default_factory=dict)
    """데이터 스키마 정보 (변수별)
    
    DataFrame 변수의 상세 구조 정보.
    예: {"df": DataSchema(...), "cohort": DataSchema(...)}
    """
    
    def to_prompt_context(self) -> str:
        """프롬프트에 삽입할 컨텍스트 문자열 생성"""
        lines = ["## Available Variables"]
        for var_name, var_desc in self.available_variables.items():
            lines.append(f"- `{var_name}`: {var_desc}")
        
        lines.append("\n## Allowed Imports")
        for imp in self.available_imports:
            lines.append(f"- `{imp}`")
        
        # 데이터 스키마 (상세 구조)
        if self.data_schemas:
            lines.append("\n## Data Structure Details")
            for schema in self.data_schemas.values():
                lines.append("")
                lines.append(schema.to_prompt_text())
        
        # 추가 샘플 데이터 (레거시 지원)
        if self.sample_data and not self.data_schemas:
            lines.append("\n## Sample Data")
            for key, value in self.sample_data.items():
                lines.append(f"- {key}: {value}")
        
        return "\n".join(lines)


class DataSummary(BaseModel):
    """데이터 요약 (Code Gen & Tool 공통)
    
    DataContext의 현재 상태를 요약.
    Agent가 LLM에게 데이터 개요를 전달할 때 사용.
    
    Example:
        summary = DataSummary(
            case_count=150,
            param_keys=["HR", "SpO2", "ABP"],
            cohort_columns=["entity_id", "age", "gender"],
            signal_columns=["Time", "HR", "SpO2", "ABP"],
            signal_shape=(150000, 4),
        )
    """
    
    case_count: int
    """분석 대상 케이스 수"""
    
    param_keys: List[str]
    """사용 가능한 파라미터 키 목록 (예: ["HR", "SpO2", "ABP"])"""
    
    cohort_columns: List[str]
    """Cohort DataFrame의 컬럼 목록"""
    
    signal_columns: List[str] = Field(default_factory=list)
    """Signal DataFrame의 컬럼 목록 (로드된 경우)"""
    
    signal_shape: Optional[Tuple[int, int]] = None
    """Signal DataFrame의 shape (rows, columns)"""
    
    temporal_filter: Optional[Dict[str, Any]] = None
    """적용된 시간 필터 정보 (있는 경우)"""
    
    def to_summary_text(self) -> str:
        """사람이 읽을 수 있는 요약 텍스트 생성"""
        lines = [
            f"Cases: {self.case_count}",
            f"Parameters: {', '.join(self.param_keys)}",
            f"Cohort columns: {', '.join(self.cohort_columns)}",
        ]
        
        if self.signal_columns:
            lines.append(f"Signal columns: {', '.join(self.signal_columns)}")
        
        if self.signal_shape:
            lines.append(f"Signal shape: {self.signal_shape[0]:,} rows × {self.signal_shape[1]} columns")
        
        if self.temporal_filter:
            lines.append(f"Temporal filter: {self.temporal_filter}")
        
        return "\n".join(lines)

