# AnalysisAgent/src/tools/base.py
"""
Base Tool Class

Defines the interface for analysis tools.
Tools are pre-defined, validated functions that can be used by the executor.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Callable
from pydantic import BaseModel, Field
import time

from ..models.io import StepInput, StepOutput


class ToolMetadata(BaseModel):
    """Metadata describing a tool for the Planner"""
    
    name: str
    description: str
    
    # Input schema (JSON Schema format)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    # {
    #   "type": "object",
    #   "properties": {
    #     "column": {"type": "string", "description": "Column name"},
    #     "threshold": {"type": "number", "description": "Threshold value"}
    #   },
    #   "required": ["column"]
    # }
    
    # Expected output type
    output_type: str = "any"
    # "numeric", "dataframe", "dict", "list", "bool"
    
    # Tags for categorization
    tags: List[str] = Field(default_factory=list)
    # ["statistics", "correlation", "filtering", "aggregation"]
    
    # Example usage
    examples: List[Dict[str, Any]] = Field(default_factory=list)
    # [
    #   {"input": {"column": "HR"}, "output": 72.5}
    # ]
    
    def to_planner_dict(self) -> Dict[str, Any]:
        """Convert to dict for Planner context"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_type": self.output_type,
            "tags": self.tags,
        }


class BaseTool(ABC):
    """
    Base class for analysis tools.
    
    Tools are pre-defined functions that:
    1. Have clear input/output schemas
    2. Are validated before execution
    3. Provide more reliable results than CodeGen for common operations
    
    Usage:
        class MeanTool(BaseTool):
            @property
            def metadata(self) -> ToolMetadata:
                return ToolMetadata(
                    name="compute_mean",
                    description="Calculate mean of a column",
                    input_schema={
                        "type": "object",
                        "properties": {"column": {"type": "string"}},
                        "required": ["column"]
                    },
                    output_type="numeric",
                    tags=["statistics"]
                )
            
            def execute(self, step_input: StepInput) -> StepOutput:
                df = step_input.get_dataframe()
                col = step_input.parameters["column"]
                result = df[col].mean()
                return StepOutput.success(
                    step_id=step_input.step_id,
                    result=result,
                    output_key=f"{step_input.step_id}_result"
                )
    """
    
    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        """Return tool metadata"""
        pass
    
    @property
    def name(self) -> str:
        """Tool name"""
        return self.metadata.name
    
    @property
    def description(self) -> str:
        """Tool description"""
        return self.metadata.description
    
    @property
    def tags(self) -> List[str]:
        """Tool tags"""
        return self.metadata.tags
    
    def validate_input(self, step_input: StepInput) -> List[str]:
        """
        Validate input against schema.
        
        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        schema = self.metadata.input_schema
        
        if not schema:
            return errors
        
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        
        # Check required parameters
        for param in required:
            if param not in step_input.parameters:
                # Check if it's in input_columns
                if param == "column" and step_input.input_columns:
                    continue
                errors.append(f"Missing required parameter: {param}")
        
        # Validate types (basic)
        for param, value in step_input.parameters.items():
            if param in properties:
                expected_type = properties[param].get("type")
                if expected_type:
                    if expected_type == "string" and not isinstance(value, str):
                        errors.append(f"Parameter '{param}' must be string")
                    elif expected_type == "number" and not isinstance(value, (int, float)):
                        errors.append(f"Parameter '{param}' must be number")
                    elif expected_type == "boolean" and not isinstance(value, bool):
                        errors.append(f"Parameter '{param}' must be boolean")
        
        return errors
    
    @abstractmethod
    def execute(self, step_input: StepInput) -> StepOutput:
        """
        Execute the tool.
        
        Args:
            step_input: Input data and parameters
        
        Returns:
            StepOutput with result or error
        """
        pass
    
    def run(self, step_input: StepInput) -> StepOutput:
        """
        Validate and execute the tool.
        
        This is the main entry point that wraps execute() with validation
        and timing.
        """
        start_time = time.time()
        
        # Validate input
        validation_errors = self.validate_input(step_input)
        if validation_errors:
            return StepOutput.error(
                step_id=step_input.step_id,
                error="; ".join(validation_errors),
                error_type="validation",
                output_key=f"{step_input.step_id}_result",
                execution_mode="tool",
                tool_name=self.name,
            )
        
        try:
            # Execute
            output = self.execute(step_input)
            
            # Add execution metadata
            execution_time = (time.time() - start_time) * 1000
            output.execution_time_ms = execution_time
            output.execution_mode = "tool"
            output.tool_name = self.name
            
            return output
        
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            return StepOutput.error(
                step_id=step_input.step_id,
                error=str(e),
                error_type="execution",
                output_key=f"{step_input.step_id}_result",
                execution_mode="tool",
                tool_name=self.name,
                execution_time_ms=execution_time,
            )


def create_simple_tool(
    name: str,
    description: str,
    func: Callable[[StepInput], Any],
    input_schema: Optional[Dict[str, Any]] = None,
    output_type: str = "any",
    tags: Optional[List[str]] = None,
) -> BaseTool:
    """
    Factory function to create a simple tool from a function.
    
    Usage:
        def compute_mean(step_input: StepInput) -> float:
            df = step_input.get_dataframe()
            col = step_input.parameters.get("column", step_input.input_columns[0])
            return df[col].mean()
        
        mean_tool = create_simple_tool(
            name="compute_mean",
            description="Calculate mean of a column",
            func=compute_mean,
            output_type="numeric",
            tags=["statistics"]
        )
    """
    
    class SimpleTool(BaseTool):
        @property
        def metadata(self) -> ToolMetadata:
            return ToolMetadata(
                name=name,
                description=description,
                input_schema=input_schema or {},
                output_type=output_type,
                tags=tags or [],
            )
        
        def execute(self, step_input: StepInput) -> StepOutput:
            result = func(step_input)
            return StepOutput.success(
                step_id=step_input.step_id,
                result=result,
                result_type=output_type,
                output_key=f"{step_input.step_id}_result",
            )
    
    return SimpleTool()
