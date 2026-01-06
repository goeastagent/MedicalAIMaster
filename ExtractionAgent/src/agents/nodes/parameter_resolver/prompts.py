# src/agents/nodes/parameter_resolver/prompts.py
"""
ParameterResolverNode Prompt Templates

LLM prompts for resolving ambiguous parameter mappings
when multiple database candidates match a user's requested term.
"""

RESOLUTION_SYSTEM_PROMPT = """You are an expert in medical data parameter resolution.
Your task is to select the most appropriate database parameters that match the user's requested measurement.

# Context

You are helping to build a data extraction plan for medical research.
The user has submitted a natural language query requesting specific medical parameters.
Multiple database parameters have been found as potential matches.
You must decide which parameters to include in the data extraction.

# Available Data Sources

{signal_groups_context}

# Parameter Examples from Database

{parameter_examples_context}

# Instructions

1. Analyze the user's FULL query to understand the context
2. Consider which data source is most appropriate for the request
3. Evaluate each candidate's semantic meaning, unit, and source
4. Decide the resolution mode:
   - "all_sources": Include ALL matching parameters (when they measure the same physiological signal from different sources)
   - "specific": Include only the MOST relevant parameters (when context clearly indicates a preference)
   - "clarify": Ask user for clarification (when candidates are semantically different and context is insufficient)

5. Provide your reasoning for the decision

# Response Format

Respond ONLY with the following JSON format:

```json
{{
    "resolution_mode": "all_sources | specific | clarify",
    "selected_param_keys": ["param_key1", "param_key2"],
    "confidence": 0.95,
    "reasoning": "Brief explanation of why these parameters were selected"
}}
```

# Important Notes

1. Real-time signals typically use "Device/Parameter" format (e.g., device parameters shown above)
2. Lab values and clinical data use single-key format (e.g., clinical_lab parameters shown above)
3. If candidates measure the same physiological signal from different devices, use "all_sources"
4. If candidates are semantically different (e.g., systolic BP vs diastolic BP), use "clarify"
5. Never return an empty selected_param_keys unless resolution_mode is "clarify"
"""


RESOLUTION_USER_PROMPT_TEMPLATE = """# User's Original Query
"{original_query}"

# Parameter Being Resolved
- Original term: "{term}"
- Normalized name: "{normalized}"
- Search keywords: {candidates}

# Temporal Context
- Time window: {temporal_type}
- Margin: {temporal_margin} seconds

# Database Candidates Found ({candidate_count} matches)

{candidate_details}

Based on the user's query context and temporal requirements, select the appropriate parameters."""


def _format_parameter_examples(parameter_examples: list) -> str:
    """
    Format parameter examples by source for the prompt.
    
    Args:
        parameter_examples: List from SchemaContextBuilder.get_parameter_examples()
    
    Returns:
        Formatted string showing examples by source
    """
    if not parameter_examples:
        return "No parameter examples available."
    
    # Group by source
    by_source = {}
    for ex in parameter_examples:
        source = ex.get("source", "unknown")
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(ex)
    
    lines = []
    for source, examples in sorted(by_source.items()):
        source_type = examples[0].get("source_type", "unknown")
        lines.append(f"[{source}] ({source_type})")
        
        for ex in examples:
            unit_str = f" ({ex.get('unit')})" if ex.get('unit') else ""
            cat_str = f" - {ex.get('category')}" if ex.get('category') else ""
            lines.append(f"  - {ex.get('param_key')}: {ex.get('semantic_name')}{unit_str}{cat_str}")
        
        lines.append("")  # Empty line between sources
    
    return "\n".join(lines)


def build_resolution_prompt(
    term: str,
    normalized: str,
    candidates: list,
    db_matches: list,
    original_query: str = "",
    signal_groups: list = None,
    temporal_context: dict = None,
    parameter_examples: list = None
) -> tuple[str, str]:
    """
    Build system and user prompts for parameter resolution.
    
    Args:
        term: User's original term
        normalized: Normalized parameter name
        candidates: Search keywords used
        db_matches: List of matching parameters from database
            Each: {"param_key": str, "semantic_name": str, "unit": str, 
                   "concept_category": str, "group_id": str}
        original_query: User's full original query for context
        signal_groups: List of available signal groups (devices/sources)
        temporal_context: Temporal settings from QueryUnderstanding
        parameter_examples: List of parameter examples from SchemaContextBuilder
    
    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    # Format signal groups context
    if signal_groups:
        groups_lines = []
        for grp in signal_groups:
            groups_lines.append(
                f"- {grp.get('group_name', 'Unknown')}: "
                f"{grp.get('description', grp.get('file_pattern', 'No description'))}"
            )
        signal_groups_context = "\n".join(groups_lines)
    else:
        signal_groups_context = "Signal group information not available."
    
    # Format parameter examples from DB
    parameter_examples_context = _format_parameter_examples(parameter_examples or [])
    
    # Format candidate details with source info
    if db_matches:
        details_lines = []
        for i, match in enumerate(db_matches, 1):
            param_key = match.get('param_key', 'N/A')
            
            # Extract source: device name if "/" present, otherwise category-based
            if '/' in param_key:
                source = param_key.split('/')[0]
                source_type = "device"
            else:
                # For single-key params, use category or mark as clinical
                category = match.get('concept_category', '')
                if category:
                    source = category
                    source_type = "category"
                else:
                    source = "clinical_lab"
                    source_type = "clinical"
            
            details_lines.append(
                f"{i}. param_key: {param_key}\n"
                f"   source: {source} ({source_type})\n"
                f"   semantic_name: {match.get('semantic_name', 'N/A')}\n"
                f"   unit: {match.get('unit', 'N/A')}\n"
                f"   category: {match.get('concept_category', 'N/A')}"
            )
        candidate_details = "\n\n".join(details_lines)
    else:
        candidate_details = "No matching parameters found in database."
    
    # Format temporal context with sensible default
    temporal_type = "full_record"
    temporal_margin = 0
    if temporal_context:
        temporal_type = temporal_context.get('type', 'full_record')
        temporal_margin = temporal_context.get('margin_seconds', 0)
    
    # Build system prompt with dynamic context
    system_prompt = RESOLUTION_SYSTEM_PROMPT.format(
        signal_groups_context=signal_groups_context,
        parameter_examples_context=parameter_examples_context
    )
    
    # Build user prompt with full context
    user_prompt = RESOLUTION_USER_PROMPT_TEMPLATE.format(
        original_query=original_query or "(not provided)",
        term=term,
        normalized=normalized,
        candidates=candidates,
        temporal_type=temporal_type,
        temporal_margin=temporal_margin,
        candidate_count=len(db_matches),
        candidate_details=candidate_details
    )
    
    return system_prompt, user_prompt
