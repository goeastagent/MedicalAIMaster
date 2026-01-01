# src/agents/nodes/entity_identification/prompts.py
"""
Entity Identification 프롬프트

각 데이터 테이블이 어떤 Entity를 나타내는지,
고유 식별자 컬럼이 무엇인지 분석하기 위한 LLM 프롬프트
"""

from src.agents.prompts import PromptTemplate
from src.agents.models.llm_responses import TableEntityResult


class EntityIdentificationPrompt(PromptTemplate):
    """
    Entity Identification 프롬프트
    
    데이터 테이블의 행이 무엇을 나타내는지(row_represents)와
    고유 식별자 컬럼(entity_identifier)을 식별합니다.
    """
    
    name = "entity_identification"
    response_model = TableEntityResult
    response_wrapper_key = "tables"
    is_list_response = True
    
    system_role = "You are a Medical Data Expert analyzing clinical database tables."
    
    task_description = """For each data table, identify:
1. **row_represents**: What does each ROW in this table represent? 
   - Examples: "surgery", "patient", "lab_result", "vital_sign_record", "medication_order"
   - Use a SINGULAR noun (not plural)
   
2. **entity_identifier**: Which column UNIQUELY identifies each row?
   - Look at unique counts - if unique count equals row count, that's a good candidate
   - If multiple columns together form a unique key, set to null
   - If no single column uniquely identifies rows, set to null"""
    
    context_template = """[Tables to Analyze]
{tables_context}"""
    
    rules = [
        "row_represents should be a SINGULAR, descriptive noun in lowercase",
        "entity_identifier should be a column with unique values per row (unique_count ≈ row_count)",
        "If a table has time-series data (same ID with multiple timestamps), the ID column is NOT a unique identifier",
        "For signal/waveform data, consider if there's a case/subject identifier",
    ]
    
    examples = [
        {
            "input": "patients.csv with patient_id (10000 unique), age, sex, admission_date...",
            "output": """{
    "file_name": "patients.csv",
    "row_represents": "patient",
    "entity_identifier": "patient_id",
    "confidence": 0.95,
    "reasoning": "patient_id has 10000 unique values matching row count, each row is one patient record"
}"""
        },
        {
            "input": "lab_results.csv with patient_id (5000 unique), test_time, test_name, value...",
            "output": """{
    "file_name": "lab_results.csv",
    "row_represents": "lab_result",
    "entity_identifier": null,
    "confidence": 0.85,
    "reasoning": "Multiple lab results per patient_id over time, no single column uniquely identifies a row"
}"""
        }
    ]

