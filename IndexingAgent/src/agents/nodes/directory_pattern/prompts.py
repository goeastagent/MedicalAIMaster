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


class GroupPatternPrompt(PromptTemplate):
    """
    Group Pattern 프롬프트
    
    파일 그룹의 샘플 파일명에서 패턴을 분석하고 값을 추출합니다.
    [700] directory_pattern 노드에서 그룹화된 파일 처리에 사용됩니다.
    """
    
    name = "group_pattern"
    response_model = None  # 복잡한 구조로 Pydantic 미사용
    
    system_role = """You are a filename pattern analysis expert for research datasets.
Your task is to analyze sample filenames from a file group and:
1. Identify the naming pattern
2. Extract meaningful values (IDs, dates, versions, etc.)
3. Generate a regex pattern for automated extraction
4. Match extracted values to known data columns when possible"""
    
    task_description = """Analyze the sample filenames from this file group and extract meaningful patterns and values.
Focus on identifying:
- Entity identifiers (case IDs, patient IDs, subject IDs, record IDs)
- Temporal information (dates, timestamps, versions)
- Categorical information (types, categories, conditions)"""
    
    context_template = """## File Group Information
- Group Name: {group_name}
- Total Files in Group: {file_count}
- File Extensions: {extensions}

## Sample Filenames (representative subset)
{sample_filenames}

## Data Dictionary (Reference for matching)
{data_dictionary}

## Task
1. Analyze the filename pattern in these samples
2. Extract values from each sample filename
3. Generate a regex pattern that can extract these values from ALL files in the group
4. Match extracted columns to the data dictionary if possible"""
    
    rules = [
        "pattern_regex MUST be a valid Python/PostgreSQL regex",
        "Use capturing groups () for each value to extract",
        "position is 1-indexed (first group = 1)",
        "Escape special regex characters properly (\\\\. for literal dot)",
        "sample_extractions should show actual values extracted from each sample",
        "If pattern doesn't apply to ALL samples, set confidence lower",
        "matched_column should be null if no match in data dictionary",
    ]
    
    custom_output_format = """{
    "has_pattern": "boolean - true if consistent pattern found across samples",
    "pattern": "string - Human-readable pattern like '{caseid}.vital'",
    "pattern_regex": "string - Regex pattern with capturing groups, e.g., '^(\\\\d+)\\\\.vital$'",
    "pattern_description": "string - Explanation of what the pattern represents",
    "columns": [
        {
            "name": "string - Semantic name for this value (e.g., 'caseid', 'subject_id')",
            "position": "integer - 1-indexed capture group position in regex",
            "type": "string - 'integer', 'text', 'date', 'uuid'",
            "matched_column": "string or null - Matching column from data dictionary",
            "match_confidence": "float (0.0-1.0)",
            "match_reasoning": "string - Why this matches (or why no match)"
        }
    ],
    "sample_extractions": [
        {
            "filename": "string - Sample filename",
            "values": {"column_name": "extracted_value", ...}
        }
    ],
    "confidence": "float (0.0-1.0) - Overall confidence in the pattern",
    "reasoning": "string - Explanation of pattern analysis"
}"""
    
    examples = [
        {
            "input": """Group: vital_files_caseid, 6388 files, extensions: [.vital]
Samples: 1.vital, 100.vital, 3249.vital, 5000.vital, 6388.vital
Data Dictionary: clinical_data.csv has column 'caseid' (integer, patient case ID)""",
            "output": """{
    "has_pattern": true,
    "pattern": "{caseid}.vital",
    "pattern_regex": "^(\\\\d+)\\\\.vital$",
    "pattern_description": "Numeric case identifier followed by .vital extension",
    "columns": [
        {
            "name": "caseid",
            "position": 1,
            "type": "integer",
            "matched_column": "caseid",
            "match_confidence": 0.98,
            "match_reasoning": "Numeric values match caseid column in clinical_data.csv"
        }
    ],
    "sample_extractions": [
        {"filename": "1.vital", "values": {"caseid": "1"}},
        {"filename": "100.vital", "values": {"caseid": "100"}},
        {"filename": "3249.vital", "values": {"caseid": "3249"}},
        {"filename": "5000.vital", "values": {"caseid": "5000"}},
        {"filename": "6388.vital", "values": {"caseid": "6388"}}
    ],
    "confidence": 0.98,
    "reasoning": "All samples follow consistent {number}.vital pattern where number matches caseid in clinical_data"
}"""
        },
        {
            "input": """Group: eeg_recordings, 150 files, extensions: [.edf]
Samples: subj_001_ses_01_task_rest.edf, subj_001_ses_02_task_motor.edf, subj_002_ses_01_task_rest.edf
Data Dictionary: subjects.csv has 'subject_id', sessions.csv has 'session', tasks.csv has 'task_name'""",
            "output": """{
    "has_pattern": true,
    "pattern": "subj_{subject_id}_ses_{session}_task_{task}.edf",
    "pattern_regex": "^subj_(\\\\d+)_ses_(\\\\d+)_task_([a-z]+)\\\\.edf$",
    "pattern_description": "EEG recording with subject ID, session number, and task name",
    "columns": [
        {
            "name": "subject_id",
            "position": 1,
            "type": "integer",
            "matched_column": "subject_id",
            "match_confidence": 0.95,
            "match_reasoning": "Zero-padded integers match subject_id in subjects.csv"
        },
        {
            "name": "session",
            "position": 2,
            "type": "integer",
            "matched_column": "session",
            "match_confidence": 0.90,
            "match_reasoning": "Session numbers match session column in sessions.csv"
        },
        {
            "name": "task",
            "position": 3,
            "type": "text",
            "matched_column": "task_name",
            "match_confidence": 0.85,
            "match_reasoning": "Task names (rest, motor) likely match task_name in tasks.csv"
        }
    ],
    "sample_extractions": [
        {"filename": "subj_001_ses_01_task_rest.edf", "values": {"subject_id": "001", "session": "01", "task": "rest"}},
        {"filename": "subj_001_ses_02_task_motor.edf", "values": {"subject_id": "001", "session": "02", "task": "motor"}},
        {"filename": "subj_002_ses_01_task_rest.edf", "values": {"subject_id": "002", "session": "01", "task": "rest"}}
    ],
    "confidence": 0.92,
    "reasoning": "Consistent BIDS-like naming convention with subject, session, and task components"
}"""
        }
    ]

