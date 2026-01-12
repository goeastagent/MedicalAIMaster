"""AnalysisAgent Models

Central location for all Pydantic models.
"""

# Context models
from .context import ExecutionContext, DataSummary, DataSchema, ColumnDescription

# Code generation models
from .code_gen import (
    CodeRequest,
    ValidationResult,
    GenerationResult,
    ExecutionResult,
    CodeResult,
    # Map-Reduce models
    MapReduceRequest,
    MapReduceGenerationResult,
    MapReduceExecutionResult,
)

# I/O models (Step execution)
from .io import (
    StepInput,
    StepOutput,
    ExecutionState,
)

# Planning models
from .plan import (
    PlanStep,
    AnalysisPlan,
    PlanningResult,
)

# Result models
from .result import (
    AnalysisResult,
    ResultSummary,
)

__all__ = [
    # Context
    "ExecutionContext",
    "DataSummary",
    "DataSchema",
    "ColumnDescription",
    # Code Generation
    "CodeRequest",
    "ValidationResult",
    "GenerationResult",
    "ExecutionResult",
    "CodeResult",
    # Map-Reduce
    "MapReduceRequest",
    "MapReduceGenerationResult",
    "MapReduceExecutionResult",
    # I/O (Step Execution)
    "StepInput",
    "StepOutput",
    "ExecutionState",
    # Planning
    "PlanStep",
    "AnalysisPlan",
    "PlanningResult",
    # Results
    "AnalysisResult",
    "ResultSummary",
]
