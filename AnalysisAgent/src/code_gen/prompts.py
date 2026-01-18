"""Code Generation 프롬프트 템플릿

LLM에게 코드 생성을 요청할 때 사용하는 프롬프트.
- 기본 코드 생성 프롬프트
- Map-Reduce 패턴 프롬프트 (대용량 데이터 처리)
"""

from typing import Tuple, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import CodeRequest, DataSchema, MapReduceRequest


def _format_data_schemas(schemas: Dict[str, "DataSchema"]) -> str:
    """데이터 스키마를 프롬프트용 텍스트로 변환
    
    Args:
        schemas: 변수명 -> DataSchema 매핑
    
    Returns:
        포맷팅된 텍스트
    """
    if not schemas:
        return ""
    
    lines = ["## Data Structure Details (IMPORTANT: Use exact column names!)"]
    
    for schema in schemas.values():
        lines.append("")
        lines.append(schema.to_prompt_text())
    
    return "\n".join(lines)


SYSTEM_PROMPT = """You are a Python code generator for medical data analysis.

## Your Task
Generate Python code that accomplishes the user's analysis task.

## ⚠️ CRITICAL: Available Variables (ONLY use these - they are already defined)
{available_variables}

**YOU MUST ONLY USE THE VARIABLES LISTED ABOVE.**
- If `signals` is listed → use `signals`
- If `df` is listed → use `df`  
- DO NOT assume variables exist if they are not listed above.

## Pre-imported Modules (already available, use directly)
{allowed_imports}

{data_structure_section}

## 📡 High-Resolution Data Loading with VitalDB (IMPORTANT)
The `signals` data provided is pre-loaded at 1Hz (1-second intervals). 
If the task requires **high-resolution data** (e.g., 500Hz ECG, 125Hz PPG, 10Hz, 20Hz, etc.), 
you MUST load the data directly from VitalDB. The `vitaldb` module is already available:

```python
# vitaldb is already pre-imported - use directly without import statement
# Load high-resolution signal data
# Parameters: case_id (int), track_names (list of str), interval (float in seconds)

# Example: Load ECG at 500Hz (interval = 1/500 = 0.002 seconds)
vals = vitaldb.load_case(case_id, ['SNUADC/ECG_II'], 1/500)  # Returns numpy array

# Example: Load PPG at 125Hz (interval = 1/125 = 0.008 seconds)  
vals = vitaldb.load_case(case_id, ['SNUADC/PLETH'], 1/125)

# Example: Load vital signs at 10Hz (interval = 0.1 seconds)
vals = vitaldb.load_case(case_id, ['Solar8000/HR'], 0.1)

# The returned array shape is (num_samples, num_tracks)
# If vals is None or empty, handle gracefully
```

**Common VitalDB track names:**
- ECG: 'SNUADC/ECG_II' (typically 500Hz native)
- PPG/Pleth: 'SNUADC/PLETH' (typically 125Hz native)
- Vital Signs: 'Solar8000/HR', 'Solar8000/ART_SBP', 'Solar8000/ART_DBP', 'Solar8000/ART_MBP' (typically 1Hz native)

**When to use VitalDB direct loading:**
- When the task explicitly mentions sampling rates like "500Hz", "125Hz", "10Hz", "20Hz"
- When analyzing waveform morphology or detecting peaks
- When high temporal resolution is required

**When to use the pre-loaded `signals`:**
- For standard aggregations (mean, max, min) at 1-second resolution
- When no specific high sampling rate is mentioned

## STRICT RULES - MUST FOLLOW
1. ⚠️ ONLY use variables from "Available Variables" section above - DO NOT assume other variables exist
2. DO NOT use: os, subprocess, sys, open(), eval(), exec(), __import__
3. DO NOT read/write files or make network requests
4. DO NOT define functions or classes (write inline code only)
5. Use vectorized pandas/numpy operations instead of explicit loops when possible
6. ⚠️ NaN HANDLING: Medical data typically contains NaN values. Write NaN-resistant code that produces correct results even when NaN values are present in the data.
7. The final result MUST be assigned to a variable named `result`
8. DO NOT import modules - pd, np, stats, vitaldb, signal (scipy.signal), interpolate (scipy.interpolate) are already available
9. Use EXACT column names as shown in Data Structure Details
10. DO NOT use variable names starting with underscore (_)

## Output Format
- Return ONLY the Python code
- Wrap code in ```python ... ``` block
- Code must be complete and executable
- The `result` variable must contain the final answer
- ⚠️ IMPORTANT: When the expected output format specifies exact keys, return ONLY those keys. DO NOT add any extra metadata keys (e.g., identifiers, timestamps, source info) unless explicitly requested.
"""


USER_PROMPT = """## Task
{task_description}

## Expected Output Format
{expected_output}
{hints_section}
{constraints_section}

Generate the Python code now:"""


ERROR_FIX_PROMPT = """The previous code failed with the following error:

## Previous Code
```python
{previous_code}
```

## Error
{error_message}
{error_specific_guidance}

## ⚠️ REMINDER: Available Variables
Refer back to the Available Variables section in the original prompt.
ONLY use variables that were explicitly listed there.

Please fix the code and try again. Remember:
1. ⚠️ ONLY use variables from the "Available Variables" section - check the original prompt
2. Assign the final result to `result` variable
3. Handle edge cases and NaN values
4. Follow all the rules from the original prompt
5. DO NOT import modules - use the pre-imported ones (pd, np, stats, etc.)
6. DO NOT use variable names starting with underscore (_)

Generate the fixed Python code:"""


def _get_error_specific_guidance(error_message: str) -> str:
    """에러 메시지에 따른 구체적인 수정 가이드 생성
    
    Args:
        error_message: 에러 메시지
    
    Returns:
        구체적인 수정 가이드 문자열
    """
    guidance_parts = []
    error_lower = error_message.lower()
    
    # TypeError: 'X' object is not iterable
    if "not iterable" in error_lower:
        guidance_parts.append("""
## FIX: Object Not Iterable
The object you're trying to iterate over or unpack is not iterable.

Common causes:
1. Trying to unpack a single value: `a, b = some_number`
2. Function returned a scalar instead of a tuple/list
3. Wrong variable type

Solutions:
- Check the return type of the function you're calling
- If you need multiple values, ensure the function returns them
- For scipy.stats: `r, p = stats.pearsonr(x, y)` should work, but check your inputs are valid arrays
- For single values: don't try to unpack, just assign directly""")
    
    # NameError - undefined variable
    elif "nameerror" in error_lower and "not defined" in error_lower:
        # 특정 변수 추출 시도
        import re
        var_match = re.search(r"name ['\"](\w+)['\"] is not defined", error_message)
        undefined_var = var_match.group(1) if var_match else "unknown"
        
        guidance_parts.append(f"""
## FIX: Variable '{undefined_var}' Not Defined

**CRITICAL**: You used `{undefined_var}` but it does NOT exist.
Check the "Available Variables" section in the original prompt and ONLY use those variables.

Common mistakes:
- Using `signals` when only `df` is available (or vice versa)
- Using `cohort` when it's not provided
- Using `case_ids` when it's not provided

**Action Required**: 
1. Re-read the "Available Variables" section
2. Use ONLY the variables listed there
3. If you need `{undefined_var}`, it must be created from the available variables first""")
    
    # KeyError - column not found
    elif "keyerror" in error_lower:
        guidance_parts.append("""
## FIX: Column/Key Not Found
- Check the exact column names in the DataFrame
- Column names are case-sensitive
- Use .columns to see available columns if unsure""")
    
    # globals/eval/exec forbidden
    elif "globals" in error_lower or "forbidden" in error_lower:
        guidance_parts.append("""
## FIX: Forbidden Pattern Detected
DO NOT use any of these:
- globals(), locals(), eval(), exec()
- __import__, __builtins__
- Any double-underscore (__) names
- Variable names starting with underscore (_)

Use simple, direct code without dynamic evaluation.""")
    
    # TypeError: unsupported operand type
    elif "typeerror" in error_lower and "operand" in error_lower:
        guidance_parts.append("""
## FIX: Type Mismatch
- Ensure numeric operations use numeric types
- Convert strings to numbers: pd.to_numeric(col, errors='coerce')
- Check for mixed types in columns: df[col].dtype""")
    
    return "\n".join(guidance_parts) if guidance_parts else ""


def build_prompt(request: "CodeRequest") -> Tuple[str, str]:
    """CodeRequest로부터 프롬프트 생성
    
    Args:
        request: 코드 생성 요청
    
    Returns:
        (system_prompt, user_prompt) 튜플
    
    Example:
        system, user = build_prompt(request)
        response = llm.ask_text(f"{system}\n\n{user}")
    """
    ctx = request.execution_context
    
    # 변수 설명 포맷팅
    var_desc = "\n".join([
        f"- `{name}`: {desc}"
        for name, desc in ctx.available_variables.items()
    ])
    
    # Import 목록 포맷팅
    imports = "\n".join([f"- {imp}" for imp in ctx.available_imports])
    
    # 데이터 구조 섹션 (스키마 우선, 없으면 sample_data)
    data_structure_section = ""
    if ctx.data_schemas:
        data_structure_section = _format_data_schemas(ctx.data_schemas)
    elif ctx.sample_data:
        import json
        try:
            sample = json.dumps(ctx.sample_data, indent=2, default=str, ensure_ascii=False)
            data_structure_section = f"## Sample Data (for reference only)\n{sample}"
        except:
            data_structure_section = f"## Sample Data\n{ctx.sample_data}"
    
    system = SYSTEM_PROMPT.format(
        available_variables=var_desc,
        allowed_imports=imports,
        data_structure_section=data_structure_section
    )
    
    # 힌트 섹션
    hints_section = ""
    if request.hints:
        hints_section = f"\n## Hints\n{request.hints}"
    
    # 제약사항 섹션
    constraints_section = ""
    if request.constraints:
        constraints_section = "\n## Additional Constraints\n" + "\n".join(
            f"- {c}" for c in request.constraints
        )
    
    user = USER_PROMPT.format(
        task_description=request.task_description,
        expected_output=request.expected_output,
        hints_section=hints_section,
        constraints_section=constraints_section
    )
    
    return system, user


def build_error_fix_prompt(
    request: "CodeRequest",
    previous_code: str,
    error_message: str
) -> Tuple[str, str]:
    """에러 수정을 위한 프롬프트 생성
    
    Args:
        request: 원본 코드 생성 요청
        previous_code: 실패한 이전 코드
        error_message: 에러 메시지
    
    Returns:
        (system_prompt, user_prompt) 튜플
    """
    system, _ = build_prompt(request)
    
    # 에러별 구체적인 가이드 생성
    error_specific_guidance = _get_error_specific_guidance(error_message)
    
    user = ERROR_FIX_PROMPT.format(
        previous_code=previous_code,
        error_message=error_message,
        error_specific_guidance=error_specific_guidance
    )
    
    return system, user


# =============================================================================
# Map-Reduce 패턴 프롬프트 (대용량 데이터 처리용, 범용)
# =============================================================================

MAPREDUCE_SYSTEM_PROMPT = """You are a Python code generator for Map-Reduce data analysis.

## Task
Generate `map_func` and `reduce_func` based on the data context provided below.

## Data Context
{data_structure_overview}

## Function Signatures

```python
def map_func(entity_id: str, entity_data: pd.DataFrame, metadata_row: pd.Series) -> Any:
    # Process ONE entity, return intermediate result (or None to skip)
    ...

def reduce_func(intermediate_results: List[Any], full_metadata: pd.DataFrame) -> Any:
    # Aggregate all map results into final result
    ...
```

## Pre-imported Modules
{allowed_imports}

{detailed_schema_section}

## Rules
1. Use ONLY column names shown in the Data Context above
2. Handle NaN and empty DataFrames gracefully
3. Return None from map_func to skip invalid entities
4. DO NOT import modules (already available: pd, np, stats, etc.)
5. DO NOT use: os, subprocess, eval, exec, open

## Output
Return Python code with both functions in ```python``` block.
"""


MAPREDUCE_USER_PROMPT = """## Analysis Task
{task_description}

## Expected Final Output Format
{expected_output}

## Dataset Information
- Dataset type: {dataset_type}
- Total entities to process: {total_entities}
- Entity identifier column: `{entity_id_column}`

{entity_data_section}

{metadata_section}

{hints_section}
{constraints_section}

Generate the map_func and reduce_func now:"""


MAPREDUCE_ERROR_FIX_PROMPT = """The previous Map-Reduce code failed with the following error:

## Previous Code
```python
{previous_code}
```

## Error
{error_message}

## Error Phase
{error_phase}

{error_specific_guidance}

Please fix the code. Remember:
1. `map_func` receives: entity_id (str), entity_data (DataFrame), metadata_row (Series)
2. `reduce_func` receives: intermediate_results (List), full_metadata (DataFrame)
3. Handle edge cases: empty DataFrames, NaN values, empty lists
4. Use EXACT column names from the Data Structure section
5. Return None from map_func if entity should be skipped

Generate the fixed map_func and reduce_func:"""


# =============================================================================
# 동적 스키마 생성 함수 (범용)
# =============================================================================

def build_data_structure_overview(
    entity_id_column: str,
    entity_data_columns: List[str],
    entity_data_dtypes: Dict[str, str],
    metadata_columns: List[str],
    metadata_dtypes: Dict[str, str],
    dataset_type: Optional[str] = None,
    dataset_description: Optional[str] = None,
) -> str:
    """데이터 구조 개요 동적 생성 (프롬프트 시스템 섹션용)
    
    Args:
        entity_id_column: 엔티티 식별자 컬럼명
        entity_data_columns: 엔티티 데이터 컬럼 목록
        entity_data_dtypes: 엔티티 데이터 타입
        metadata_columns: 메타데이터 컬럼 목록
        metadata_dtypes: 메타데이터 타입
        dataset_type: 데이터셋 유형
        dataset_description: 데이터셋 설명
    
    Returns:
        프롬프트용 데이터 구조 설명 문자열
    """
    lines = []
    
    # 데이터셋 설명
    if dataset_type or dataset_description:
        lines.append("### Dataset")
        if dataset_type:
            lines.append(f"- Type: {dataset_type}")
        if dataset_description:
            lines.append(f"- Description: {dataset_description}")
        lines.append("")
    
    # 엔티티 구조
    lines.append("### Entity Structure")
    lines.append(f"- Each entity is uniquely identified by `{entity_id_column}`")
    lines.append(f"- `entity_data`: pd.DataFrame containing data for ONE entity")
    
    if entity_data_columns:
        lines.append(f"- Entity data columns ({len(entity_data_columns)}): {entity_data_columns}")
    
    lines.append("")
    
    # 메타데이터 구조
    lines.append("### Metadata Structure")
    if metadata_columns:
        lines.append(f"- `metadata_row`: pd.Series containing metadata for ONE entity")
        lines.append(f"- Metadata columns ({len(metadata_columns)}): {metadata_columns}")
        lines.append(f"- `full_metadata`: pd.DataFrame containing ALL entities' metadata")
    else:
        lines.append("- No metadata available")
        lines.append("- `metadata_row` will be an empty pd.Series")
        lines.append("- `full_metadata` will be an empty pd.DataFrame")
    
    return "\n".join(lines)


def build_entity_data_section(
    columns: List[str],
    dtypes: Dict[str, str],
    sample_data: Optional[str] = None,
) -> str:
    """엔티티 데이터 스키마 상세 설명 (프롬프트 사용자 섹션용)
    
    Args:
        columns: 컬럼 목록
        dtypes: 컬럼별 데이터 타입
        sample_data: 샘플 데이터 문자열 (DataFrame.to_string())
    
    Returns:
        프롬프트용 엔티티 데이터 설명
    """
    if not columns:
        return "## Entity Data\nNo entity data columns defined."
    
    lines = []
    lines.append("## Entity Data Schema (`entity_data: pd.DataFrame`)")
    lines.append("")
    lines.append("⚠️ **CRITICAL: ONLY USE THESE EXACT COLUMN NAMES** ⚠️")
    lines.append("DO NOT assume or invent column names like 'Time', 'Timestamp', 'Index', etc.")
    lines.append("The ONLY available columns are listed below:")
    lines.append("")
    lines.append(f"Available Columns ({len(columns)}):")
    
    for col in columns:
        dtype = dtypes.get(col, "unknown")
        lines.append(f"  - `{col}` ({dtype})")
    
    lines.append("")
    lines.append("⚠️ If you need time information, look for it in the columns above.")
    lines.append("⚠️ If no time column exists, use the DataFrame index for time-based operations.")
    
    if sample_data:
        lines.append("")
        lines.append("Sample data (first few rows from one entity):")
        lines.append("```")
        lines.append(sample_data)
        lines.append("```")
    
    return "\n".join(lines)


def build_metadata_section(
    columns: List[str],
    dtypes: Dict[str, str],
    entity_id_column: str,
    sample_data: Optional[str] = None,
) -> str:
    """메타데이터 스키마 상세 설명 (프롬프트 사용자 섹션용)
    
    Args:
        columns: 컬럼 목록
        dtypes: 컬럼별 데이터 타입
        entity_id_column: 엔티티 식별자 컬럼
        sample_data: 샘플 데이터 문자열
    
    Returns:
        프롬프트용 메타데이터 설명
    """
    if not columns:
        return "## Metadata\nNo metadata available. `metadata_row` will be empty."
    
    lines = []
    lines.append("## Metadata Schema (`metadata_row: pd.Series`, `full_metadata: pd.DataFrame`)")
    lines.append(f"Entity ID column: `{entity_id_column}`")
    lines.append(f"Columns ({len(columns)}):")
    
    for col in columns:
        dtype = dtypes.get(col, "unknown")
        marker = " ← entity identifier" if col == entity_id_column else ""
        lines.append(f"  - `{col}` ({dtype}){marker}")
    
    if sample_data:
        lines.append("")
        lines.append("Sample metadata (first few rows):")
        lines.append("```")
        lines.append(sample_data)
        lines.append("```")
    
    return "\n".join(lines)


def build_mapreduce_prompt(request: "MapReduceRequest") -> Tuple[str, str]:
    """MapReduceRequest로부터 프롬프트 생성
    
    Args:
        request: Map-Reduce 코드 생성 요청
    
    Returns:
        (system_prompt, user_prompt) 튜플
    
    Example:
        system, user = build_mapreduce_prompt(request)
        response = llm.ask_text(f"{system}\\n\\n{user}")
    """
    # 데이터 구조 개요 생성
    data_overview = build_data_structure_overview(
        entity_id_column=request.entity_id_column,
        entity_data_columns=request.entity_data_columns,
        entity_data_dtypes=request.entity_data_dtypes,
        metadata_columns=request.metadata_columns,
        metadata_dtypes=request.metadata_dtypes,
        dataset_type=request.dataset_type,
        dataset_description=request.dataset_description,
    )
    
    # 엔티티 데이터 섹션
    entity_section = build_entity_data_section(
        columns=request.entity_data_columns,
        dtypes=request.entity_data_dtypes,
        sample_data=request.entity_data_sample,
    )
    
    # 메타데이터 섹션
    metadata_section = build_metadata_section(
        columns=request.metadata_columns,
        dtypes=request.metadata_dtypes,
        entity_id_column=request.entity_id_column,
        sample_data=request.metadata_sample,
    )
    
    # Import 목록 포맷팅
    imports = "\n".join([f"- {imp}" for imp in request.allowed_imports])
    
    # 시스템 프롬프트
    system = MAPREDUCE_SYSTEM_PROMPT.format(
        data_structure_overview=data_overview,
        allowed_imports=imports,
        detailed_schema_section=entity_section,
    )
    
    # 힌트 섹션
    hints_section = ""
    if request.hints:
        hints_section = f"\n## Implementation Hints\n{request.hints}"
    
    # 제약사항 섹션
    constraints_section = ""
    if request.constraints:
        constraints_section = "\n## Additional Constraints\n" + "\n".join(
            f"- {c}" for c in request.constraints
        )
    
    # 사용자 프롬프트
    user = MAPREDUCE_USER_PROMPT.format(
        task_description=request.task_description,
        expected_output=request.expected_output,
        dataset_type=request.dataset_type or "Unknown",
        total_entities=request.total_entities,
        entity_id_column=request.entity_id_column,
        entity_data_section=entity_section,
        metadata_section=metadata_section,
        hints_section=hints_section,
        constraints_section=constraints_section,
    )
    
    return system, user


def build_mapreduce_error_fix_prompt(
    previous_code: str,
    error_message: str,
    request: "MapReduceRequest",
    error_phase: str = "unknown",
) -> str:
    """Map-Reduce 에러 수정 프롬프트 생성 (단일 프롬프트 반환)
    
    에러 메시지를 분석하여 구체적인 수정 가이드를 제공합니다.
    힌트 없이 동작하는 시스템에서, 에러 발생 시에만 구체적인 가이드를 제공합니다.
    
    Args:
        previous_code: 실패한 코드
        error_message: 에러 메시지
        request: 원본 MapReduceRequest
        error_phase: 에러 발생 단계 ("map", "reduce", "validation")
    
    Returns:
        수정 요청 프롬프트 문자열
    """
    # 에러 메시지 기반 구체적 가이드 생성
    specific_guidance = _get_mapreduce_error_guidance(error_message, error_phase, request)
    
    prompt = MAPREDUCE_ERROR_FIX_PROMPT.format(
        previous_code=previous_code,
        error_message=error_message,
        error_phase=error_phase,
        error_specific_guidance=specific_guidance,
    )
    
    return prompt


def _get_mapreduce_error_guidance(
    error_message: str, 
    error_phase: str,
    request: "MapReduceRequest" = None,
) -> str:
    """Map-Reduce 에러 메시지에 따른 구체적인 수정 가이드
    
    에러 메시지를 분석하여 문제 해결에 필요한 구체적인 힌트를 생성합니다.
    
    Args:
        error_message: 에러 메시지
        error_phase: 에러 발생 단계
        request: 원본 요청 (컬럼 정보 참조용)
    
    Returns:
        수정 가이드 문자열
    """
    import re
    
    guidance_parts = []
    error_lower = error_message.lower()
    
    # 실제 컬럼 목록 (있으면)
    actual_columns = request.entity_data_columns if request else []
    metadata_columns = request.metadata_columns if request else []
    
    # === KeyError - 컬럼 없음 ===
    if "keyerror" in error_lower:
        # 에러 메시지에서 문제된 컬럼명 추출
        col_match = re.search(r"keyerror[:\s]*['\"]?(\w+)['\"]?", error_message, re.IGNORECASE)
        problem_col = col_match.group(1) if col_match else "unknown"
        
        guidance_parts.append(f"""
## FIX: KeyError - Column '{problem_col}' Not Found

The column '{problem_col}' does NOT exist in the data.

**Available entity_data columns:** {actual_columns}
**Available metadata columns:** {metadata_columns}

**Solutions:**
1. Use one of the actual column names listed above
2. If you need time/index: use `entity_data.index` (row position: 0, 1, 2, ...)
3. Check column existence: `if '{problem_col}' in entity_data.columns:`""")
    
    # === Index/Time 관련 에러 ===
    elif "'time'" in error_lower or "'timestamp'" in error_lower or "index" in error_lower:
        guidance_parts.append(f"""
## FIX: Time/Index Column Not Found

This dataset does NOT have a 'Time' or 'Timestamp' column.

**Available columns:** {actual_columns}

**Solutions:**
1. Use `entity_data.index` for row position (0, 1, 2, ...)
2. Use `len(entity_data)` for total rows
3. Segment by position: `entity_data.iloc[start:end]`""")
    
    # === TypeError ===
    elif "typeerror" in error_lower:
        if "nonetype" in error_lower or "'nonetype'" in error_lower:
            guidance_parts.append("""
## FIX: NoneType Error

A value is None when it shouldn't be.

**Solutions:**
1. Check for empty DataFrame: `if entity_data.empty: return None`
2. Check for None before operations: `if value is None: return None`
3. Use `.dropna()` before calculations""")
        elif "not iterable" in error_lower:
            guidance_parts.append("""
## FIX: Not Iterable Error

Trying to iterate over a non-iterable value.

**Solutions:**
1. Check return type of functions you're calling
2. Ensure you're not unpacking a single value: `a, b = scalar` is wrong
3. Wrap single values in list if needed: `[value]`""")
        else:
            guidance_parts.append("""
## FIX: Type Error

Data type mismatch in operation.

**Solutions:**
1. Convert to numeric: `pd.to_numeric(col, errors='coerce')`
2. Check dtypes: `entity_data.dtypes`
3. Handle mixed types appropriately""")
    
    # === ValueError ===
    elif "valueerror" in error_lower:
        guidance_parts.append("""
## FIX: Value Error

Invalid value for operation.

**Solutions:**
1. Check for empty sequences before operations
2. Handle edge cases: `if len(data) == 0: return None`
3. Validate inputs before calculations""")
    
    # === Empty/NaN 관련 ===
    elif "empty" in error_lower or "nan" in error_lower or "no data" in error_lower:
        guidance_parts.append("""
## FIX: Empty Data or NaN

Data is empty or contains only NaN values.

**Solutions:**
1. Early return: `if entity_data.empty: return None`
2. Drop NaN: `values = entity_data[col].dropna()`
3. Check length: `if len(values) == 0: return None`""")
    
    # === 단계별 기본 가이드 (위 패턴에 해당하지 않을 때) ===
    if not guidance_parts:
        if error_phase == "map":
            guidance_parts.append("""
## Map Phase Error

**Common issues:**
- Accessing non-existent columns
- Not handling empty/NaN data
- Type mismatches

**Quick fixes:**
1. Add: `if entity_data.empty: return None`
2. Use `.dropna()` before calculations
3. Check column existence before access""")
        elif error_phase == "reduce":
            guidance_parts.append("""
## Reduce Phase Error

**Common issues:**
- Empty intermediate_results list
- Inconsistent types from map_func

**Quick fixes:**
1. Add: `if not intermediate_results: return None`
2. Filter None: `results = [r for r in intermediate_results if r is not None]`
3. Ensure map_func returns consistent types""")
    
    return "\n".join(guidance_parts)

