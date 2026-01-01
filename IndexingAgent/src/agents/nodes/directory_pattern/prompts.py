# src/agents/nodes/directory_pattern/prompts.py
"""
Directory Pattern 프롬프트

디렉토리 내 파일명 패턴을 분석하기 위한 LLM 프롬프트

Note: 이 프롬프트는 Pydantic 모델이 없는 복잡한 JSON 응답을 반환합니다.
      custom_output_format을 사용하여 Output Format을 직접 정의합니다.
"""

from src.agents.prompts import PromptTemplate


class DirectoryPatternPrompt(PromptTemplate):
    """
    Directory Pattern 프롬프트
    
    디렉토리별 파일명 패턴 분석:
    - 파일명 패턴 식별
    - 패턴에서 추출 가능한 값과 Data Dictionary 매칭
    """
    
    name = "directory_pattern"
    response_model = None  # 복잡한 구조로 Pydantic 미사용
    response_wrapper_key = "directories"
    is_list_response = True
    
    system_role = "You are a medical dataset filename pattern analysis expert."
    
    task_description = """Given directory filename samples and a data dictionary, analyze:
1. Identify filename patterns for each directory
2. Determine which columns from the data dictionary match values extractable from filenames"""
    
    context_template = """## Data Dictionary
The following tables and columns are available in this dataset:

{data_dictionary}

## Directories to Analyze

{directories_info}

Analyze the filename patterns for each directory and match extractable values to data dictionary columns."""
    
    rules = [
        "pattern_regex must be a valid PostgreSQL regex (use \\\\ for backslash in JSON)",
        "position is 1-indexed capture group number",
        "type should be 'integer' or 'text'",
        "Only set has_pattern=true if a clear, consistent pattern exists",
        "matched_column should reference exact column name from data dictionary",
        "If no matching column found in data dictionary, set matched_column to null",
    ]
    
    # 복잡한 구조는 custom_output_format으로 직접 정의
    # Note: dir_name을 식별자로 사용 (UUID는 LLM 외부에서 관리)
    custom_output_format = """{
    "directories": [
        {
            "dir_name": "string - Directory name from input (used as identifier)",
            "has_pattern": "boolean - true if consistent pattern found",
            "pattern": "string or null - Pattern like '{caseid:integer}.vital'",
            "pattern_regex": "string or null - PostgreSQL regex for extraction",
            "columns": [
                {
                    "name": "string - Extracted value name (e.g., 'caseid')",
                    "type": "string - 'integer' or 'text'",
                    "position": "integer - 1-indexed capture group",
                    "matched_column": "string or null - Matching column from data dictionary",
                    "match_confidence": "float (0.0-1.0) - Confidence of match",
                    "match_reasoning": "string - Explanation"
                }
            ],
            "confidence": "float (0.0-1.0) - Overall pattern confidence",
            "reasoning": "string - Explanation of pattern analysis"
        }
    ]
}"""
    
    # Few-shot 예시
    examples = [
        {
            "input": "Directory 'patient_records' with files: patient_001.csv, patient_002.csv, patient_003.csv...",
            "output": """{
    "dir_name": "patient_records",
    "has_pattern": true,
    "pattern": "patient_{record_id:integer}.csv",
    "pattern_regex": "^patient_(\\\\d+)\\\\.csv$",
    "columns": [
        {
            "name": "record_id",
            "type": "integer",
            "position": 1,
            "matched_column": "patient_id",
            "match_confidence": 0.95,
            "match_reasoning": "Numeric value matches patient_id format in main data table"
        }
    ],
    "confidence": 0.95,
    "reasoning": "All files follow patient_{number}.csv pattern"
}"""
        },
        {
            "input": "Directory 'misc' with files: data.csv, report.pdf, notes.txt...",
            "output": """{
    "dir_name": "misc",
    "has_pattern": false,
    "pattern": null,
    "pattern_regex": null,
    "columns": [],
    "confidence": 0.9,
    "reasoning": "Various files with no consistent naming pattern"
}"""
        }
    ]

