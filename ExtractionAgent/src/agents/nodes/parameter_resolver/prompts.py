# src/agents/nodes/parameter_resolver/prompts.py
"""
ParameterResolverNode Prompt Templates

LLM prompts for resolving ambiguous parameter mappings
when multiple database candidates match a user's requested term.
"""

RESOLUTION_SYSTEM_PROMPT = """You are an expert Medical Data Parameter Resolver.
Your task is to map the user's natural language request to the most appropriate database parameters from the provided candidates.

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

1. Analyze the user's FULL query to understand the exact clinical intent.
2. Evaluate the provided Database Candidates to find the best semantic match for the user's request. Be flexible with synonyms and clinical terminology.
3. Determine the resolution mode:
   - "retrieve": Found a valid semantic match. The candidate represents the same clinical concept the user asked for. (Select the specific param_keys).
   - "clarify": Candidates match the general concept, but it's too ambiguous to choose without user input.
   - "not_found": NONE of the DB candidates actually represent what the user asked for. Use this when the match is superficial (keyword overlap only) but semantically wrong. Criteria:
     • User asked for signal X, but DB only has signal Y from a different body location (e.g., "intracranial pressure" ≠ "arterial blood pressure")
     • User asked for a physiological process that has no corresponding measurement in the DB (e.g., "gut motility", "sweat gland activity")
     • The closest DB match would be clinically misleading to substitute for the requested signal
     In "not_found" mode, set selected_param_keys to [].

4. Domain Specific Rules:
   - Cross-Device Resolution (Hierarchy of Sources): If the exact same physiological parameter exists across multiple devices and the user didn't specify one, DO NOT ask for clarification and DO NOT return all of them. Instead, select ONLY ONE parameter based on the following clinical hierarchy:
     1) For general vital signs (Heart Rate, Blood Pressure, SpO2), strongly prefer the Patient Monitor (e.g., 'Solar8000').
     2) For respiratory/ventilation and anesthetic gases (ETCO2, FIO2, Tidal Volume, Airway Pressures), strongly prefer the Anesthesia Machine/Ventilator (e.g., 'Primus').
     3) For depth of anesthesia, prefer 'BIS'. For infusion pumps, prefer 'Orchestra'.
     Select only the single best candidate that aligns with this hierarchy.
     **CRITICAL EXCEPTION**: ALWAYS prefer measured/observed values over "Set" or target values, regardless of the device hierarchy, unless the user explicitly asks for the setting. For example, prefer `Solar8000/VENT_INSP_TM` (measured) over `Primus/SET_INSP_TM` (setting).
   - Propofol/Remifentanil Concentration: Pay strict attention to "CE" (Effect-site concentration) vs "CT" (Target concentration). If the user asks for "concentration" in the context of patient effect/depth, prefer "CE".
   - Default/Primary Parameters: If multiple related parameters exist (e.g., HR vs PLETH_HR, or multiple ECG leads), prefer the primary/standard one (e.g., HR, ECG_II) instead of asking for clarification. If multiple leads/channels exist for the exact same signal type (e.g., ECG_II and ECG_V5) and no specific one is requested, you may select all of them rather than clarifying.

# Response Format

Respond ONLY with the following JSON format:

```json
{{
    "resolution_mode": "retrieve | clarify | not_found",
    "selected_param_keys": ["param_key1", "param_key2"],
    "confidence": 0.95,
    "reasoning": "Detailed explanation of why these parameters were selected or why it was deemed clarify/not_found."
}}
```

# Important Notes

1. Real-time signals typically use "Device/Parameter" format (e.g., device parameters shown above)
2. Lab values and clinical data use single-key format (e.g., clinical_lab parameters shown above)
3. Never return an empty selected_param_keys unless resolution_mode is "clarify" or "not_found"
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

VALIDATOR_SYSTEM_PROMPT = """You are a strict Medical Data Semantic Validator.
Your ONLY job is to verify if the parameter selected by the system actually matches what the user asked for.

# Instructions
1. Read the User's Original Query.
2. Look at the "Parameter Being Resolved" (what the user asked for).
3. Look at the "Selected Parameters" (what the system mapped it to).
4. Decide if this mapping is semantically valid and clinically appropriate.

# Validation Rules
- If the user asks for a parameter that does NOT exist in the Selected Parameters (e.g., user asks for "synovial fluid pressure" but system selected "arterial blood pressure"), you MUST mark it as INVALID.
- If the user asks for a specific derived metric (e.g., "brain wave conduction") and the system selected raw waveforms that don't represent that metric, mark it as INVALID.
- If the mapping is a reasonable synonym or standard clinical equivalent (e.g., "heart rate" -> "HR"), mark it as VALID.
- **Unit Leniency**: Database schemas often have quirky or mislabeled units (e.g., flow rate in mbar). Do NOT reject a mapping solely because the unit seems unusual if the semantic name matches the request.
- **Set vs Measured Leniency**: If the user asks for a parameter (e.g., "inspiratory time", "respiratory rate") and the system selects a "Set" value (e.g., "Set Inspiratory Time") because it's the best available match, mark it as VALID.

# Response Format
Respond ONLY with the following JSON format:
```json
{{
    "is_valid": true | false,
    "error_type": "none | completely_irrelevant | missing_condition | wrong_parameter_type",
    "reasoning": "Brief explanation of why this mapping is valid or invalid."
}}
```
"""

VALIDATOR_USER_PROMPT_TEMPLATE = """# User's Original Query
"{original_query}"

# Parameter Being Resolved (User's Request)
- Original term: "{term}"

# Selected Parameters (System's Mapping)
{selected_details}

Is this mapping semantically valid?"""

def build_validator_prompt(
    term: str,
    original_query: str,
    selected_matches: list
) -> tuple[str, str]:
    """
    Build system and user prompts for the validation pass.
    """
    if not selected_matches:
        selected_details = "None (System could not find any matches)"
    else:
        details_lines = []
        for match in selected_matches:
            details_lines.append(
                f"- {match.get('param_key', 'N/A')}: {match.get('semantic_name', 'N/A')} "
                f"({match.get('unit', 'N/A')}) [{match.get('concept_category', 'N/A')}]"
            )
        selected_details = "\n".join(details_lines)
        
    user_prompt = VALIDATOR_USER_PROMPT_TEMPLATE.format(
        original_query=original_query or "(not provided)",
        term=term,
        selected_details=selected_details
    )
    
    return VALIDATOR_SYSTEM_PROMPT, user_prompt
