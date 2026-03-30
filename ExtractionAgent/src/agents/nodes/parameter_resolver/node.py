# src/agents/nodes/parameter_resolver/node.py
"""
ParameterResolverNode - [200] Parameter Mapping

Responsibilities:
1. Map requested_parameters to actual param_keys
2. Search PostgreSQL parameter table
3. Determine Resolution Mode (ALL_SOURCES / SPECIFIC / CLARIFY)
"""

from typing import Dict, Any, List
from shared.langgraph import BaseNode, register_node
from shared.config.llm import LLMConfig
from ExtractionAgent.src.agents.state import ExtractionState
from ExtractionAgent.src.config import ExtractionConfig
from ExtractionAgent.src.agents.nodes.parameter_resolver.prompts import build_resolution_prompt, build_validator_prompt
from shared.database.connection import get_db_manager
from shared.llm.client import get_llm_client


@register_node
class ParameterResolverNode(BaseNode):
    """
    [200] Parameter Resolution Node
    
    Maps requested parameters to actual DB param_keys.
    
    Input:
        - schema_context: Dict (from QueryUnderstanding)
        - requested_parameters: List[Dict] (term, normalized, candidates)
    
    Output:
        - resolved_parameters: List[Dict] (term, param_keys, semantic_name, unit, ...)
        - ambiguities: List[Dict] (questions for ambiguous cases)
        - has_ambiguity: bool
    """
    
    name = "parameter_resolver"
    description = "Parameter mapping and resolution"
    order = 200
    requires_llm = True
    requires_db = True
    
    def __init__(self):
        super().__init__()
        self.config = ExtractionConfig().parameter_resolver
        self.db = get_db_manager()
        self.llm_client = get_llm_client()
    
    def execute(self, state: ExtractionState) -> Dict[str, Any]:
        """
        Execute parameter resolution
        
        1. Iterate through requested_parameters
        2. Search PostgreSQL parameter table
        3. Determine Resolution Mode based on candidates
        """
        requested_parameters = state.get("requested_parameters", [])
        schema_context = state.get("schema_context", {})
        
        # Extract additional context for LLM
        original_query = state.get("user_query", "")
        signal_groups = schema_context.get("signal_groups", [])
        temporal_context = state.get("temporal_context", {})
        parameter_examples = schema_context.get("parameter_examples", [])
        
        self.log(f"📋 Requested parameters: {len(requested_parameters)}")
        
        resolved_parameters: List[Dict[str, Any]] = []
        ambiguities: List[Dict[str, Any]] = []
        
        for param in requested_parameters:
            term = param.get("term", "")
            normalized = param.get("normalized", term)
            candidates = param.get("candidates", [])
            expected_categories = param.get("expected_categories", [])  # Option B
            
            self.log(f"🔍 Resolving: {term}", indent=1)
            if expected_categories:
                self.log(f"   Expected categories: {expected_categories}", indent=2)
            
            # 1. Search database for matching parameters (with category filter - Option B)
            db_matches = self._search_parameters(candidates, expected_categories, schema_context)
            self.log(f"   Found {len(db_matches)} DB matches", indent=2)
            
            # 2. Pass 1: Resolve with LLM (Flexible Mapper)
            if len(db_matches) == 0:
                # If no matches found, decide between not_found and clarify
                is_vague = any(cat in ["Unknown", "Other"] for cat in expected_categories)
                mode = "clarify" if is_vague else "not_found"
                reason = f"No matches found for keywords: {candidates}. Marked as {mode} due to category {expected_categories}."
                
                resolved = {
                    "term": term,
                    "param_keys": [],
                    "semantic_name": normalized,
                    "unit": None,
                    "concept_category": None,
                    "resolution_mode": mode,
                    "confidence": 0.0,
                    "reasoning": reason
                }
            else:
                resolved = self._resolve_with_llm(
                    term=term,
                    normalized=normalized,
                    candidates=candidates,
                    db_matches=db_matches,
                    original_query=original_query,
                    signal_groups=signal_groups,
                    temporal_context=temporal_context,
                    parameter_examples=parameter_examples
                )
            
            # 3. Pass 2: Validate with LLM (Strict Validator) — conditional
            should_validate = (
                self.config.enable_validator_pass
                and resolved.get("resolution_mode") in ("retrieve", "clarify")
                and resolved.get("param_keys")
                and resolved.get("confidence", 1.0) < self.config.validator_confidence_threshold
            )
            if should_validate:
                selected_keys = resolved["param_keys"]
                selected_matches = [m for m in db_matches if m.get("param_key") in selected_keys]
                
                is_valid, validation_reasoning = self._validate_mapping_with_llm(
                    term=term,
                    original_query=original_query,
                    selected_matches=selected_matches
                )
                
                if not is_valid:
                    self.log(f"   ❌ Validator rejected mapping: {validation_reasoning}", indent=2)
                    resolved["resolution_mode"] = "not_found"
                    resolved["param_keys"] = []
                    resolved["confidence"] = 0.0
                    resolved["reasoning"] = f"Validation failed: {validation_reasoning}"
                else:
                    self.log(f"   ✅ Validator approved mapping", indent=2)
            
            resolution_mode = resolved.get("resolution_mode")
            
            if resolution_mode == "clarify":
                ambiguities.append({
                    "term": term,
                    "candidates": [m.get("param_key") for m in db_matches],
                    "question": resolved.get("reasoning", f"Could not clearly identify '{term}'. Please clarify.")
                })
            elif resolution_mode == "not_found":
                self.log(f"   ❌ Parameter not found or rejected: {resolved.get('reasoning')}", indent=2)
                # It will be passed to PlanBuilder with confidence=0.0 and empty param_keys
            
            # Store db_matches for debugging
            resolved["db_matches"] = db_matches
            resolved["search_candidates"] = candidates
            
            resolved_parameters.append(resolved)
            self.log(f"   → {len(resolved.get('param_keys', []))} param_keys mapped (mode: {resolution_mode})", indent=2)
        
        has_ambiguity = len(ambiguities) > 0
        
        if has_ambiguity:
            self.log(f"⚠️ Ambiguous parameters: {len(ambiguities)}")
        else:
            self.log("✅ All parameters resolved successfully")
        
        return {
            "parameter_resolver_result": {
                "status": "success",
                "node": self.name,
                "resolved_count": len(resolved_parameters),
                "ambiguity_count": len(ambiguities)
            },
            "resolved_parameters": resolved_parameters,
            "ambiguities": ambiguities,
            "has_ambiguity": has_ambiguity,
            "logs": self._logs
        }
    
    def _search_parameters(
        self, 
        candidates: List[str],
        expected_categories: List[str],  # Option B: 카테고리 필터
        schema_context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Search PostgreSQL parameter table for matching parameters.
        
        Option B: 2-step search
        1. Keyword search (ILIKE on param_key, semantic_name)
        2. Filter by expected_categories if provided
        
        Args:
            candidates: Search keywords
            expected_categories: Expected concept_category values (Option B)
            schema_context: Schema context (contains group info)
        
        Returns:
            List of matching parameters
        """
        if not candidates:
            return []
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Step 1: Build ILIKE conditions for each candidate
            keyword_conditions = []
            params = []
            
            for kw in candidates:
                kw_pattern = f"%{kw}%"
                keyword_conditions.append("(param_key ILIKE %s OR semantic_name ILIKE %s)")
                params.extend([kw_pattern, kw_pattern])
            
            keyword_clause = " OR ".join(keyword_conditions)
            
            # Step 2: Add category filter if expected_categories provided (Option B)
            if expected_categories:
                category_placeholders = ", ".join(["%s"] * len(expected_categories))
                category_clause = f"AND concept_category IN ({category_placeholders})"
                params.extend(expected_categories)
            else:
                category_clause = ""
            
            query = f"""
                SELECT DISTINCT ON (param_key)
                       param_id, param_key, semantic_name, unit, 
                       concept_category, file_id, group_id
                FROM parameter
                WHERE ({keyword_clause}) {category_clause}
                ORDER BY param_key, param_id
                LIMIT %s
            """
            params.append(self.config.search_limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            conn.commit()
            
            results = []
            for row in rows:
                param_id, param_key, sem_name, unit, category, file_id, group_id = row
                results.append({
                    "param_id": param_id,
                    "param_key": param_key,
                    "semantic_name": sem_name,
                    "unit": unit,
                    "concept_category": category,
                    "file_id": str(file_id) if file_id else None,
                    "group_id": str(group_id) if group_id else None
                })
            
            # Option B Fallback: 카테고리 필터로 결과가 없으면 전체 검색
            if not results and expected_categories:
                self.log(f"⚠️ No matches in categories {expected_categories}, searching all", indent=2)
                return self._search_parameters_without_category(candidates)
            
            return results
            
        except Exception as e:
            conn.rollback()
            self.log(f"❌ DB search error: {e}", indent=2)
            return []
    
    def _search_parameters_without_category(
        self,
        candidates: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Fallback: Search without category filter.
        Used when category-filtered search returns no results.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            conditions = []
            params = []
            
            for kw in candidates:
                kw_pattern = f"%{kw}%"
                conditions.append("(param_key ILIKE %s OR semantic_name ILIKE %s)")
                params.extend([kw_pattern, kw_pattern])
            
            where_clause = " OR ".join(conditions)
            
            query = f"""
                SELECT DISTINCT ON (param_key)
                       param_id, param_key, semantic_name, unit, 
                       concept_category, file_id, group_id
                FROM parameter
                WHERE {where_clause}
                ORDER BY param_key, param_id
                LIMIT %s
            """
            params.append(self.config.search_limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.commit()
            
            results = []
            for row in rows:
                param_id, param_key, sem_name, unit, category, file_id, group_id = row
                results.append({
                    "param_id": param_id,
                    "param_key": param_key,
                    "semantic_name": sem_name,
                    "unit": unit,
                    "concept_category": category,
                    "file_id": str(file_id) if file_id else None,
                    "group_id": str(group_id) if group_id else None
                })
            
            return results
            
        except Exception as e:
            conn.rollback()
            self.log(f"❌ DB fallback search error: {e}", indent=2)
            return []
    
    def _resolve_with_llm(
        self,
        term: str,
        normalized: str,
        candidates: List[str],
        db_matches: List[Dict[str, Any]],
        original_query: str = "",
        signal_groups: List[Dict[str, Any]] = None,
        temporal_context: Dict[str, Any] = None,
        parameter_examples: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Pass 1: Use LLM as a flexible Resolver to map candidates.
        
        The LLM decides whether to:
        - Retrieve specific parameters (retrieve)
        - Ask for clarification (clarify)
        
        Args:
            term: User's original term
            normalized: Normalized parameter name
            candidates: Search keywords
            db_matches: Database search results
            original_query: Full user query for context
            signal_groups: Available signal groups (devices)
            temporal_context: Time window settings
            parameter_examples: Sample parameters from DB (for context)
        """
        system_prompt, user_prompt = build_resolution_prompt(
            term=term,
            normalized=normalized,
            candidates=candidates,
            db_matches=db_matches,
            original_query=original_query,
            signal_groups=signal_groups or [],
            temporal_context=temporal_context or {},
            parameter_examples=parameter_examples or []
        )
        
        try:
            self.log("🤖 Calling LLM Resolver (Pass 1)...", indent=2)
            
            response = self.llm_client.ask_json(
                system_prompt + "\n\n" + user_prompt,
                max_tokens=LLMConfig.MAX_TOKENS
            )
            
            resolution_mode = response.get("resolution_mode", "clarify")
            selected_keys = response.get("selected_param_keys", [])
            confidence = response.get("confidence", 0.5)
            reasoning = response.get("reasoning", "")

            if resolution_mode == "not_found":
                self.log(f"   ✗ Resolver: parameter does not exist in DB — {reasoning[:80]}", indent=2)
                return {
                    "term": term,
                    "param_keys": [],
                    "semantic_name": normalized,
                    "unit": None,
                    "concept_category": None,
                    "resolution_mode": "not_found",
                    "confidence": 0.0,
                    "reasoning": reasoning,
                }

            if resolution_mode == "clarify":
                return {
                    "term": term,
                    "param_keys": selected_keys, # Might be empty or contain candidates for clarification
                    "semantic_name": normalized,
                    "unit": None,
                    "concept_category": None,
                    "resolution_mode": resolution_mode,
                    "confidence": confidence,
                    "reasoning": reasoning
                }
            
            # resolution_mode == "retrieve"
            if selected_keys:
                selected_matches = [
                    m for m in db_matches 
                    if m.get("param_key") in selected_keys
                ]
                self.log(f"   🎯 Resolver selected {len(selected_keys)} keys → {len(selected_matches)} matched", indent=2)
                
                # If LLM selected keys but none match DB results, it's a hallucination
                if not selected_matches:
                    self.log(f"   ⚠️ Resolver selection didn't match DB, falling back to clarify", indent=2)
                    return {
                        "term": term,
                        "param_keys": [],
                        "semantic_name": normalized,
                        "unit": None,
                        "concept_category": None,
                        "resolution_mode": "clarify",
                        "confidence": 0.0,
                        "reasoning": "Resolver selected parameters that don't exist in the search results."
                    }
            else:
                # No selection from LLM but retrieve mode - fallback to clarify
                return {
                    "term": term,
                    "param_keys": [],
                    "semantic_name": normalized,
                    "unit": None,
                    "concept_category": None,
                    "resolution_mode": "clarify",
                    "confidence": 0.0,
                    "reasoning": "Resolver chose retrieve but didn't select any parameters."
                }
            
            # Get semantic info from selected matches
            unique_semantic_names = list(set(
                m.get("semantic_name") for m in selected_matches if m.get("semantic_name")
            ))
            unique_units = list(set(
                m.get("unit") for m in selected_matches if m.get("unit")
            ))
            unique_categories = list(set(
                m.get("concept_category") for m in selected_matches if m.get("concept_category")
            ))
            
            # Determine display values
            if len(unique_semantic_names) == 1:
                semantic_name = unique_semantic_names[0]
            elif len(unique_semantic_names) > 1:
                semantic_name = f"{normalized} ({len(selected_matches)} types)"
            else:
                semantic_name = normalized
            
            unit = unique_units[0] if len(unique_units) == 1 else (
                f"mixed ({len(unique_units)})" if unique_units else None
            )
            category = unique_categories[0] if len(unique_categories) == 1 else (
                unique_categories[0] if unique_categories else None
            )
            
            return {
                "term": term,
                "param_keys": [m.get("param_key") for m in selected_matches],
                "semantic_name": semantic_name,
                "unit": unit,
                "concept_category": category,
                "resolution_mode": resolution_mode,
                "confidence": confidence,
                "reasoning": reasoning
            }
                
        except Exception as e:
            self.log(f"❌ LLM resolution error: {e}", indent=2)
            # Fallback to clarify
            return {
                "term": term,
                "param_keys": [],
                "semantic_name": normalized,
                "unit": None,
                "concept_category": None,
                "resolution_mode": "clarify",
                "confidence": 0.0,
                "reasoning": f"Error during resolution: {str(e)}"
            }

    def _validate_mapping_with_llm(
        self,
        term: str,
        original_query: str,
        selected_matches: List[Dict[str, Any]]
    ) -> tuple[bool, str]:
        """
        Pass 2: Use LLM as a strict Validator to check the Resolver's mapping.
        
        Args:
            term: User's original term
            original_query: Full user query
            selected_matches: The parameters selected by the Resolver
            
        Returns:
            Tuple of (is_valid: bool, reasoning: str)
        """
        system_prompt, user_prompt = build_validator_prompt(
            term=term,
            original_query=original_query,
            selected_matches=selected_matches
        )
        
        try:
            self.log("🛡️ Calling LLM Validator (Pass 2)...", indent=2)
            
            # We could use a faster/cheaper model here if configured, 
            # but for now we use the standard client
            response = self.llm_client.ask_json(
                system_prompt + "\n\n" + user_prompt,
                max_tokens=LLMConfig.MAX_TOKENS
            )
            
            is_valid = response.get("is_valid", False)
            reasoning = response.get("reasoning", "No reasoning provided by validator.")
            
            return is_valid, reasoning
            
        except Exception as e:
            self.log(f"❌ LLM validation error: {e}", indent=2)
            # If validation fails technically, we default to rejecting to be safe
            return False, f"Validator technical error: {str(e)}"
