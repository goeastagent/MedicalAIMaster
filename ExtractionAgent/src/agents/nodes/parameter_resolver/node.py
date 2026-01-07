# src/agents/nodes/parameter_resolver/node.py
"""
ParameterResolverNode - [200] Parameter Mapping

Responsibilities:
1. Map requested_parameters to actual param_keys
2. Search PostgreSQL parameter table
3. Determine Resolution Mode (ALL_SOURCES / SPECIFIC / CLARIFY)
"""

from typing import Dict, Any, List
from src.agents.base import BaseNode
from src.agents.registry import register_node
from src.agents.state import VitalExtractionState
from src.config import VitalExtractionConfig, LLMConfig
from src.agents.nodes.parameter_resolver.prompts import build_resolution_prompt
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
        self.config = VitalExtractionConfig().parameter_resolver
        self.db = get_db_manager()
        self.llm_client = get_llm_client()
    
    def execute(self, state: VitalExtractionState) -> Dict[str, Any]:
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
            
            # 2. Determine resolution based on match count
            if len(db_matches) == 0:
                # No matches - create clarify request
                resolved = self._create_no_match_result(term, normalized, candidates)
                ambiguities.append({
                    "term": term,
                    "candidates": candidates,
                    "question": f"Could not find parameter matching '{term}'. Please provide more details."
                })
                
            elif len(db_matches) <= 3:
                # Few matches - use all sources directly
                resolved = self._create_all_sources_result(term, normalized, db_matches)
                
            else:
                # Many matches - use LLM to decide with full context
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
                if resolved.get("resolution_mode") == "clarify":
                    ambiguities.append({
                        "term": term,
                        "candidates": [m.get("param_key") for m in db_matches],
                        "question": f"Multiple different types of '{term}' found. Which one do you need?"
                    })
            
            # Store db_matches for debugging
            resolved["db_matches"] = db_matches
            resolved["search_candidates"] = candidates
            
            resolved_parameters.append(resolved)
            self.log(f"   → {len(resolved.get('param_keys', []))} param_keys mapped", indent=2)
        
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
    
    def _create_no_match_result(
        self, 
        term: str, 
        normalized: str, 
        candidates: List[str]
    ) -> Dict[str, Any]:
        """Create result for no database matches."""
        return {
            "term": term,
            "param_keys": [],
            "semantic_name": normalized,
            "unit": None,
            "concept_category": None,
            "resolution_mode": "clarify",
            "confidence": 0.0,
            "reasoning": f"No matches found for keywords: {candidates}"
        }
    
    def _create_all_sources_result(
        self, 
        term: str, 
        normalized: str, 
        db_matches: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create result using all matched sources."""
        # Collect unique values
        unique_semantic_names = list(set(
            m.get("semantic_name") for m in db_matches if m.get("semantic_name")
        ))
        unique_units = list(set(
            m.get("unit") for m in db_matches if m.get("unit")
        ))
        unique_categories = list(set(
            m.get("concept_category") for m in db_matches if m.get("concept_category")
        ))
        
        # Determine display values
        if len(unique_semantic_names) == 1:
            semantic_name = unique_semantic_names[0]
        elif len(unique_semantic_names) > 1:
            semantic_name = f"{normalized} ({len(db_matches)} types)"
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
            "param_keys": [m.get("param_key") for m in db_matches],
            "semantic_name": semantic_name,
            "unit": unit,
            "concept_category": category,
            "resolution_mode": "all_sources",
            "confidence": 0.9,
            "reasoning": f"Using all {len(db_matches)} matched sources"
        }
    
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
        Use LLM to resolve when many candidates exist.
        
        The LLM decides whether to:
        - Use all sources (all_sources)
        - Pick specific ones (specific)
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
            self.log("🤖 Calling LLM for resolution...", indent=2)
            
            response = self.llm_client.ask_json(
                system_prompt + "\n\n" + user_prompt,
                max_tokens=LLMConfig.MAX_TOKENS
            )
            
            resolution_mode = response.get("resolution_mode", "all_sources")
            selected_keys = response.get("selected_param_keys", [])
            confidence = response.get("confidence", 0.5)
            reasoning = response.get("reasoning", "")
            
            # Option C (fix-2): ALWAYS trust LLM's selected_param_keys if provided
            # This is the key fix - previously only "specific" mode used selected_keys
            if selected_keys:
                selected_matches = [
                    m for m in db_matches 
                    if m.get("param_key") in selected_keys
                ]
                self.log(f"   🎯 LLM selected {len(selected_keys)} keys → {len(selected_matches)} matched", indent=2)
                
                # If LLM selected keys but none match DB results, fall back to all
                if not selected_matches:
                    self.log(f"   ⚠️ LLM selection didn't match DB, using all", indent=2)
                    selected_matches = db_matches
                    resolution_mode = "all_sources"
            else:
                # No selection from LLM - use all matches
                selected_matches = db_matches
            
            # Get semantic info from selected matches
            if selected_matches:
                # Collect unique values from selected matches
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
            else:
                return {
                    "term": term,
                    "param_keys": [m.get("param_key") for m in db_matches],
                    "semantic_name": normalized,
                    "unit": None,
                    "concept_category": None,
                    "resolution_mode": "all_sources",
                    "confidence": 0.7,
                    "reasoning": "LLM selection empty, using all sources"
                }
                
        except Exception as e:
            self.log(f"❌ LLM resolution error: {e}", indent=2)
            # Fallback to all sources
            return self._create_all_sources_result(term, normalized, db_matches)
