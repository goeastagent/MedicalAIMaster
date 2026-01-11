# src/agents/nodes/plan_builder/node.py
"""
PlanBuilderNode - [300] Execution Plan 생성

Responsibilities:
1. schema_context 기반 동적 토폴로지 결정
2. Execution Plan JSON 조립
3. Temporal alignment 설정
4. Validation (파일 존재 확인, confidence 계산)
"""

from typing import Dict, Any, List
from datetime import datetime
from shared.langgraph import BaseNode, register_node
from ExtractionAgent.src.config import ExtractionConfig


@register_node
class PlanBuilderNode(BaseNode):
    """
    [300] Plan Builder Node
    
    Creates the final Execution Plan JSON.
    
    Input:
        - schema_context: Dict (cohort_sources, signal_groups, relationships)
        - resolved_parameters: List[Dict] (param_keys, resolution_mode, ...)
        - cohort_filters: List[Dict] (column, operator, value)
        - temporal_context: Dict (type, margin_seconds, ...)
        - user_query: str
    
    Output:
        - execution_plan: Dict (final JSON)
        - validation: Dict (warnings, confidence)
    """
    
    name = "plan_builder"
    description = "Execution Plan JSON generation"
    order = 300
    requires_llm = False
    requires_db = False
    
    def __init__(self):
        super().__init__()
        self.config = ExtractionConfig().plan_builder
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute plan building
        
        1. Extract topology from schema_context
        2. Build Execution Plan JSON
        3. Perform validation
        """
        user_query = state.get("user_query", "")
        schema_context = state.get("schema_context", {})
        resolved_parameters = state.get("resolved_parameters", [])
        cohort_filters = state.get("cohort_filters", [])
        temporal_context = state.get("temporal_context", {})
        has_ambiguity = state.get("has_ambiguity", False)
        
        self.log("🔨 Starting Execution Plan generation")
        
        # Check for ambiguities first
        if has_ambiguity:
            self.log("⚠️ Ambiguities detected - plan may be incomplete", indent=1)
        
        # 1. Extract topology
        topology = self._extract_topology(schema_context)
        cohort_name = topology.get("cohort_source", {}).get("file_name") if topology.get("cohort_source") else "None"
        signal_name = topology.get("signal_group", {}).get("group_name") if topology.get("signal_group") else "None"
        self.log(f"📐 Topology: cohort={cohort_name}, signal_group={signal_name}", indent=1)
        
        # 2. Build Execution Plan
        execution_plan = self._build_execution_plan(
            user_query=user_query,
            topology=topology,
            resolved_parameters=resolved_parameters,
            cohort_filters=cohort_filters,
            temporal_context=temporal_context
        )
        self.log("✅ Execution Plan assembled", indent=1)
        
        # 3. Validation
        validation = self._validate_plan(
            execution_plan=execution_plan,
            schema_context=schema_context,
            resolved_parameters=resolved_parameters,
            has_ambiguity=has_ambiguity
        )
        self.log(f"🔍 Validation: confidence={validation.get('confidence', 0):.2f}", indent=1)
        
        if validation.get("warnings"):
            for warning in validation["warnings"]:
                self.log(f"⚠️ {warning}", indent=2)
        
        return {
            "plan_builder_result": {
                "status": "success",
                "node": self.name,
                "confidence": validation.get("confidence", 0),
                "warning_count": len(validation.get("warnings", []))
            },
            "execution_plan": execution_plan,
            "validation": validation,
            "logs": self._logs
        }
    
    def _extract_topology(self, schema_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract topology information from schema_context.
        
        Dynamically determines:
        - Which cohort source to use
        - Which signal group to use
        - How to join them
        
        Returns:
            {
                "cohort_source": {...},   # file_id, file_name, entity_identifier
                "signal_group": {...},    # group_id, group_name, entity_identifier_key
                "join_spec": {            # join configuration
                    "cohort_key": "...",
                    "signal_key": "...",
                    "relationship_type": "..."
                }
            }
        """
        cohort_sources = schema_context.get("cohort_sources", [])
        signal_groups = schema_context.get("signal_groups", [])
        relationships = schema_context.get("relationships", [])
        
        topology = {
            "cohort_source": None,
            "signal_group": None,
            "join_spec": None
        }
        
        # Select first cohort source (could be enhanced to select best match)
        if cohort_sources:
            topology["cohort_source"] = cohort_sources[0]
        
        # Select first signal group
        if signal_groups:
            topology["signal_group"] = signal_groups[0]
        
        # Find join specification from relationships
        if relationships and topology["cohort_source"] and topology["signal_group"]:
            cohort_name = topology["cohort_source"].get("file_name")
            signal_name = topology["signal_group"].get("group_name")
            
            for rel in relationships:
                # Match relationship between cohort and signal
                from_table = rel.get("from_table", "")
                to_table = rel.get("to_table", "")
                
                if (cohort_name and signal_name and 
                    (cohort_name in from_table or cohort_name in to_table)):
                    topology["join_spec"] = {
                        "cohort_key": rel.get("from_column"),
                        "signal_key": rel.get("to_column"),
                        "relationship_type": rel.get("relationship_type"),
                        "cardinality": rel.get("cardinality")
                    }
                    break
        
        # Fallback: use entity_identifier as join key
        if not topology["join_spec"] and topology["cohort_source"]:
            entity_id = topology["cohort_source"].get("entity_identifier")
            if entity_id:
                topology["join_spec"] = {
                    "cohort_key": entity_id,
                    "signal_key": entity_id,  # Assume same key name
                    "relationship_type": "inferred",
                    "cardinality": "1:N"
                }
        
        return topology
    
    def _build_execution_plan(
        self,
        user_query: str,
        topology: Dict[str, Any],
        resolved_parameters: List[Dict[str, Any]],
        cohort_filters: List[Dict[str, Any]],
        temporal_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build the complete Execution Plan JSON."""
        
        # Cohort source configuration
        cohort_source_plan = None
        if topology.get("cohort_source"):
            cs = topology["cohort_source"]
            cohort_source_plan = {
                "file_id": cs.get("file_id"),
                "file_name": cs.get("file_name"),
                "entity_identifier": cs.get("entity_identifier"),
                "row_represents": cs.get("row_represents"),
                "filters": self._build_filters(cohort_filters, cs)
            }
        
        # Signal source configuration
        signal_source_plan = None
        if topology.get("signal_group"):
            sg = topology["signal_group"]
            signal_source_plan = {
                "group_id": sg.get("group_id"),
                "group_name": sg.get("group_name"),
                "file_pattern": sg.get("file_pattern"),
                "parameters": self._build_parameters_spec(resolved_parameters),
                "temporal_alignment": self._build_temporal_alignment(
                    temporal_context, 
                    topology.get("cohort_source")
                )
            }
        
        # Join specification
        join_spec = None
        if topology.get("join_spec"):
            js = topology["join_spec"]
            join_spec = {
                "type": "inner",
                "cohort_key": js.get("cohort_key"),
                "signal_key": js.get("signal_key"),
                "cardinality": js.get("cardinality", "1:N")
            }
        
        return {
            "version": "1.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "agent": "ExtractionAgent",
            "original_query": user_query,
            "execution_plan": {
                "cohort_source": cohort_source_plan,
                "signal_source": signal_source_plan,
                "join_specification": join_spec
            }
        }
    
    def _build_filters(
        self, 
        cohort_filters: List[Dict[str, Any]], 
        cohort_source: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Build filter specifications with validation."""
        if not cohort_filters:
            return []
        
        # Get available columns from cohort source
        available_columns = set()
        for col in cohort_source.get("filterable_columns", []):
            available_columns.add(col.get("column_name", ""))
        
        validated_filters = []
        for f in cohort_filters:
            filter_spec = {
                "column": f.get("column"),
                "operator": f.get("operator", "="),
                "value": f.get("value"),
                "validated": f.get("column") in available_columns if available_columns else True
            }
            validated_filters.append(filter_spec)
        
        return validated_filters
    
    def _build_parameters_spec(
        self, 
        resolved_parameters: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Build parameter specifications for the plan."""
        params_spec = []
        
        for p in resolved_parameters:
            param_spec = {
                "term": p.get("term"),
                "param_keys": p.get("param_keys", []),
                "semantic_name": p.get("semantic_name"),
                "unit": p.get("unit"),
                "resolution_mode": p.get("resolution_mode"),
                "confidence": p.get("confidence", 0.0)
            }
            params_spec.append(param_spec)
        
        return params_spec
    
    def _build_temporal_alignment(
        self, 
        temporal_context: Dict[str, Any],
        cohort_source: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Build temporal alignment configuration."""
        temporal_type = temporal_context.get("type", self.config.default_temporal_type)
        
        alignment = {
            "type": temporal_type,
            "margin_seconds": temporal_context.get("margin_seconds", 0)
        }
        
        # Add column references for windowed types
        if temporal_type in ("procedure_window", "treatment_window", "custom_window"):
            # Try to get from temporal_context first
            start_col = temporal_context.get("start_column")
            end_col = temporal_context.get("end_column")
            
            # Fallback: infer from cohort source temporal columns
            if not start_col and cohort_source:
                temporal_cols = cohort_source.get("temporal_columns", [])
                for tc in temporal_cols:
                    col_name = tc.get("column_name", "").lower()
                    if "start" in col_name or "begin" in col_name:
                        start_col = tc.get("column_name")
                    elif "end" in col_name or "finish" in col_name:
                        end_col = tc.get("column_name")
            
            alignment["start_column"] = start_col
            alignment["end_column"] = end_col
        
        return alignment
    
    def _validate_plan(
        self, 
        execution_plan: Dict[str, Any],
        schema_context: Dict[str, Any],
        resolved_parameters: List[Dict[str, Any]],
        has_ambiguity: bool = False
    ) -> Dict[str, Any]:
        """
        Validate the Execution Plan.
        
        Checks:
        - Required components present
        - Parameter mapping completeness
        - Filter validation
        - Confidence calculation
        """
        warnings: List[str] = []
        confidence = 1.0
        
        plan = execution_plan.get("execution_plan", {})
        
        # 1. Cohort source validation
        cohort_source = plan.get("cohort_source")
        if not cohort_source:
            warnings.append("No cohort_source configured")
            confidence -= 0.3
        else:
            # Check for invalid filters
            filters = cohort_source.get("filters", [])
            invalid_filters = [f for f in filters if not f.get("validated", True)]
            if invalid_filters:
                warnings.append(f"{len(invalid_filters)} filter(s) reference unknown columns")
                confidence -= 0.05 * len(invalid_filters)
        
        # 2. Signal source validation
        signal_source = plan.get("signal_source")
        if not signal_source:
            warnings.append("No signal_source configured")
            confidence -= 0.3
        else:
            params = signal_source.get("parameters", [])
            if not params:
                warnings.append("No parameters requested")
                confidence -= 0.2
            else:
                # Check unmapped parameters
                unmapped = [p for p in params if not p.get("param_keys")]
                if unmapped:
                    terms = [p.get("term") for p in unmapped]
                    warnings.append(f"Unmapped parameters: {terms}")
                    confidence -= 0.15 * len(unmapped)
                
                # Check low-confidence parameters
                low_conf = [p for p in params if p.get("confidence", 1.0) < self.config.min_confidence]
                if low_conf:
                    warnings.append(f"{len(low_conf)} parameter(s) have low confidence")
                    confidence -= 0.05 * len(low_conf)
            
            # Check temporal alignment
            temporal = signal_source.get("temporal_alignment", {})
            if temporal.get("type") in ("procedure_window", "treatment_window"):
                if not temporal.get("start_column") or not temporal.get("end_column"):
                    warnings.append(f"Temporal window '{temporal.get('type')}' missing start/end columns")
                    confidence -= 0.1
        
        # 3. Join specification validation
        if not plan.get("join_specification"):
            warnings.append("No join_specification configured")
            confidence -= 0.1
        
        # 4. Ambiguity penalty
        if has_ambiguity:
            warnings.append("Ambiguous parameters require user clarification")
            confidence -= 0.2
        
        # Clamp confidence
        confidence = max(0.0, min(1.0, confidence))
        
        return {
            "is_valid": confidence >= self.config.min_confidence,
            "warnings": warnings,
            "confidence": round(confidence, 2),
            "validated_at": datetime.utcnow().isoformat() + "Z"
        }
