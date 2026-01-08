"""AnalysisAgent - Data Analysis Agent

Generic data analysis agent:
- Context Building: DataContext → AnalysisContext
- Planning: LLM-based analysis planning
- Execution: Tool or CodeGen execution
- Results: Result management and caching

Usage:
    from AnalysisAgent.src import AnalysisAgent
    
    agent = AnalysisAgent()
    result = agent.analyze("Calculate mean of HR", data_context)
"""

# Main Agent (Phase 5)
from .agent import AnalysisAgent

from .config import (
    AnalysisAgentConfig,
    CodeGenConfig,
    SandboxConfig,
    ValidatorConfig,
    GeneratorConfig,
    DEFAULT_CONFIG,
    get_config,
    create_config,
)

# Context Building (Phase 1)
from .context import (
    ColumnInfo,
    DataFrameSchema,
    AnalysisContext,
    ContextBuilder,
)

# Planning (Phase 2)
from .planner import (
    PlanStep,
    AnalysisPlan,
    PlanningResult,
    AnalysisPlanner,
)

# Execution (Phase 3)
from .executor import (
    ExecutionRouter,
    StepExecutor,
)

from .tools import (
    BaseTool,
    ToolMetadata,
    ToolRegistry,
    get_tool_registry,
)

from .models.io import (
    StepInput,
    StepOutput,
    ExecutionState,
)

# Results (Phase 4)
from .results import (
    AnalysisResult,
    ResultSummary,
    ResultStore,
    get_result_store,
)

__all__ = [
    # Main Agent (Phase 5)
    "AnalysisAgent",
    "AnalysisAgentConfig",
    
    # Config (CodeGen)
    "CodeGenConfig",
    "SandboxConfig",
    "ValidatorConfig",
    "GeneratorConfig",
    "DEFAULT_CONFIG",
    "get_config",
    "create_config",
    
    # Context (Phase 1)
    "ColumnInfo",
    "DataFrameSchema",
    "AnalysisContext",
    "ContextBuilder",
    
    # Planning (Phase 2)
    "PlanStep",
    "AnalysisPlan",
    "PlanningResult",
    "AnalysisPlanner",
    
    # Execution (Phase 3)
    "ExecutionRouter",
    "StepExecutor",
    "BaseTool",
    "ToolMetadata",
    "ToolRegistry",
    "get_tool_registry",
    "StepInput",
    "StepOutput",
    "ExecutionState",
    
    # Results (Phase 4)
    "AnalysisResult",
    "ResultSummary",
    "ResultStore",
    "get_result_store",
]
