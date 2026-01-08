# src/agents/nodes/entity_identification/prompts.py
"""
Entity Identification 프롬프트

각 데이터 테이블이 어떤 Entity를 나타내는지,
고유 식별자 컬럼이 무엇인지 분석하기 위한 LLM 프롬프트
"""

from IndexingAgent.src.agents.prompts import PromptTemplate
from IndexingAgent.src.models.llm_responses import TableEntityResult


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


class GroupEntityPrompt(PromptTemplate):
    """
    Group Entity Identification 프롬프트
    
    파일 그룹 단위로 Entity를 식별합니다.
    그룹의 샘플 파일 하나를 분석하여 전체 그룹에 적용합니다.
    """
    
    name = "group_entity_identification"
    response_model = None  # 커스텀 JSON 응답
    
    system_role = """You are a Medical Data Expert analyzing file groups in clinical datasets.
Your task is to identify what each file in a group represents and how to uniquely identify each file."""
    
    task_description = """Analyze this file group and identify:

1. **row_represents**: What does each FILE in this group represent?
   - For signal files: "surgical_case_vital_signs", "patient_waveform_record", etc.
   - Use a SINGULAR noun phrase
   
2. **entity_identifier_source**: Where does the unique identifier come from?
   - "filename": The identifier is extracted from the filename
   - "content": The identifier is inside the file content
   
3. **entity_identifier_key**: What is the name of the identifier?
   - If from filename: The key name from filename_values (e.g., "caseid", "subject_id")
   - If from content: The column name that uniquely identifies the file"""
    
    context_template = """{group_context}"""
    
    rules = [
        "Focus on what each FILE represents, not what each ROW represents",
        "For signal/waveform files, each file typically represents one recording session",
        "The identifier is often embedded in the filename (look at filename_values)",
        "Pattern columns from directory_pattern analysis indicate the identifier key",
        "If caseid/subject_id/patient_id is in filename_values, that's likely the identifier",
    ]
    
    custom_output_format = """{
    "row_represents": "string - What each file represents (e.g., 'surgical_case_vital_signs')",
    "entity_identifier_source": "string - 'filename' or 'content'",
    "entity_identifier_key": "string - Key name (e.g., 'caseid', 'subject_id')",
    "confidence": "float (0.0-1.0)",
    "reasoning": "string - Explanation of your analysis"
}"""
    
    examples = [
        {
            "input": """File Group: vital_files_caseid (6388 files)
Extensions: [.vital]
Filename Pattern: ^(\\d+)\\.vital$
Pattern Columns: caseid

Sample File: 1.vital
Filename-extracted values: caseid=1
Columns: Time, Solar8000/HR, Solar8000/SpO2, ...""",
            "output": """{
    "row_represents": "surgical_case_vital_signs",
    "entity_identifier_source": "filename",
    "entity_identifier_key": "caseid",
    "confidence": 0.95,
    "reasoning": "Each .vital file contains time-series vital signs for one surgical case. The caseid (1, 2, ..., 6388) is embedded in the filename and matches the pattern. Files are named {caseid}.vital."
}"""
        },
        {
            "input": """File Group: eeg_recordings (150 files)
Extensions: [.edf]
Filename Pattern: ^subj_(\\d+)_ses_(\\d+)_task_([a-z]+)\\.edf$
Pattern Columns: subject_id, session, task

Sample File: subj_001_ses_01_task_rest.edf
Filename-extracted values: subject_id=001, session=01, task=rest
Columns: EEG_FP1, EEG_FP2, EEG_F3, ...""",
            "output": """{
    "row_represents": "eeg_recording_session",
    "entity_identifier_source": "filename",
    "entity_identifier_key": "subject_id",
    "confidence": 0.90,
    "reasoning": "Each .edf file is one EEG recording session for a subject. Files are identified by subject_id, session, and task. Using subject_id as primary identifier for linking to clinical data."
}"""
        }
    ]

