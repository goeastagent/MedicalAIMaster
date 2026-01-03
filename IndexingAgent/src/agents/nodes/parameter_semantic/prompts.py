# src/agents/nodes/parameter_semantic/prompts.py
"""
Parameter Semantic 프롬프트

parameter 테이블의 각 parameter를 분석하고 data_dictionary와 매칭하기 위한 LLM 프롬프트
"""

from src.agents.prompts import PromptTemplate
from src.agents.models.llm_responses import ParameterSemanticResult


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
Infer semantic meaning from parameter names using your medical knowledge.
Set dict_entry_key to null for all parameters.
"""


class ParameterSemanticPrompt(PromptTemplate):
    """
    Parameter Semantic 프롬프트
    
    parameter 테이블의 각 parameter를 의미론적으로 분석:
    - semantic_name, unit, description 추론
    - data_dictionary의 parameter_key와 매칭
    - concept_category 분류
    """
    
    name = "parameter_semantic"
    response_model = ParameterSemanticResult
    response_wrapper_key = "parameters"
    is_list_response = True
    
    system_role = "You are a Medical Data Expert analyzing clinical parameters from medical datasets."
    
    task_description = """Analyze each parameter and provide semantic information.
Use the Parameter Dictionary to match parameters with standard definitions.
Parameters may come from column names (Wide-format) or column values (Long-format)."""
    
    context_template = """{dict_section}

[Parameters to Analyze]
Total: {param_count} parameters

{parameters_info}"""
    
    rules = [
        "dict_entry_key MUST be EXACTLY one of the keys from 'EXACT Parameter Keys' (if provided)",
        "Copy the key exactly as shown (including '/' and special characters)",
        "If no matching key exists → set dict_entry_key to null",
        "If uncertain (confidence < 0.7) → set dict_entry_key to null",
        "Use parameter names and statistics to help identify the correct match",
        "Return ONLY valid JSON (no markdown, no explanation)",
        "param_key in response must match the parameter name exactly",
    ]
    
    # Few-shot 예시
    examples = [
        {
            "input": "Parameter 'HR' (source: column_name)",
            "output": """{
  "param_key": "HR",
  "semantic_name": "Heart Rate",
  "unit": "bpm",
  "description": "Heart rate measurement",
  "concept_category": "Vital Signs",
  "dict_entry_key": "HR",
  "match_confidence": 0.95,
  "reasoning": "HR is standard abbreviation for Heart Rate"
}"""
        },
        {
            "input": "Parameter 'unknown_param' with unclear meaning",
            "output": """{
  "param_key": "unknown_param",
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
    
    # Custom output format (response_model 대신 직접 지정)
    custom_output_format = """{
  "parameters": [
    {
      "param_key": "string - Original parameter key (MUST match input exactly)",
      "semantic_name": "string - Standardized semantic name",
      "unit": "string or null - Measurement unit",
      "description": "string or null - Description",
      "concept_category": "string - Category (Vital Signs, Laboratory, Demographics, etc.)",
      "dict_entry_key": "string or null - EXACT key from dictionary (null if no match)",
      "match_confidence": "float (0.0-1.0) - Confidence score",
      "reasoning": "string - Reasoning for the match decision"
    }
  ]
}"""
    
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
