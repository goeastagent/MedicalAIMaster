# src/agents/nodes/file_grouping/prompts.py
"""
File Grouping 프롬프트

디렉토리별로 파일들을 어떻게 그룹핑해야 하는지,
파일명에서 어떤 entity identifier를 추출할 수 있는지 분석하기 위한 LLM 프롬프트

범용적으로 설계되어 다양한 도메인의 데이터셋에 적용 가능:
- 의료 데이터 (MIMIC, PhysioNet, VitalDB)
- 일반 데이터셋 (이미지, 로그, 센서 데이터)
- 분할된 대용량 테이블
"""

from IndexingAgent.src.agents.prompts import PromptTemplate


class FileGroupingPrompt(PromptTemplate):
    """
    File Grouping 프롬프트
    
    각 디렉토리의 파일들이 어떤 그룹핑 전략을 따르는지,
    파일명에서 entity identifier를 추출할 수 있는지 분석합니다.
    """
    
    name = "file_grouping"
    response_wrapper_key = "directories"
    is_list_response = True
    
    system_role = """You are a Data Organization Expert analyzing file naming patterns and structures.
Your task is to determine how files in each directory should be grouped for efficient analysis.
You work with various types of datasets: tabular data, time-series, signals, images, logs, and more."""
    
    task_description = """For each directory, analyze the file patterns and determine:

1. **should_group**: Should these files be grouped together? (true/false)
   - true: Files share a common structure/schema and should be analyzed as a group
   - false: Files are independent with different structures, analyze separately

2. **grouping_strategy**: If should_group=true, what strategy?
   - "pattern_based": Files follow a naming pattern with variable ID parts
     (e.g., "{id}.csv", "subject_{num}.dat", "IMG_{timestamp}.jpg")
   - "partitioned": Files are shards/partitions of a larger dataset
     (e.g., "data_part1.csv", "data_part2.csv", "chunk_001.parquet")
   - "paired": Files come in pairs/groups with different extensions
     (e.g., "record.hea + record.dat", "data.csv + data.json")
   - "single": No grouping needed, each file is independent

3. **filename_pattern**: The detected pattern with placeholders
   - Use {variable_name} for variable parts
   - Examples: "{id}.csv", "{subject}_{session}.dat", "part_{num}.parquet"

4. **entity_identifier_source**: Where is the entity identifier?
   - "filename": Embedded in the filename (e.g., "123.csv" → id=123)
   - "content": Inside the file content (need to read file)
   - null: No clear entity identifier or not applicable

5. **entity_identifier_key**: The key name for the entity identifier
   - Infer from context: "id", "subject_id", "record_id", "session", "timestamp", etc.
   - Use descriptive, lowercase names with underscores
"""
    
    context_template = """[Directories to Analyze]
{directories_context}"""
    
    rules = [
        "If 80%+ of files follow the same naming pattern, they should be grouped",
        "Numeric-only filenames (1.ext, 2.ext, 100.ext) typically indicate entity IDs",
        "Partitioned files (name_1.csv, name_2.csv or name_part1.csv) represent one logical dataset",
        "Paired extensions should be grouped by stem (same name, different extensions)",
        "If files have different naming conventions or structures, do NOT group them",
        "Use the observed_patterns as hints, but make your own judgment based on the full context",
        "For entity_identifier_key, choose a descriptive name that reflects what the ID represents",
        "Consider the domain context when naming: subject_id for per-subject files, session_id for sessions, etc.",
    ]
    
    examples = [
        # Example 1: VitalDB vital signals (medical time-series)
        {
            "input": """Directory: vital_files/
- File count: 6388
- Extensions: {".vital": 6388}
- Samples: ["1.vital", "2.vital", "100.vital", "3000.vital", "6388.vital"]
- Observed patterns: numeric_only (ratio: 1.0, range: 1-6388)""",
            "output": """{
    "dir_path": "vital_files/",
    "should_group": true,
    "grouping_strategy": "pattern_based",
    "filename_pattern": "{caseid}.vital",
    "entity_identifier_source": "filename",
    "entity_identifier_key": "caseid",
    "group_name": "vital_signals",
    "confidence": 0.95,
    "reasoning": "All 6388 .vital files follow numeric-only naming pattern, where each number represents a surgical case ID. Files contain time-series vital sign data with identical schema per case."
}"""
        },
        # Example 2: Generic numeric ID pattern
        {
            "input": """Directory: data_files/
- File count: 5000
- Extensions: {".csv": 5000}
- Samples: ["1.csv", "2.csv", "100.csv", "4999.csv", "5000.csv"]
- Observed patterns: numeric_only (ratio: 1.0, range: 1-5000)""",
            "output": """{
    "dir_path": "data_files/",
    "should_group": true,
    "grouping_strategy": "pattern_based",
    "filename_pattern": "{id}.csv",
    "entity_identifier_source": "filename",
    "entity_identifier_key": "id",
    "group_name": "data_files_by_id",
    "confidence": 0.95,
    "reasoning": "All 5000 files follow numeric-only naming pattern (1.csv to 5000.csv), indicating unique entity IDs embedded in filenames. Files likely share the same schema."
}"""
        },
        # Example 2: Partitioned table (sharded data)
        {
            "input": """Directory: large_table/
- File count: 10
- Extensions: {".parquet": 10}
- Samples: ["events_part_001.parquet", "events_part_002.parquet", "events_part_010.parquet"]
- Observed patterns: partitioned (base: events_part.parquet, count: 10)""",
            "output": """{
    "dir_path": "large_table/",
    "should_group": true,
    "grouping_strategy": "partitioned",
    "filename_pattern": "events_part_{partition}.parquet",
    "entity_identifier_source": null,
    "entity_identifier_key": null,
    "group_name": "events_partitioned",
    "confidence": 0.92,
    "reasoning": "Files are numbered partitions of a single large 'events' table. Should be treated as one logical dataset for schema analysis."
}"""
        },
        # Example 3: Paired files (header + data pattern)
        {
            "input": """Directory: signal_records/
- File count: 400
- Extensions: {".hea": 200, ".dat": 200}
- Samples: ["rec_001.hea", "rec_001.dat", "rec_002.hea", "rec_002.dat"]
- Observed patterns: paired_extensions (pair: [".hea", ".dat"], count: 200)""",
            "output": """{
    "dir_path": "signal_records/",
    "should_group": true,
    "grouping_strategy": "paired",
    "filename_pattern": "rec_{record_id}.{ext}",
    "entity_identifier_source": "filename",
    "entity_identifier_key": "record_id",
    "group_name": "signal_record_pairs",
    "confidence": 0.93,
    "reasoning": "Files come in .hea/.dat pairs where .hea is header metadata and .dat is binary data. Each pair represents one recording identified by record_id."
}"""
        },
        # Example 4: Independent tables (no grouping)
        {
            "input": """Directory: database_export/
- File count: 6
- Extensions: {".csv": 6}
- Samples: ["users.csv", "orders.csv", "products.csv", "categories.csv", "reviews.csv", "inventory.csv"]
- Observed patterns: none""",
            "output": """{
    "dir_path": "database_export/",
    "should_group": false,
    "grouping_strategy": "single",
    "filename_pattern": null,
    "entity_identifier_source": null,
    "entity_identifier_key": null,
    "group_name": null,
    "confidence": 0.90,
    "reasoning": "Each file represents a different database table with unique schema (users, orders, products, etc.). Files should be analyzed independently as they have different structures and purposes."
}"""
        },
        # Example 5: Subject-session pattern
        {
            "input": """Directory: experiment_data/
- File count: 150
- Extensions: {".json": 150}
- Samples: ["subj_01_sess_01.json", "subj_01_sess_02.json", "subj_02_sess_01.json", "subj_50_sess_03.json"]
- Observed patterns: numeric_parts (ratio: 1.0, positions: start, middle)""",
            "output": """{
    "dir_path": "experiment_data/",
    "should_group": true,
    "grouping_strategy": "pattern_based",
    "filename_pattern": "subj_{subject_id}_sess_{session_id}.json",
    "entity_identifier_source": "filename",
    "entity_identifier_key": "subject_id",
    "group_name": "experiment_sessions",
    "confidence": 0.91,
    "reasoning": "Files follow subject_session naming pattern. Primary identifier is subject_id, with session_id as secondary. All files likely share the same JSON schema for experiment results."
}"""
        },
        # Example 6: Timestamped logs
        {
            "input": """Directory: logs/
- File count: 365
- Extensions: {".log": 365}
- Samples: ["2024-01-01.log", "2024-01-02.log", "2024-06-15.log", "2024-12-31.log"]
- Observed patterns: date_pattern (format: YYYY-MM-DD, ratio: 1.0)""",
            "output": """{
    "dir_path": "logs/",
    "should_group": true,
    "grouping_strategy": "pattern_based",
    "filename_pattern": "{date}.log",
    "entity_identifier_source": "filename",
    "entity_identifier_key": "date",
    "group_name": "daily_logs",
    "confidence": 0.94,
    "reasoning": "Files are daily log files with date-based naming (YYYY-MM-DD). All files share the same log format, grouped by date identifier."
}"""
        }
    ]


class FileGroupingResponseSchema:
    """LLM 응답 스키마 정의"""
    
    @staticmethod
    def get_schema():
        return {
            "type": "object",
            "properties": {
                "directories": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dir_path": {"type": "string"},
                            "should_group": {"type": "boolean"},
                            "grouping_strategy": {
                                "type": "string",
                                "enum": ["pattern_based", "partitioned", "paired", "single"]
                            },
                            "filename_pattern": {"type": ["string", "null"]},
                            "entity_identifier_source": {
                                "type": ["string", "null"],
                                "enum": ["filename", "content", None]
                            },
                            "entity_identifier_key": {"type": ["string", "null"]},
                            "group_name": {"type": ["string", "null"]},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "reasoning": {"type": "string"}
                        },
                        "required": ["dir_path", "should_group", "grouping_strategy", "confidence", "reasoning"]
                    }
                }
            },
            "required": ["directories"]
        }
