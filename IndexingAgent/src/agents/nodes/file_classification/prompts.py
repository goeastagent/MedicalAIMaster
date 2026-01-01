# src/agents/nodes/file_classification/prompts.py
"""
File Classification 프롬프트

파일을 metadata/data로 분류하기 위한 LLM 프롬프트 정의
"""

from src.agents.prompts import PromptTemplate
from src.agents.models.llm_responses import FileClassificationItem


class FileClassificationPrompt(PromptTemplate):
    """
    File Classification 프롬프트
    
    파일을 metadata(데이터 사전) vs data(실제 데이터)로 분류
    """
    
    name = "file_classification"
    response_model = FileClassificationItem
    response_wrapper_key = "classifications"
    is_list_response = True
    
    system_role = "You are a Medical Data Expert specializing in healthcare informatics."
    
    task_description = """Classify each file as "metadata" or "data":

**metadata** files:
- Data dictionaries, codebooks, parameter definitions, lookup tables
- Typically contain columns like: Parameter, Description, Unit, Code, Category
- Values are mostly text descriptions, definitions, or codes
- Purpose: Define or describe what data means
- Examples: clinical_parameters.csv, lab_parameters.csv, track_names.csv

**data** files:
- Actual measurements, patient records, lab results, vital signs
- Typically contain columns like: patient_id, timestamp, measured values
- Values are mostly numbers, IDs, dates, measurements
- Purpose: Store actual recorded data
- Examples: clinical_data.csv, lab_data.csv, vitals.csv"""
    
    context_template = """[Files to Classify]
{files_info}"""
    
    rules = [
        "Return ONLY valid JSON (no markdown, no explanation)",
        "Include confidence score (0.0-1.0) for each classification",
        "Provide brief reasoning for each classification decision",
    ]

