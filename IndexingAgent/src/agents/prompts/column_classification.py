# src/agents/prompts/column_classification.py
"""
[column_classification] 노드 프롬프트

각 컬럼의 역할을 분류하는 LLM 프롬프트.
Wide-format과 Long-format 데이터를 모두 처리할 수 있도록
컬럼명과 unique values를 기반으로 역할을 판단합니다.

ColumnRole enum을 동적으로 활용하여 역할 목록을 생성합니다.
"""

from typing import List, Dict, Any

from .base import PromptTemplate
from src.models import ColumnClassificationItem, ColumnRole


class ColumnClassificationPrompt(PromptTemplate):
    """
    [column_classification] 컬럼 역할 분류 프롬프트
    
    입력: 컬럼명 + unique values + 기본 통계
    출력: 각 컬럼의 역할 분류
    
    Features:
    - ColumnRole enum에서 동적으로 역할 목록 생성
    - Wide-format: 컬럼명이 곧 parameter (예: HR, SBP)
    - Long-format: 특정 컬럼의 값들이 parameter (예: param_name 컬럼)
    """
    
    name = "column_classification"
    response_model = ColumnClassificationItem
    response_wrapper_key = "columns"
    is_list_response = True
    
    system_role = """You are a Medical Data Expert specializing in analyzing biomedical datasets.
Your task is to classify the role of each column in a medical data file.
You understand both Wide-format (parameters as column names) and Long-format (parameters as values in a key column)."""
    
    task_description = """Analyze each column and determine its role based on:
1. The column name
2. Sample unique values
3. Basic statistics (count, null count, dtype)

For each column, classify its role and provide reasoning."""
    
    # rules는 동적으로 생성 (build() 메서드에서)
    rules: List[str] = []
    
    examples: List[Dict[str, Any]] = [
        {
            "input": """Column: HR
Unique Values (10 samples): 72, 85, 91, 68, 77, 82, 79, 88, 75, 83
Stats: count=1000, null_count=5, dtype=float64""",
            "output": """{
  "column_name": "HR",
  "column_role": "parameter_name",
  "is_parameter_name": true,
  "is_parameter_container": false,
  "parameters": [],
  "confidence": 0.95,
  "reasoning": "HR (Heart Rate) is a common vital sign measurement. The column name itself represents a medical parameter with numeric values."
}"""
        },
        {
            "input": """Column: param
Unique Values (10 samples): HR, SBP, DBP, SpO2, RR, Temp, MAP, CVP, EtCO2, FiO2
Stats: count=50000, null_count=0, dtype=object""",
            "output": """{
  "column_name": "param",
  "column_role": "parameter_container",
  "is_parameter_name": false,
  "is_parameter_container": true,
  "parameters": ["HR", "SBP", "DBP", "SpO2", "RR", "Temp", "MAP", "CVP", "EtCO2", "FiO2"],
  "confidence": 0.98,
  "reasoning": "This column contains medical parameter names as values (HR, SBP, DBP, etc.). This is a Long-format key column where values represent different measurements."
}"""
        },
        {
            "input": """Column: caseid
Unique Values (10 samples): 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
Stats: count=1000, null_count=0, dtype=int64""",
            "output": """{
  "column_name": "caseid",
  "column_role": "identifier",
  "is_parameter_name": false,
  "is_parameter_container": false,
  "parameters": [],
  "confidence": 0.95,
  "reasoning": "caseid is a unique identifier for each case/patient. It's used for linking records, not as a measurement."
}"""
        }
    ]
    
    # context_template은 build()에서 직접 처리
    context_template = ""
    
    @classmethod
    def build(cls, columns_info: str, file_name: str = "") -> str:
        """
        컬럼 분류 프롬프트 생성
        
        Args:
            columns_info: 컬럼별 정보 문자열 (컬럼명, unique values, stats)
            file_name: 파일명 (선택)
        
        Returns:
            완성된 프롬프트 문자열
        """
        sections = []
        
        # 1. System Role
        sections.append(f"[Role]\n{cls.system_role}")
        
        # 2. Task Description
        sections.append(f"[Task]\n{cls.task_description}")
        
        # 3. Column Role Definitions (ColumnRole enum에서 동적 생성)
        role_definitions = cls._build_role_definitions()
        sections.append(f"[Column Role Definitions]\n{role_definitions}")
        
        # 4. Rules
        rules = cls._build_rules()
        sections.append(f"[Rules]\n{rules}")
        
        # 5. Examples
        examples_text = cls._format_examples()
        sections.append(f"[Examples]\n{examples_text}")
        
        # 6. Context (실제 컬럼 정보)
        context = cls._build_context(columns_info, file_name)
        sections.append(f"[Context]\n{context}")
        
        # 7. Output Format
        output_format = cls._get_output_format()
        sections.append(f"[Output Format]\nRespond with valid JSON:\n{output_format}")
        
        return "\n\n".join(sections)
    
    @classmethod
    def _build_role_definitions(cls) -> str:
        """
        ColumnRole enum에서 역할 정의 생성
        
        Returns:
            역할 정의 문자열
        """
        return ColumnRole.for_prompt()
    
    @classmethod
    def _build_rules(cls) -> str:
        """규칙 목록 생성"""
        rules = [
            "Analyze each column independently based on its name and values.",
            "For Wide-format data: Column names like 'HR', 'SBP', 'Temperature' are parameter_name.",
            "For Long-format data: A column containing parameter names as values is parameter_container.",
            "identifier columns are used for entity identification (e.g., caseid, patient_id, record_id).",
            "value columns contain measurement values (typically in Long-format paired with parameter_container).",
            "unit columns contain measurement units (e.g., 'mmHg', 'bpm', 'kg').",
            "timestamp columns contain date/time information.",
            "attribute columns contain descriptive info (e.g., sex, department, diagnosis).",
            "When uncertain, prefer 'other' with lower confidence.",
            "If is_parameter_container=true, list ALL unique values in 'parameters' field.",
            f"column_role must be one of: {', '.join(ColumnRole.values())}",
        ]
        return "\n".join(f"- {rule}" for rule in rules)
    
    @classmethod
    def _build_context(cls, columns_info: str, file_name: str) -> str:
        """컨텍스트 섹션 생성"""
        context_parts = []
        
        if file_name:
            context_parts.append(f"File: {file_name}")
        
        context_parts.append("[Columns to Classify]")
        context_parts.append(columns_info)
        
        return "\n".join(context_parts)


def build_column_info_for_prompt(
    column_name: str,
    unique_values: List[Any],
    stats: Dict[str, Any],
    max_samples: int = 15
) -> str:
    """
    단일 컬럼 정보를 프롬프트용 문자열로 변환
    
    Args:
        column_name: 컬럼명
        unique_values: unique 값 리스트
        stats: 통계 정보 dict (count, null_count, dtype 등)
        max_samples: 표시할 최대 샘플 수
    
    Returns:
        프롬프트용 문자열
    """
    lines = [f"Column: {column_name}"]
    
    # Unique values (샘플링)
    samples = unique_values[:max_samples]
    samples_str = ", ".join(str(v) for v in samples)
    
    if len(unique_values) > max_samples:
        lines.append(f"Unique Values ({len(unique_values)} total, showing {max_samples}): {samples_str}")
    else:
        lines.append(f"Unique Values ({len(unique_values)}): {samples_str}")
    
    # Stats
    stats_parts = []
    if "count" in stats:
        stats_parts.append(f"count={stats['count']}")
    if "null_count" in stats:
        stats_parts.append(f"null_count={stats['null_count']}")
    if "dtype" in stats:
        stats_parts.append(f"dtype={stats['dtype']}")
    if "unique_count" in stats:
        stats_parts.append(f"unique={stats['unique_count']}")
    
    if stats_parts:
        lines.append(f"Stats: {', '.join(stats_parts)}")
    
    return "\n".join(lines)


def build_columns_info_batch(
    columns_data: List[Dict[str, Any]],
    max_samples_per_column: int = 15
) -> str:
    """
    여러 컬럼 정보를 프롬프트용 문자열로 변환
    
    Args:
        columns_data: 컬럼 정보 리스트
            [{"name": str, "unique_values": list, "stats": dict}, ...]
        max_samples_per_column: 컬럼당 표시할 최대 샘플 수
    
    Returns:
        프롬프트용 문자열
    """
    column_blocks = []
    
    for col_data in columns_data:
        block = build_column_info_for_prompt(
            column_name=col_data["name"],
            unique_values=col_data.get("unique_values", []),
            stats=col_data.get("stats", {}),
            max_samples=max_samples_per_column
        )
        column_blocks.append(block)
    
    return "\n\n".join(column_blocks)

