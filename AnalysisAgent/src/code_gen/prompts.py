"""Code Generation 프롬프트 템플릿

LLM에게 코드 생성을 요청할 때 사용하는 프롬프트.
"""

from typing import Tuple, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import CodeRequest, DataSchema


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

## Available Variables (already defined, DO NOT import or create them)
{available_variables}

## Pre-imported Modules (already available, use directly)
{allowed_imports}

{data_structure_section}

## STRICT RULES - MUST FOLLOW
1. DO NOT use: os, subprocess, sys, open(), eval(), exec(), __import__
2. DO NOT read/write files
3. DO NOT make network requests
4. DO NOT define functions or classes (write inline code only)
5. Use vectorized pandas/numpy operations instead of explicit loops when possible
6. Handle NaN/missing values with .dropna() or .fillna()
7. The final result MUST be assigned to a variable named `result`
8. DO NOT import modules - they are already available (pd, np, stats, etc.)
9. Use EXACT column names as shown in Data Structure Details
10. DO NOT use variable names starting with underscore (_) - use names like `tmp`, `data`, `cleaned` instead of `_tmp`, `_data`

## Output Format
- Return ONLY the Python code
- Wrap code in ```python ... ``` block
- Code must be complete and executable
- The `result` variable must contain the final answer
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

Please fix the code and try again. Remember:
1. Assign the final result to `result` variable
2. Handle edge cases and NaN values
3. Follow all the rules from the original prompt
4. DO NOT import modules - use the pre-imported ones (pd, np, stats, etc.)
5. DO NOT use variable names starting with underscore (_) - use `tmp`, `data` instead of `_tmp`, `_data`

Generate the fixed Python code:"""


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
    
    user = ERROR_FIX_PROMPT.format(
        previous_code=previous_code,
        error_message=error_message
    )
    
    return system, user

