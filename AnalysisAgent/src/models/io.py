# AnalysisAgent/src/models/io.py
"""
I/O Models for Step Execution

Defines input and output models for analysis steps.
These models are used by both Tool execution and CodeGen execution.
"""

from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class StepInput(BaseModel):
    """Input for a single execution step"""
    
    # Step identification
    step_id: str
    
    # Data to operate on
    data: Dict[str, Any] = Field(default_factory=dict)
    # {
    #   "df": pd.DataFrame,
    #   "cohort": pd.DataFrame,
    #   "step_1_result": Any,  # Previous step result
    # }
    
    # Step parameters
    parameters: Dict[str, Any] = Field(default_factory=dict)
    # {
    #   "threshold": 100,
    #   "method": "pearson",
    # }
    
    # Columns to use (hint for execution)
    input_columns: List[str] = Field(default_factory=list)
    
    # Code hint (for CodeGen)
    code_hint: Optional[str] = None
    
    # Expected output type
    expected_output_type: str = "any"
    
    # Additional context
    context: Optional[Dict[str, Any]] = None
    
    def get_dataframe(self, name: str = "df"):
        """Get DataFrame from data dict"""
        return self.data.get(name)
    
    def get_previous_result(self, step_id: str):
        """Get result from previous step"""
        key = f"{step_id}_result"
        return self.data.get(key)


class StepOutput(BaseModel):
    """Output from a single execution step"""
    
    # Step identification
    step_id: str
    
    # Execution status
    status: Literal["success", "error", "warning"] = "success"
    
    # Result data
    result: Any = None
    result_type: str = "any"
    # "numeric", "dataframe", "dict", "list", "bool", "string", "any"
    
    # Output key (for storing in data context)
    output_key: str = ""
    
    # Error information
    error: Optional[str] = None
    error_type: Optional[str] = None
    # "validation", "execution", "timeout", "runtime"
    
    # Warning messages
    warnings: List[str] = Field(default_factory=list)
    
    # Execution metadata
    execution_time_ms: Optional[float] = None
    executed_at: datetime = Field(default_factory=datetime.now)
    
    # Execution details
    execution_mode: Literal["tool", "code"] = "code"
    tool_name: Optional[str] = None
    generated_code: Optional[str] = None
    
    # Additional metadata
    meta: Dict[str, Any] = Field(default_factory=dict)
    
    @classmethod
    def success(
        cls,
        step_id: str,
        result: Any,
        output_key: str,
        result_type: str = "any",
        execution_time_ms: Optional[float] = None,
        **kwargs
    ) -> "StepOutput":
        """Create successful output"""
        return cls(
            step_id=step_id,
            status="success",
            result=result,
            result_type=result_type,
            output_key=output_key,
            execution_time_ms=execution_time_ms,
            **kwargs
        )
    
    @classmethod
    def error(
        cls,
        step_id: str,
        error: str,
        error_type: str = "execution",
        output_key: str = "",
        **kwargs
    ) -> "StepOutput":
        """Create error output"""
        return cls(
            step_id=step_id,
            status="error",
            error=error,
            error_type=error_type,
            output_key=output_key,
            **kwargs
        )
    
    @classmethod
    def warning(
        cls,
        step_id: str,
        result: Any,
        output_key: str,
        warnings: List[str],
        **kwargs
    ) -> "StepOutput":
        """Create output with warnings"""
        return cls(
            step_id=step_id,
            status="warning",
            result=result,
            output_key=output_key,
            warnings=warnings,
            **kwargs
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "step_id": self.step_id,
            "status": self.status,
            "result": self.result,
            "result_type": self.result_type,
            "output_key": self.output_key,
            "error": self.error,
            "error_type": self.error_type,
            "warnings": self.warnings,
            "execution_time_ms": self.execution_time_ms,
            "execution_mode": self.execution_mode,
            "tool_name": self.tool_name,
            "generated_code": self.generated_code,
        }


class ExecutionState(BaseModel):
    """State maintained during plan execution"""
    
    # Data context (accumulated results)
    data: Dict[str, Any] = Field(default_factory=dict)
    # {
    #   "df": pd.DataFrame,  # Original input
    #   "cohort": pd.DataFrame,
    #   "step_1_result": Any,
    #   "step_2_result": Any,
    # }
    
    # Step outputs
    step_outputs: List[StepOutput] = Field(default_factory=list)
    
    # Execution status
    current_step_index: int = 0
    total_steps: int = 0
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def add_step_output(self, output: StepOutput) -> None:
        """Add step output and update data context"""
        self.step_outputs.append(output)
        
        if output.status == "success" and output.output_key:
            # Store result in data context for subsequent steps
            self.data[output.output_key] = output.result
    
    def get_step_result(self, step_id: str) -> Optional[Any]:
        """Get result from a specific step"""
        for output in self.step_outputs:
            if output.step_id == step_id:
                return output.result
        return None
    
    def get_final_result(self) -> Optional[Any]:
        """Get result from last successful step"""
        for output in reversed(self.step_outputs):
            if output.status == "success":
                return output.result
        return None
    
    def has_errors(self) -> bool:
        """Check if any step has errors"""
        return any(o.status == "error" for o in self.step_outputs)
    
    def get_errors(self) -> List[str]:
        """Get all error messages"""
        return [o.error for o in self.step_outputs if o.error]
    
    @property
    def total_execution_time_ms(self) -> float:
        """Total execution time across all steps"""
        return sum(
            o.execution_time_ms or 0
            for o in self.step_outputs
        )
