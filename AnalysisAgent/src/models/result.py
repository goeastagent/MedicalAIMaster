# AnalysisAgent/src/models/result.py
"""
Analysis Result Models

Defines models for storing and managing analysis results.
"""

import hashlib
import json
from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class AnalysisResult(BaseModel):
    """
    Complete result of an analysis operation.
    
    Stores the query, plan, execution results, and metadata
    for caching, history tracking, and auditing.
    """
    
    # Unique identifier
    id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d%H%M%S%f"))
    
    # Query information
    query: str
    query_hash: str = ""  # For cache lookup
    
    # Input context summary (for reference, not full data)
    input_summary: Dict[str, Any] = Field(default_factory=dict)
    # {
    #   "dataframes": {"signals": {"cases": 100, "columns": ["Time", "HR", "SpO2"]}},
    #   "join_keys": ["entity_id"],
    # }
    
    # Execution plan
    plan: Dict[str, Any] = Field(default_factory=dict)
    # {
    #   "analysis_type": "statistics",
    #   "steps": [...],
    #   "estimated_complexity": "simple"
    # }
    
    # Step-by-step results
    step_results: List[Dict[str, Any]] = Field(default_factory=list)
    # [
    #   {"step_id": "step_1", "status": "success", "result": 72.5, ...},
    #   {"step_id": "step_2", "status": "success", "result": {...}, ...}
    # ]
    
    # Final result
    final_result: Any = None
    final_result_type: str = "any"
    # "numeric", "dataframe", "dict", "list", "bool", "string"
    
    # Output schema (if applicable)
    output_schema: Optional[Dict[str, Any]] = None
    # {
    #   "type": "dict",
    #   "properties": {"mean": "float", "std": "float"}
    # }
    
    # Generated code (if CodeGen was used)
    generated_code: Optional[str] = None
    
    # Execution status
    status: Literal["success", "error", "partial", "cached"] = "success"
    error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    
    # Timing
    execution_time_ms: float = 0.0
    created_at: datetime = Field(default_factory=datetime.now)
    
    # Lineage tracking
    parent_id: Optional[str] = None  # If derived from another result
    
    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # {
    #   "execution_mode": "code",
    #   "tool_names": ["mean_calculator"],
    #   "retries": 0
    # }
    
    def model_post_init(self, __context):
        """Generate query_hash after initialization"""
        if not self.query_hash and self.query:
            self.query_hash = self._compute_hash()
    
    def _compute_hash(self) -> str:
        """Compute hash of query + input summary for cache key"""
        # Normalize query (lowercase, strip)
        normalized_query = self.query.lower().strip()
        
        # Include input schema info for context-aware caching
        input_str = json.dumps(self.input_summary, sort_keys=True, default=str)
        
        combined = f"{normalized_query}:{input_str}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]
    
    @classmethod
    def create_success(
        cls,
        query: str,
        final_result: Any,
        final_result_type: str,
        plan: Dict[str, Any],
        step_results: List[Dict[str, Any]],
        execution_time_ms: float,
        input_summary: Optional[Dict[str, Any]] = None,
        generated_code: Optional[str] = None,
        **kwargs
    ) -> "AnalysisResult":
        """Create a successful result"""
        return cls(
            query=query,
            final_result=final_result,
            final_result_type=final_result_type,
            plan=plan,
            step_results=step_results,
            execution_time_ms=execution_time_ms,
            input_summary=input_summary or {},
            generated_code=generated_code,
            status="success",
            **kwargs
        )
    
    @classmethod
    def create_error(
        cls,
        query: str,
        error: str,
        plan: Optional[Dict[str, Any]] = None,
        step_results: Optional[List[Dict[str, Any]]] = None,
        execution_time_ms: float = 0.0,
        **kwargs
    ) -> "AnalysisResult":
        """Create an error result"""
        return cls(
            query=query,
            status="error",
            error=error,
            plan=plan or {},
            step_results=step_results or [],
            execution_time_ms=execution_time_ms,
            **kwargs
        )
    
    @classmethod
    def create_cached(
        cls,
        original: "AnalysisResult"
    ) -> "AnalysisResult":
        """Create a cached copy of an existing result"""
        return cls(
            id=datetime.now().strftime("%Y%m%d%H%M%S%f"),
            query=original.query,
            query_hash=original.query_hash,
            input_summary=original.input_summary,
            plan=original.plan,
            step_results=original.step_results,
            final_result=original.final_result,
            final_result_type=original.final_result_type,
            output_schema=original.output_schema,
            generated_code=original.generated_code,
            status="cached",
            execution_time_ms=0.0,  # No new execution
            parent_id=original.id,
            metadata={**original.metadata, "cached_from": original.id}
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/serialization"""
        return {
            "id": self.id,
            "query": self.query,
            "query_hash": self.query_hash,
            "input_summary": self.input_summary,
            "plan": self.plan,
            "step_results": self.step_results,
            "final_result": self._serialize_result(self.final_result),
            "final_result_type": self.final_result_type,
            "output_schema": self.output_schema,
            "generated_code": self.generated_code,
            "status": self.status,
            "error": self.error,
            "warnings": self.warnings,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat(),
            "parent_id": self.parent_id,
            "metadata": self.metadata,
        }
    
    def _serialize_result(self, result: Any) -> Any:
        """Serialize result for JSON storage"""
        if result is None:
            return None
        
        # Handle pandas DataFrame
        if hasattr(result, 'to_dict'):
            try:
                return {"_type": "dataframe", "data": result.to_dict('records')[:100]}
            except Exception:
                return {"_type": "dataframe", "preview": str(result)[:500]}
        
        # Handle numpy types
        if hasattr(result, 'item'):
            return result.item()
        
        # Handle numpy arrays
        if hasattr(result, 'tolist'):
            return result.tolist()
        
        return result
    
    def get_summary(self) -> str:
        """Get human-readable summary of the result"""
        lines = [
            f"Query: {self.query}",
            f"Status: {self.status}",
            f"Execution Time: {self.execution_time_ms:.1f}ms",
        ]
        
        if self.status == "success":
            lines.append(f"Result Type: {self.final_result_type}")
            result_preview = str(self.final_result)[:100]
            lines.append(f"Result: {result_preview}")
        elif self.status == "error":
            lines.append(f"Error: {self.error}")
        
        return "\n".join(lines)


class ResultSummary(BaseModel):
    """Lightweight summary of a result for listing"""
    
    id: str
    query: str
    status: str
    final_result_type: str
    execution_time_ms: float
    created_at: datetime
    
    @classmethod
    def from_result(cls, result: AnalysisResult) -> "ResultSummary":
        return cls(
            id=result.id,
            query=result.query,
            status=result.status,
            final_result_type=result.final_result_type,
            execution_time_ms=result.execution_time_ms,
            created_at=result.created_at,
        )
