# AnalysisAgent/src/models/plan.py
"""
Planning Models

Defines models for analysis plans.

Components:
- PlanStep: Single execution step (one analysis task)
- AnalysisPlan: Complete analysis plan (multiple PlanSteps)
"""

from typing import Dict, List, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class PlanStep(BaseModel):
    """Single execution step"""
    
    # Step identification
    id: str  # "step_1", "step_2", ...
    order: int = 0  # Execution order (0-based)
    
    # Action description
    action: str  # "calculate_mean", "compute_correlation", "filter_data", ...
    description: str  # "Calculate the mean of HR column"
    
    # Execution mode
    execution_mode: Literal["tool", "code"] = "code"
    tool_name: Optional[str] = None  # Tool name if using Tool
    
    # Inputs
    inputs: List[str] = Field(default_factory=list)
    # ["df", "cohort"] - Variable names to use
    # ["step_1.result"] - Reference to previous step result
    
    input_columns: List[str] = Field(default_factory=list)
    # ["HR", "SpO2"] - Column names to use (hint)
    
    parameters: Dict[str, Any] = Field(default_factory=dict)
    # {"threshold": 100, "method": "pearson"} - Additional parameters
    
    # Output
    output_key: str  # "step_1_result" - Key to store result
    expected_output_type: str = "any"
    # "numeric", "dataframe", "dict", "list", "bool", "any"
    
    # Code generation hint (for CodeGen)
    code_hint: Optional[str] = None
    # "df['HR'].mean()" - Code hint to provide to LLM
    
    # Dependencies
    depends_on: List[str] = Field(default_factory=list)
    # ["step_1", "step_2"] - Preceding step IDs
    
    def to_prompt_dict(self) -> Dict[str, Any]:
        """Dictionary format for prompt inclusion"""
        return {
            "id": self.id,
            "action": self.action,
            "description": self.description,
            "inputs": self.inputs,
            "input_columns": self.input_columns,
            "parameters": self.parameters,
            "expected_output_type": self.expected_output_type,
            "code_hint": self.code_hint,
        }


class AnalysisPlan(BaseModel):
    """Complete analysis plan"""
    
    # Original query
    query: str  # "Calculate mean and std of HR"
    
    # Analysis type (determined by LLM)
    analysis_type: str = "general"
    # "statistics", "correlation", "comparison", "trend", "aggregation", "general"
    
    # Execution plan
    steps: List[PlanStep] = Field(default_factory=list)
    
    # Final output format
    expected_output: Dict[str, Any] = Field(default_factory=dict)
    # {
    #   "type": "dict",
    #   "schema": {"mean": "float", "std": "float"},
    #   "description": "Dictionary containing mean and standard deviation"
    # }
    
    # Execution mode
    execution_mode: Literal["tool_only", "code_only", "hybrid"] = "code_only"
    # - tool_only: All steps use Tool
    # - code_only: All steps use CodeGen
    # - hybrid: Mix of Tool and CodeGen
    
    # Complexity estimation
    estimated_complexity: Literal["simple", "moderate", "complex"] = "simple"
    # - simple: 1-2 steps, simple calculation
    # - moderate: 3-5 steps, medium complexity
    # - complex: 6+ steps, complex analysis
    
    # Confidence (LLM self-assessment)
    confidence: float = 0.8
    # 0.0 ~ 1.0, LLM self-assesses plan appropriateness
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    planning_time_ms: Optional[float] = None
    
    # Additional info
    reasoning: Optional[str] = None
    # LLM's explanation for planning decisions
    
    warnings: List[str] = Field(default_factory=list)
    # Potential issues detected during planning
    
    @property
    def step_count(self) -> int:
        """Number of steps"""
        return len(self.steps)
    
    @property
    def has_tool_steps(self) -> bool:
        """Whether there are Tool steps"""
        return any(step.execution_mode == "tool" for step in self.steps)
    
    @property
    def has_code_steps(self) -> bool:
        """Whether there are CodeGen steps"""
        return any(step.execution_mode == "code" for step in self.steps)
    
    def get_step(self, step_id: str) -> Optional[PlanStep]:
        """Get step by ID"""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None
    
    def get_execution_order(self) -> List[PlanStep]:
        """Execution order considering dependencies"""
        # Currently sorts by order (extend with topological sort if needed)
        return sorted(self.steps, key=lambda s: s.order)
    
    def validate(self) -> List[str]:
        """Validate plan"""
        errors = []
        
        # Error if no steps
        if not self.steps:
            errors.append("No steps in plan")
            return errors
        
        # Check duplicate IDs
        step_ids = [s.id for s in self.steps]
        if len(step_ids) != len(set(step_ids)):
            errors.append("Duplicate step IDs found")
        
        # Check dependencies
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    errors.append(f"Step {step.id} depends on unknown step {dep}")
        
        # Check circular dependencies (simple version)
        for step in self.steps:
            if step.id in step.depends_on:
                errors.append(f"Step {step.id} has self-dependency")
        
        return errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "query": self.query,
            "analysis_type": self.analysis_type,
            "steps": [step.model_dump() for step in self.steps],
            "expected_output": self.expected_output,
            "execution_mode": self.execution_mode,
            "estimated_complexity": self.estimated_complexity,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "warnings": self.warnings,
        }
    
    def describe(self) -> str:
        """Human-readable description"""
        lines = [
            f"## Analysis Plan",
            f"Query: {self.query}",
            f"Type: {self.analysis_type}",
            f"Complexity: {self.estimated_complexity}",
            f"Confidence: {self.confidence:.0%}",
            f"",
            f"### Steps ({self.step_count})",
        ]
        
        for step in self.get_execution_order():
            mode_icon = "🔧" if step.execution_mode == "tool" else "💻"
            lines.append(f"{mode_icon} {step.id}: {step.description}")
            if step.code_hint:
                lines.append(f"   Hint: {step.code_hint}")
        
        if self.expected_output:
            lines.append(f"")
            lines.append(f"### Expected Output")
            lines.append(f"Type: {self.expected_output.get('type', 'unknown')}")
            if 'description' in self.expected_output:
                lines.append(f"Description: {self.expected_output['description']}")
        
        if self.warnings:
            lines.append(f"")
            lines.append(f"### Warnings")
            for w in self.warnings:
                lines.append(f"⚠️ {w}")
        
        return "\n".join(lines)


class PlanningResult(BaseModel):
    """Planner response result"""
    
    success: bool
    plan: Optional[AnalysisPlan] = None
    error: Optional[str] = None
    raw_response: Optional[str] = None  # LLM raw response (for debugging)
    
    @classmethod
    def from_plan(cls, plan: AnalysisPlan) -> "PlanningResult":
        return cls(success=True, plan=plan)
    
    @classmethod
    def from_error(cls, error: str, raw_response: Optional[str] = None) -> "PlanningResult":
        return cls(success=False, error=error, raw_response=raw_response)
