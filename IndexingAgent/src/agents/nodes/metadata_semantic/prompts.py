# src/agents/nodes/metadata_semantic/prompts.py
"""
Metadata Semantic 프롬프트

metadata 파일에서 컬럼 역할(key/desc/unit)을 추론하기 위한 LLM 프롬프트
"""

from IndexingAgent.src.agents.prompts import PromptTemplate
from IndexingAgent.src.models.llm_responses import ColumnRoleMapping


class ColumnRoleMappingPrompt(PromptTemplate):
    """
    Column Role Mapping 프롬프트
    
    metadata 파일의 컬럼들이 각각 어떤 역할을 하는지 분석
    - key_column: 파라미터 이름/코드
    - desc_column: 설명
    - unit_column: 측정 단위
    - extra_columns: 추가 유용한 컬럼들
    """
    
    name = "column_role_mapping"
    response_model = ColumnRoleMapping
    response_wrapper_key = None  # 직접 객체 반환 (wrapper 없음)
    is_list_response = False
    
    system_role = "You are a Medical Data Expert analyzing a metadata/dictionary file."
    
    task_description = """Analyze this file and identify which column serves which role:

- **key_column**: The column containing parameter names/codes (e.g., "age", "hr", "sbp")
  This is the main identifier column that other data files will reference.
  
- **desc_column**: The column containing descriptions or definitions
  Human-readable explanations of what each parameter means.
  
- **unit_column**: The column containing measurement units (e.g., "years", "bpm", "mmHg")
  May be empty or null for some parameters.
  
- **extra_columns**: Other useful columns mapped to their semantic role
  Examples: {"category": "Category", "reference_value": "Reference value", "data_source": "Data Source"}"""
    
    context_template = """[File Info]
File: {file_name}
Columns: {column_names}

[Columns with Sample Values]
{columns_info}

[Sample Rows (first 5)]
{sample_rows}"""
    
    rules = [
        "Return ONLY valid JSON (no markdown, no explanation)",
        "key_column is required - identify the primary identifier column",
        "desc_column and unit_column may be null if not clearly present",
        "Include confidence score and brief reasoning",
    ]

