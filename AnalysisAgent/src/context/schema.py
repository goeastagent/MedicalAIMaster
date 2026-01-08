# AnalysisAgent/src/context/schema.py
"""
Context Schema Models

AnalysisAgent가 분석을 수행하기 위해 필요한 컨텍스트 스키마를 정의합니다.

주요 컴포넌트:
- ColumnInfo: 개별 컬럼의 메타데이터 (타입, 통계, 샘플 값)
- DataFrameSchema: DataFrame의 전체 스키마 (컬럼 목록, shape, 샘플 행)
- AnalysisContext: 분석에 필요한 모든 컨텍스트 (스키마, Tools, 이전 결과)
"""

from typing import Dict, List, Any, Optional, Literal, Tuple
from pydantic import BaseModel, Field
from datetime import datetime


class ColumnInfo(BaseModel):
    """개별 컬럼의 메타데이터"""
    
    name: str
    dtype: Literal["numeric", "categorical", "datetime", "boolean", "text", "unknown"]
    original_dtype: str  # numpy/pandas dtype (e.g., "float64", "object")
    nullable: bool = True
    
    # 샘플 값 (최대 5개)
    sample_values: List[Any] = Field(default_factory=list)
    
    # Numeric 컬럼용 통계
    statistics: Optional[Dict[str, float]] = None
    # {
    #   "min": 0.0,
    #   "max": 100.0,
    #   "mean": 50.0,
    #   "std": 10.0,
    #   "median": 48.0,
    #   "null_count": 5,
    #   "null_ratio": 0.01
    # }
    
    # Categorical 컬럼용 고유값 (최대 20개)
    unique_values: Optional[List[Any]] = None
    unique_count: Optional[int] = None
    
    def describe(self) -> str:
        """컬럼 설명 문자열 생성 (LLM 프롬프트용)"""
        desc = f"'{self.name}' ({self.dtype})"
        
        if self.dtype == "numeric" and self.statistics:
            stats = self.statistics
            desc += f" - range [{stats.get('min', '?'):.2f}, {stats.get('max', '?'):.2f}]"
            desc += f", mean={stats.get('mean', '?'):.2f}"
        
        elif self.dtype == "categorical" and self.unique_values:
            if len(self.unique_values) <= 5:
                desc += f" - values: {self.unique_values}"
            else:
                desc += f" - {self.unique_count} unique values"
        
        elif self.dtype == "datetime":
            desc += " - datetime column"
        
        if self.nullable and self.statistics:
            null_ratio = self.statistics.get('null_ratio', 0)
            if null_ratio > 0:
                desc += f" (null: {null_ratio:.1%})"
        
        return desc


class DataFrameSchema(BaseModel):
    """DataFrame의 전체 스키마"""
    
    name: str  # 변수명 (e.g., "df", "cohort")
    description: str = ""  # 설명 (e.g., "Signal 데이터", "Cohort 메타데이터")
    
    # 형태 정보
    shape: Tuple[int, int]  # (rows, columns)
    
    # 컬럼 정보
    columns: List[ColumnInfo] = Field(default_factory=list)
    
    # 샘플 행 (최대 3개)
    sample_rows: List[Dict[str, Any]] = Field(default_factory=list)
    
    # 인덱스 정보
    index_column: Optional[str] = None
    
    @property
    def column_names(self) -> List[str]:
        """컬럼 이름 목록"""
        return [col.name for col in self.columns]
    
    @property
    def numeric_columns(self) -> List[str]:
        """Numeric 컬럼 이름 목록"""
        return [col.name for col in self.columns if col.dtype == "numeric"]
    
    @property
    def categorical_columns(self) -> List[str]:
        """Categorical 컬럼 이름 목록"""
        return [col.name for col in self.columns if col.dtype == "categorical"]
    
    def get_column(self, name: str) -> Optional[ColumnInfo]:
        """컬럼 정보 조회"""
        for col in self.columns:
            if col.name == name:
                return col
        return None
    
    def describe(self) -> str:
        """DataFrame 설명 문자열 생성 (LLM 프롬프트용)"""
        lines = [
            f"### {self.name}",
            f"Shape: {self.shape[0]:,} rows × {self.shape[1]} columns",
        ]
        
        if self.description:
            lines.append(f"Description: {self.description}")
        
        lines.append("Columns:")
        for col in self.columns:
            lines.append(f"  - {col.describe()}")
        
        return "\n".join(lines)


class ToolInfo(BaseModel):
    """등록된 Tool 정보 (간소화된 버전)"""
    
    name: str
    description: str
    input_schema: Dict[str, Any]  # JSON Schema
    output_type: str
    tags: List[str] = Field(default_factory=list)  # ["statistics", "correlation", ...]


class AnalysisContext(BaseModel):
    """분석에 필요한 전체 컨텍스트"""
    
    # 데이터 스키마
    data_schemas: Dict[str, DataFrameSchema] = Field(default_factory=dict)
    # {
    #   "df": DataFrameSchema(name="df", ...),
    #   "cohort": DataFrameSchema(name="cohort", ...)
    # }
    
    # Join 가능한 키 (공통 컬럼)
    join_keys: List[str] = Field(default_factory=list)
    
    # Available Tools
    available_tools: List[ToolInfo] = Field(default_factory=list)
    
    # Constraints (automatically added by system)
    constraints: List[str] = Field(default_factory=lambda: [
        "Result must be assigned to 'result' variable",
        "Handle NaN values appropriately (dropna, fillna)",
        "Prefer vectorized operations",
    ])
    
    # 이전 분석 결과 참조 (선택적)
    previous_results: List[Dict[str, Any]] = Field(default_factory=list)
    # [
    #   {"query": "HR 평균", "result": 72.5, "timestamp": "2025-01-08T10:00:00"}
    # ]
    
    # 추가 힌트 (Orchestrator에서 전달)
    additional_hints: Optional[str] = None
    
    # 메타데이터
    created_at: datetime = Field(default_factory=datetime.now)
    
    def describe(self) -> str:
        """전체 컨텍스트 설명 문자열 생성 (LLM 프롬프트용)"""
        sections = []
        
        # 데이터 스키마
        sections.append("## Available Data")
        for schema in self.data_schemas.values():
            sections.append(schema.describe())
        
        # Join 키
        if self.join_keys:
            sections.append(f"\n## Join Keys\n{', '.join(self.join_keys)}")
        
        # 사용 가능한 Tools
        if self.available_tools:
            sections.append("\n## Available Tools")
            for tool in self.available_tools:
                sections.append(f"- {tool.name}: {tool.description}")
        
        # 제약 조건
        if self.constraints:
            sections.append("\n## Constraints")
            for c in self.constraints:
                sections.append(f"- {c}")
        
        # 추가 힌트
        if self.additional_hints:
            sections.append(f"\n## Additional Hints\n{self.additional_hints}")
        
        return "\n".join(sections)
    
    def get_variable_descriptions(self) -> Dict[str, str]:
        """사용 가능한 변수와 설명 (CodeGenerator 호환용)"""
        result = {}
        for name, schema in self.data_schemas.items():
            desc = f"pandas DataFrame - {schema.shape[0]:,} rows × {schema.shape[1]} columns"
            if schema.description:
                desc += f" ({schema.description})"
            result[name] = desc
        return result
    
    def to_dict_for_llm(self) -> Dict[str, Any]:
        """LLM 프롬프트에 포함할 딕셔너리 형태"""
        return {
            "data_schemas": {
                name: {
                    "shape": schema.shape,
                    "columns": [
                        {
                            "name": col.name,
                            "dtype": col.dtype,
                            "description": col.describe()
                        }
                        for col in schema.columns
                    ],
                    "sample_rows": schema.sample_rows[:2]
                }
                for name, schema in self.data_schemas.items()
            },
            "join_keys": self.join_keys,
            "available_tools": [
                {"name": t.name, "description": t.description}
                for t in self.available_tools
            ],
            "constraints": self.constraints,
        }
