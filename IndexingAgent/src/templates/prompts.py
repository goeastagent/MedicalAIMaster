# src/templates/prompts.py
"""
LLM Prompt Templates

All prompts are defined as string templates with placeholder variables.
Use .format() to fill in the placeholders.
"""

# =============================================================================
# Column Analysis Prompts
# =============================================================================

COLUMN_ANALYSIS_PROMPT = """
You are a Medical Data Ontologist specializing in clinical database design.
Analyze the columns of a medical dataset and provide DETAILED metadata.

[Context]
- Patient Identifier (Anchor): {anchor_column}
- Is Time Series: {is_time_series}

[Columns to Analyze]
{columns_info}

[Task]
For EACH column, provide a JSON object with DETAILED metadata:

1. original_name: The exact column name as provided (REQUIRED)
2. inferred_name: Human-readable name (e.g., 'sbp' → 'Systolic Blood Pressure')
3. full_name: Full medical term without abbreviation
4. description: Brief medical description
5. description_kr: Korean description for Korean users (한글 설명)
6. data_type: SQL compatible type (VARCHAR, INT, FLOAT, TIMESTAMP, BOOLEAN)
7. unit: Measurement unit if applicable (e.g., "mmHg", "kg", null if N/A)
8. typical_range: Normal/typical value range in medical context (null if N/A)
9. is_pii: Boolean (true if it contains name, phone, address, social security number)
10. confidence: 0.0 to 1.0

Respond with a JSON object: {{"columns": [list of column objects]}}
"""

# =============================================================================
# Track Analysis Prompts
# =============================================================================

TRACK_ANALYSIS_PROMPT = """You are a Medical Signal Processing Expert.
Analyze the following signal tracks and provide detailed metadata for each.

[SIGNAL TRACKS - Pre-processed by Rules]
{tracks_summary}

[TASK]
For each track, determine:
1. **inferred_name**: Human-readable name (e.g., 'SNUADC/ECG_II' → 'Lead II ECG')
2. **description**: Brief medical description
3. **clinical_category**: One of: cardiac_waveform, cardiac_vital, respiratory, neurological, temperature, anesthesia, other

[RESPONSE FORMAT - JSON]
{{
    "tracks": {{
        "track_name": {{
            "inferred_name": "Human readable name",
            "description": "Brief description",
            "clinical_category": "category"
        }}
    }}
}}
"""

# =============================================================================
# Metadata Detection Prompts
# =============================================================================

METADATA_DETECTION_PROMPT = """
You are a Data Classification Expert.

I have pre-processed file information using rules. Based on these facts, determine if this is METADATA or TRANSACTIONAL DATA.

[PRE-PROCESSED FILE INFORMATION]
Filename: {filename}
Parsed Name Parts: {name_parts}
Base Name: {base_name}
Extension: {extension}
Number of Columns: {num_columns}
Columns: {columns}

[PRE-PROCESSED SAMPLE DATA]
{sample_data}

[DEFINITION]
- METADATA file: Describes OTHER data (column definitions, parameter lists, codebooks)
- TRANSACTIONAL DATA: Actual records/measurements

[OUTPUT FORMAT - JSON ONLY]
{{
    "is_metadata": true or false,
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation",
    "indicators": {{
        "filename_hint": "strong/weak/none",
        "structure_hint": "dictionary-like/tabular/unclear",
        "content_type": "descriptive/transactional/mixed"
    }}
}}
"""

# =============================================================================
# Anchor Comparison Prompts
# =============================================================================

ANCHOR_COMPARISON_PROMPT = """
You are a Medical Data Integration Agent.
Check if the new file contains the Project's Master Anchor (Patient ID).

[Project Context / Global Master]
- Master Anchor Name: '{master_anchor}'
- Known Aliases: {known_aliases}

[New File Info]
- Candidate Column found by AI: '{local_candidate}'
- All Columns in file: {all_columns}

[Task]
Determine if any column represents the same 'Patient ID' entity as the Global Master.

Respond with JSON:
{{
    "status": "MATCH" or "MISSING" or "CONFLICT",
    "target_column": "name_of_column" or null,
    "message": "Reasoning"
}}
"""

# =============================================================================
# Relationship Inference Prompts
# =============================================================================

RELATIONSHIP_INFERENCE_PROMPT = """
You are a Database Schema Architect for Medical Data Integration.
Infer table relationships from pre-processed data.

[NEW TABLE]
Name: {current_table}
Columns: {current_cols}

[FILENAME HINTS]
{filename_hints}

[FK CANDIDATES (Common Columns)]
{fk_candidates}

[CARDINALITY]
{cardinality}

[EXISTING TABLES]
{existing_tables}

[TASK]
1. Validate FK Candidates using cardinality and filename hints
2. Determine Relationship Type (1:1, 1:N, N:1, M:N)
3. Infer Hierarchy

[OUTPUT FORMAT - JSON]
{{
  "relationships": [
    {{
      "source_table": "{current_table}",
      "target_table": "existing_table_name",
      "source_column": "column_name",
      "target_column": "column_name",
      "relation_type": "N:1",
      "confidence": 0.95,
      "description": "Brief explanation",
      "llm_inferred": true
    }}
  ],
  "hierarchy": [],
  "reasoning": "Overall explanation"
}}
"""

# =============================================================================
# Filename Analysis Prompts
# =============================================================================

FILENAME_ANALYSIS_PROMPT = """
You are a Data Architecture Analyst.
Infer semantic meaning from this parsed filename structure.

[PARSED FILENAME STRUCTURE]
{parsed_structure}

[TASK]
Infer:
1. **Entity Type**: What domain entity does base_name represent?
2. **Scope**: individual, event, measurement, treatment
3. **Suggested Hierarchy Level**: 1(highest) to 5(lowest)
4. **Data Type Indicator**: transactional, metadata, or reference

[OUTPUT FORMAT - JSON]
{{
    "entity_type": "Laboratory" or null,
    "scope": "measurement" or null,
    "suggested_level": 4 or null,
    "data_type_indicator": "transactional" or "metadata",
    "related_file_patterns": [],
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation"
}}
"""

# =============================================================================
# Human Review Decision Prompts
# =============================================================================

REVIEW_DECISION_PROMPT = """
You are an AI assistant helping with medical data processing.
Based on the following situation, decide if human intervention is needed.

[Situation]
- File: {filename}
- Issue Type: {issue_type}
- Rule-based Confidence: {rule_confidence}
- Context: {context}

[Decision Criteria]
Return "needs_review": true if:
1. The context shows ambiguous or conflicting information
2. Critical decisions might affect data integrity
3. Domain expertise is clearly needed
4. Multiple valid interpretations exist

Respond with JSON only:
{{
    "needs_review": true or false,
    "reason": "Brief explanation"
}}
"""

# =============================================================================
# Feedback Parsing Prompts
# =============================================================================

FEEDBACK_PARSING_PROMPT = """The user has provided feedback about the identifier (Anchor) column of a data file.
Interpret this feedback and determine which column should be used.

[File Information]
- Filename: {filename}
- Available Columns: {available_columns}
- Project Master Anchor: {master_anchor}

[User Feedback]
"{feedback}"

[Analysis Request]
1. Identify which column should be used as the Anchor based on the user's feedback.
2. If the feedback describes relationships, select the most appropriate column.
3. Prioritize columns that can link to the Master Anchor.

[Response Format - JSON only]
{{
    "column_name": "Selected column name",
    "reasoning": "Reason for selection",
    "user_intent": "Summary of user's intent"
}}
"""

# =============================================================================
# Question Generation Prompts
# =============================================================================

QUESTION_GENERATION_PROMPT = """You are an AI assistant helping a medical data engineer.
An uncertainty occurred, and you need to ask the user a question.

[Context]
- Filename: {filename}
- Columns: {columns}
- AI Analysis: {reasoning}
{history_context}

[Issue to Resolve]
{task_description}

[Guidelines]
1. Write in clear English
2. Be polite and specific
3. Explain why you're asking
4. Provide options/examples
5. Keep it within 3-5 sentences

Question:"""


# =============================================================================
# Fallback Question Templates
# =============================================================================

FALLBACK_QUESTIONS = {
    "anchor_conflict": """
┌─────────────────────────────────────────────────────────────────────────────┐
│  🔗 Anchor Column Mismatch - Confirmation Required                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     The project's Master Anchor is '{master_anchor}'.
│     However, this file appears to use '{candidates}' as the identifier.
│  
│  💡 AI Analysis:
│     {reasoning}
│  
│  📋 Columns in file:
│     {columns}
│  
│  🎯 Action Required:
│     1. Is '{candidates}' the same as '{master_anchor}'?
│     2. If not, which column corresponds to '{master_anchor}'?
│     3. If none exists, type 'skip'.
└─────────────────────────────────────────────────────────────────────────────┘
""",
    
    "anchor_uncertain": """
┌─────────────────────────────────────────────────────────────────────────────┐
│  🔍 Anchor Column Identification Required                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     AI could not identify a Patient/Case identifier (Anchor) column.
│     Candidate: '{candidates}' (low confidence)
│  
│  💡 AI Analysis:
│     {reasoning}
│  
│  📋 Columns in file:
│     {columns}
│  
│  🎯 Action Required:
│     Please enter the column name that serves as the unique identifier.
│     Type 'skip' if none exists.
└─────────────────────────────────────────────────────────────────────────────┘
""",
    
    "metadata_uncertain": """
┌─────────────────────────────────────────────────────────────────────────────┐
│  📖 File Type Confirmation Required                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     AI cannot determine if this file is 'metadata' or 'actual data'.
│  
│  💡 AI Analysis:
│     {reasoning}
│  
│  📋 Columns in file:
│     {columns}
│  
│  🎯 Action Required:
│     - If metadata (column descriptions): type 'metadata'
│     - If actual patient data: type 'data'
└─────────────────────────────────────────────────────────────────────────────┘
""",
    
    "general_uncertainty": """
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⚠️ Confirmation Required                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     {message}
│  
│  📋 Columns in file:
│     {columns}
│  
│  🎯 User confirmation is required.
└─────────────────────────────────────────────────────────────────────────────┘
"""
}

