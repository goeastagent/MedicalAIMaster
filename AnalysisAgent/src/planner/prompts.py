# AnalysisAgent/src/planner/prompts.py
"""
Planning Prompts

Prompt templates for LLM-based analysis planning.
"""

from typing import Dict, List, Any, Optional
import json

from ..context.schema import AnalysisContext, ToolInfo


# =============================================================================
# System Prompt
# =============================================================================

PLANNING_SYSTEM_PROMPT = """You are an expert data analysis planner. Your task is to create a step-by-step execution plan for data analysis queries.

## Your Role
Given a user query and available data context, you will:
1. Understand what the user wants to analyze
2. Break it down into executable steps
3. Determine the best execution approach (Tool or CodeGen)
4. Provide code hints for each step

## Output Format
You MUST respond with a valid JSON object in the following structure:

```json
{
  "analysis_type": "statistics|correlation|comparison|trend|aggregation|general",
  "reasoning": "Brief explanation of your planning approach",
  "steps": [
    {
      "id": "step_1",
      "order": 0,
      "action": "action_name",
      "description": "What this step does",
      "execution_mode": "code",
      "inputs": ["df"],
      "input_columns": ["HR"],
      "parameters": {},
      "output_key": "step_1_result",
      "expected_output_type": "numeric|dataframe|dict|list|bool",
      "code_hint": "df['HR'].mean()",
      "depends_on": []
    }
  ],
  "expected_output": {
    "type": "numeric|dataframe|dict|list",
    "schema": {},
    "description": "Output description"
  },
  "estimated_complexity": "simple|moderate|complex",
  "confidence": 0.9,
  "warnings": []
}
```

## Rules
1. Keep steps atomic - each step should do ONE thing
2. For simple queries (single calculation), use ONE step
3. Code hints should use pandas/numpy/scipy idioms
4. Always handle NaN values appropriately in code hints
5. Prefer vectorized operations over loops
6. The final result must be assigned to 'result' variable in code

## Step Dependencies (CRITICAL)
1. Use `depends_on` to specify which steps must complete before this step runs
2. Use `output_key` to name the result of each step - this becomes available as input for dependent steps
3. The `inputs` field must list all data variables the step needs (e.g., ["df", "filtered_df"])
4. If step B uses the result of step A, then:
   - Step A's `output_key` must be referenced in step B's `inputs`
   - Step B's `depends_on` must include step A's `id`
5. Independent steps (no shared data dependencies) can have empty `depends_on` arrays
6. Steps are executed in topological order based on dependencies, not just by `order` field
7. Circular dependencies are forbidden - the dependency graph must be a DAG

Example of correct dependency chain:
- step_1: output_key="filtered_df", depends_on=[]
- step_2: inputs=["filtered_df"], output_key="stats", depends_on=["step_1"]
- step_3: inputs=["filtered_df", "stats"], depends_on=["step_1", "step_2"]

## Available Tools
{available_tools}

## Constraints
{constraints}
"""


# =============================================================================
# User Prompt
# =============================================================================

PLANNING_USER_PROMPT = """## User Query
{query}

## Available Data
{data_context}

## Additional Context
{additional_context}

Create an execution plan for this analysis query. Respond with ONLY the JSON object, no additional text."""


# =============================================================================
# Prompt Builder
# =============================================================================

def build_planning_prompt(
    query: str,
    context: AnalysisContext,
    additional_context: Optional[str] = None,
) -> tuple[str, str]:
    """
    계획 수립용 프롬프트 생성
    
    Args:
        query: 사용자 분석 쿼리
        context: AnalysisContext
        additional_context: 추가 컨텍스트 (선택)
    
    Returns:
        (system_prompt, user_prompt)
    """
    # 사용 가능한 Tools 포맷팅
    tools_text = format_tools(context.available_tools)
    
    # 제약 조건 포맷팅
    constraints_text = format_constraints(context.constraints)
    
    # 데이터 컨텍스트 포맷팅
    data_context_text = format_data_context(context)
    
    # 추가 컨텍스트
    additional_text = additional_context or "None"
    if context.additional_hints:
        additional_text = context.additional_hints
    
    # 이전 결과 추가
    if context.previous_results:
        additional_text += "\n\n## Previous Results\n"
        for prev in context.previous_results[-3:]:  # 최근 3개만
            additional_text += f"- Query: {prev.get('query', 'N/A')}\n"
            additional_text += f"  Result: {prev.get('result', 'N/A')}\n"
    
    system_prompt = PLANNING_SYSTEM_PROMPT.format(
        available_tools=tools_text,
        constraints=constraints_text,
    )
    
    user_prompt = PLANNING_USER_PROMPT.format(
        query=query,
        data_context=data_context_text,
        additional_context=additional_text,
    )
    
    return system_prompt, user_prompt


def format_tools(tools: List[ToolInfo]) -> str:
    """Tool 목록 포맷팅"""
    if not tools:
        return "No tools available. Use CodeGen (code) for all steps."
    
    lines = []
    for tool in tools:
        lines.append(f"- **{tool.name}**: {tool.description}")
        lines.append(f"  - Tags: {', '.join(tool.tags)}")
        lines.append(f"  - Output: {tool.output_type}")
    
    return "\n".join(lines)


def format_constraints(constraints: List[str]) -> str:
    """제약 조건 포맷팅"""
    if not constraints:
        return "No specific constraints."
    
    return "\n".join(f"- {c}" for c in constraints)


def format_data_context(context: AnalysisContext) -> str:
    """데이터 컨텍스트 포맷팅"""
    sections = []
    
    # 데이터 스키마
    for name, schema in context.data_schemas.items():
        section = [f"### Variable: `{name}`"]
        section.append(f"- Shape: {schema.shape[0]:,} rows × {schema.shape[1]} columns")
        if schema.description:
            section.append(f"- Description: {schema.description}")
        
        section.append("- Columns:")
        for col in schema.columns:
            col_desc = f"  - `{col.name}` ({col.dtype})"
            if col.dtype == "numeric" and col.statistics:
                stats = col.statistics
                col_desc += f" range=[{stats.get('min', '?'):.2f}, {stats.get('max', '?'):.2f}]"
            elif col.dtype == "categorical" and col.unique_count:
                col_desc += f" {col.unique_count} unique values"
            section.append(col_desc)
        
        # 샘플 행 (최대 2개)
        if schema.sample_rows:
            section.append("- Sample rows:")
            for row in schema.sample_rows[:2]:
                # 긴 값 truncate
                truncated = {
                    k: (str(v)[:30] + "..." if len(str(v)) > 30 else v)
                    for k, v in row.items()
                }
                section.append(f"  {truncated}")
        
        sections.append("\n".join(section))
    
    # Join 키
    if context.join_keys:
        sections.append(f"### Join Keys\n{', '.join(context.join_keys)}")
    
    return "\n\n".join(sections)


# =============================================================================
# Response Examples (Few-shot용)
# =============================================================================

EXAMPLE_SIMPLE_STATS = """{
  "analysis_type": "statistics",
  "reasoning": "Simple query for computing descriptive statistics of a single column.",
  "steps": [
    {
      "id": "step_1",
      "order": 0,
      "action": "compute_statistics",
      "description": "Calculate mean and standard deviation of HR column",
      "execution_mode": "code",
      "inputs": ["df"],
      "input_columns": ["HR"],
      "parameters": {},
      "output_key": "stats_result",
      "expected_output_type": "dict",
      "code_hint": "result = {'mean': df['HR'].mean(), 'std': df['HR'].std()}",
      "depends_on": []
    }
  ],
  "expected_output": {
    "type": "dict",
    "schema": {"mean": "float", "std": "float"},
    "description": "Dictionary containing mean and standard deviation of HR"
  },
  "estimated_complexity": "simple",
  "confidence": 0.95,
  "warnings": []
}"""

EXAMPLE_CORRELATION = """{
  "analysis_type": "correlation",
  "reasoning": "Query for analyzing correlation between two variables.",
  "steps": [
    {
      "id": "step_1",
      "order": 0,
      "action": "compute_correlation",
      "description": "Calculate Pearson correlation coefficient between HR and SpO2",
      "execution_mode": "code",
      "inputs": ["df"],
      "input_columns": ["HR", "SpO2"],
      "parameters": {"method": "pearson"},
      "output_key": "correlation_result",
      "expected_output_type": "dict",
      "code_hint": "from scipy import stats; r = stats.pearsonr(df['HR'].dropna(), df['SpO2'].dropna()); result = {'correlation': r.statistic, 'pvalue': r.pvalue}",
      "depends_on": []
    }
  ],
  "expected_output": {
    "type": "dict",
    "schema": {"correlation": "float", "pvalue": "float"},
    "description": "Dictionary containing correlation coefficient and p-value"
  },
  "estimated_complexity": "simple",
  "confidence": 0.9,
  "warnings": ["NaN values will be automatically removed"]
}"""

EXAMPLE_MULTI_STEP = """{
  "analysis_type": "aggregation",
  "reasoning": "Multi-step query involving data filtering followed by aggregation.",
  "steps": [
    {
      "id": "step_1",
      "order": 0,
      "action": "filter_data",
      "description": "Filter data where HR is 100 or above",
      "execution_mode": "code",
      "inputs": ["df"],
      "input_columns": ["HR"],
      "parameters": {"threshold": 100},
      "output_key": "filtered_df",
      "expected_output_type": "dataframe",
      "code_hint": "filtered_df = df[df['HR'] >= 100]",
      "depends_on": []
    },
    {
      "id": "step_2",
      "order": 1,
      "action": "compute_statistics",
      "description": "Compute statistics on filtered data",
      "execution_mode": "code",
      "inputs": ["filtered_df"],
      "input_columns": ["HR", "SpO2"],
      "parameters": {},
      "output_key": "final_result",
      "expected_output_type": "dict",
      "code_hint": "result = {'count': len(filtered_df), 'hr_mean': filtered_df['HR'].mean(), 'spo2_mean': filtered_df['SpO2'].mean()}",
      "depends_on": ["step_1"]
    }
  ],
  "expected_output": {
    "type": "dict",
    "schema": {"count": "int", "hr_mean": "float", "spo2_mean": "float"},
    "description": "Count and mean values of filtered data"
  },
  "estimated_complexity": "moderate",
  "confidence": 0.85,
  "warnings": []
}"""

EXAMPLE_COMPLEX_DEPENDENCIES = """{
  "analysis_type": "comparison",
  "reasoning": "Complex query comparing two groups with independent filtering then combined analysis.",
  "steps": [
    {
      "id": "step_1",
      "order": 0,
      "action": "filter_high_hr",
      "description": "Filter patients with high HR (>= 100)",
      "execution_mode": "code",
      "inputs": ["df"],
      "input_columns": ["HR"],
      "parameters": {"threshold": 100},
      "output_key": "high_hr_df",
      "expected_output_type": "dataframe",
      "code_hint": "high_hr_df = df[df['HR'] >= 100]",
      "depends_on": []
    },
    {
      "id": "step_2",
      "order": 1,
      "action": "filter_low_hr",
      "description": "Filter patients with low HR (< 100)",
      "execution_mode": "code",
      "inputs": ["df"],
      "input_columns": ["HR"],
      "parameters": {"threshold": 100},
      "output_key": "low_hr_df",
      "expected_output_type": "dataframe",
      "code_hint": "low_hr_df = df[df['HR'] < 100]",
      "depends_on": []
    },
    {
      "id": "step_3",
      "order": 2,
      "action": "compute_high_hr_stats",
      "description": "Compute SpO2 statistics for high HR group",
      "execution_mode": "code",
      "inputs": ["high_hr_df"],
      "input_columns": ["SpO2"],
      "parameters": {},
      "output_key": "high_hr_stats",
      "expected_output_type": "dict",
      "code_hint": "high_hr_stats = {'mean': high_hr_df['SpO2'].mean(), 'std': high_hr_df['SpO2'].std(), 'count': len(high_hr_df)}",
      "depends_on": ["step_1"]
    },
    {
      "id": "step_4",
      "order": 3,
      "action": "compute_low_hr_stats",
      "description": "Compute SpO2 statistics for low HR group",
      "execution_mode": "code",
      "inputs": ["low_hr_df"],
      "input_columns": ["SpO2"],
      "parameters": {},
      "output_key": "low_hr_stats",
      "expected_output_type": "dict",
      "code_hint": "low_hr_stats = {'mean': low_hr_df['SpO2'].mean(), 'std': low_hr_df['SpO2'].std(), 'count': len(low_hr_df)}",
      "depends_on": ["step_2"]
    },
    {
      "id": "step_5",
      "order": 4,
      "action": "compare_groups",
      "description": "Compare statistics between two groups and perform t-test",
      "execution_mode": "code",
      "inputs": ["high_hr_df", "low_hr_df", "high_hr_stats", "low_hr_stats"],
      "input_columns": ["SpO2"],
      "parameters": {},
      "output_key": "comparison_result",
      "expected_output_type": "dict",
      "code_hint": "from scipy import stats; t_result = stats.ttest_ind(high_hr_df['SpO2'].dropna(), low_hr_df['SpO2'].dropna()); result = {'high_hr_group': high_hr_stats, 'low_hr_group': low_hr_stats, 't_statistic': t_result.statistic, 'p_value': t_result.pvalue}",
      "depends_on": ["step_3", "step_4"]
    }
  ],
  "expected_output": {
    "type": "dict",
    "schema": {"high_hr_group": "dict", "low_hr_group": "dict", "t_statistic": "float", "p_value": "float"},
    "description": "Comparison of SpO2 statistics between high HR and low HR groups with t-test result"
  },
  "estimated_complexity": "complex",
  "confidence": 0.85,
  "warnings": ["Steps 1-2 and 3-4 can run in parallel as they have no mutual dependencies"]
}"""


def get_few_shot_examples() -> str:
    """Return few-shot examples"""
    examples = [
        ("Query: Calculate mean and std of HR", EXAMPLE_SIMPLE_STATS),
        ("Query: Analyze correlation between HR and SpO2", EXAMPLE_CORRELATION),
        ("Query: Get statistics for HR >= 100", EXAMPLE_MULTI_STEP),
        ("Query: Compare SpO2 between high HR and low HR groups", EXAMPLE_COMPLEX_DEPENDENCIES),
    ]
    
    result = []
    for query, response in examples:
        result.append(f"### Example\n{query}\n\nResponse:\n```json\n{response}\n```")
    
    return "\n\n".join(result)
