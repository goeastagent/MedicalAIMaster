# src/agents/nodes/data_semantic/prompts.py
"""
Data Semantic 프롬프트

데이터 파일 컬럼의 의미를 분석하고 data_dictionary와 매칭하기 위한 LLM 프롬프트
"""

from src.agents.prompts import PromptTemplate
from src.agents.models.llm_responses import ColumnSemanticResult


# =============================================================================
# Dictionary Section Templates (프롬프트에 삽입되는 템플릿)
# =============================================================================

DICT_SECTION_TEMPLATE = """[EXACT Parameter Keys - Use these values ONLY]
{dict_keys_list}

[Parameter Definitions]
{dict_context}
"""

DICT_SECTION_EMPTY = """[Note]
No parameter dictionary is available for this dataset.
Infer semantic meaning from column names and statistics using your medical knowledge.
Set dict_entry_key to null for all columns.
"""


class ColumnSemanticPrompt(PromptTemplate):
    """
    Column Semantic 프롬프트
    
    데이터 파일의 컬럼을 의미론적으로 분석:
    - semantic_name, unit, description 추론
    - data_dictionary의 parameter_key와 매칭
    - concept_category 분류
    """
    
    name = "column_semantic"
    response_model = ColumnSemanticResult
    response_wrapper_key = "columns"
    is_list_response = True
    
    system_role = "You are a Medical Data Expert analyzing clinical data columns."
    
    task_description = """Analyze each column and provide semantic information.
Use the Parameter Dictionary and column statistics to make accurate judgments."""
    
    context_template = """{dict_section}

[File: {file_name}]
Type: {file_type}
Rows: {row_count}

[Columns to Analyze with Statistics]
{columns_info}"""
    
    rules = [
        "dict_entry_key MUST be EXACTLY one of the keys from 'EXACT Parameter Keys' (if provided)",
        "Copy the key exactly as shown (including '/' and special characters)",
        "If no matching key exists → set dict_entry_key to null",
        "If uncertain (confidence < 0.7) → set dict_entry_key to null",
        "Use column statistics (min/max/values) to help identify the correct match",
        "Return ONLY valid JSON (no markdown, no explanation)",
    ]
    
    # Few-shot 예시
    examples = [
        {
            "input": "Column 'age' with values 20-90",
            "output": """{
  "original_name": "age",
  "semantic_name": "Age",
  "unit": "years",
  "description": "Patient age at time of surgery",
  "concept_category": "Demographics",
  "dict_entry_key": "age",
  "match_confidence": 0.99,
  "reasoning": "Exact name match, values 20-90 consistent with age"
}"""
        },
        {
            "input": "Column 'unknown_col' with unclear values",
            "output": """{
  "original_name": "unknown_col",
  "semantic_name": "Unknown Parameter",
  "unit": null,
  "description": "Unable to determine meaning",
  "concept_category": "Other",
  "dict_entry_key": null,
  "match_confidence": 0.0,
  "reasoning": "No matching parameter found in dictionary"
}"""
        }
    ]
    
    @classmethod
    def build_dict_section(cls, dict_keys_list: str, dict_context: str) -> str:
        """
        Dictionary section 구성 헬퍼 메서드
        
        Args:
            dict_keys_list: dictionary key 목록 문자열
            dict_context: dictionary 상세 정보 문자열
        
        Returns:
            포맷된 dict_section 문자열
        """
        if dict_keys_list:
            return DICT_SECTION_TEMPLATE.format(
                dict_keys_list=dict_keys_list,
                dict_context=dict_context
            )
        else:
            return DICT_SECTION_EMPTY

