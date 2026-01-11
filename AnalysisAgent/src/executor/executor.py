# AnalysisAgent/src/executor/executor.py
"""
Step Executor

Executes analysis plan steps using Tool or CodeGen.
"""

import logging
import time
from typing import Dict, List, Any, Optional, TYPE_CHECKING

from ..models.plan import PlanStep, AnalysisPlan
from ..models.io import StepInput, StepOutput, ExecutionState
from ..tools.registry import ToolRegistry, get_tool_registry
from ..tools.base import BaseTool
from .router import ExecutionRouter

if TYPE_CHECKING:
    from ..code_gen.generator import CodeGenerator
    from ..code_gen.sandbox import SandboxExecutor
    from ..code_gen.engine import CodeExecutionEngine

logger = logging.getLogger(__name__)


class StepExecutor:
    """
    Executes analysis plan steps.
    
    Supports two execution modes:
    1. Tool execution: Uses pre-defined tools
    2. Code execution: Generates and executes code via CodeExecutionEngine
    
    Usage:
        executor = StepExecutor()
        
        # Execute entire plan
        state = executor.execute_plan(plan, initial_data)
        
        # Or execute single step
        output = executor.execute_step(step, input_data)
    """
    
    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        code_generator: Optional["CodeGenerator"] = None,
        sandbox_executor: Optional["SandboxExecutor"] = None,
        code_execution_engine: Optional["CodeExecutionEngine"] = None,
        max_retries: int = 2,
        timeout_seconds: int = 30,
    ):
        """
        Args:
            tool_registry: Registry for tools
            code_generator: CodeGenerator instance (lazy init if None)
            sandbox_executor: SandboxExecutor instance (lazy init if None)
            code_execution_engine: CodeExecutionEngine instance (lazy init if None)
            max_retries: Max retries for code execution
            timeout_seconds: Timeout for code execution
        """
        self._tool_registry = tool_registry or get_tool_registry()
        self._router = ExecutionRouter(self._tool_registry)
        
        self._code_generator = code_generator
        self._sandbox_executor = sandbox_executor
        self._code_execution_engine = code_execution_engine
        
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        
        # Lazy init flag
        self._codegen_initialized = False
    
    def _init_codegen(self) -> None:
        """Lazy initialization of CodeGen components."""
        if self._codegen_initialized:
            return
        
        if self._code_generator is None:
            from ..code_gen.generator import CodeGenerator
            from shared.llm import get_llm_client
            self._code_generator = CodeGenerator(
                llm_client=get_llm_client(),
                max_tokens=2048,
            )
        
        if self._sandbox_executor is None:
            from ..code_gen.sandbox import SandboxExecutor
            self._sandbox_executor = SandboxExecutor(
                timeout_seconds=self.timeout_seconds,
                capture_stdout=True,
            )
        
        if self._code_execution_engine is None:
            from ..code_gen.engine import CodeExecutionEngine
            self._code_execution_engine = CodeExecutionEngine(
                generator=self._code_generator,
                sandbox=self._sandbox_executor,
                max_retries=self.max_retries,
            )
        
        self._codegen_initialized = True
    
    def execute_plan(
        self,
        plan: AnalysisPlan,
        initial_data: Dict[str, Any],
    ) -> ExecutionState:
        """
        Execute entire analysis plan.
        
        Args:
            plan: Analysis plan to execute
            initial_data: Initial data (df, cohort, etc.)
        
        Returns:
            ExecutionState with all step results
        """
        logger.info(f"⚙️ Executing plan: {plan.step_count} steps")
        
        state = ExecutionState(
            data=initial_data.copy(),
            total_steps=plan.step_count,
            started_at=time.time(),
        )
        
        # Execute steps in order
        for step in plan.get_execution_order():
            logger.info(f"  📍 Step {step.id}: {step.action}")
            
            # Build step input
            step_input = self._build_step_input(step, state)
            
            # Execute step
            output = self.execute_step(step, step_input)
            
            # Update state
            state.add_step_output(output)
            state.current_step_index += 1
            
            # Check for errors
            if output.status == "error":
                logger.error(f"  ❌ Step {step.id} failed: {output.error}")
                # Continue or stop based on configuration
                break
            else:
                logger.info(f"  ✅ Step {step.id} completed")
        
        state.completed_at = time.time()
        
        # Log summary
        if state.has_errors():
            logger.error(f"❌ Plan execution failed: {state.get_errors()}")
        else:
            logger.info(f"✅ Plan execution completed in {state.total_execution_time_ms:.1f}ms")
        
        return state
    
    def execute_step(
        self,
        step: PlanStep,
        step_input: StepInput,
    ) -> StepOutput:
        """
        Execute a single step.
        
        Args:
            step: Step to execute
            step_input: Input data for the step
        
        Returns:
            StepOutput with result or error
        """
        # Route to Tool or CodeGen
        mode, tool = self._router.route(step)
        
        if mode == "tool" and tool:
            return self._execute_with_tool(step, step_input, tool)
        else:
            return self._execute_with_codegen(step, step_input)
    
    def _build_step_input(
        self,
        step: PlanStep,
        state: ExecutionState,
    ) -> StepInput:
        """Build StepInput from step and current state."""
        # Collect data from state
        data = {}
        for input_name in step.inputs:
            if input_name in state.data:
                data[input_name] = state.data[input_name]
            elif f"{input_name}_result" in state.data:
                data[input_name] = state.data[f"{input_name}_result"]
        
        # Add original data sources
        for key in ["df", "cohort"]:
            if key in state.data and key not in data:
                data[key] = state.data[key]
        
        return StepInput(
            step_id=step.id,
            data=data,
            parameters=step.parameters,
            input_columns=step.input_columns,
            code_hint=step.code_hint,
            expected_output_type=step.expected_output_type,
        )
    
    def _execute_with_tool(
        self,
        step: PlanStep,
        step_input: StepInput,
        tool: BaseTool,
    ) -> StepOutput:
        """Execute step using a tool."""
        logger.debug(f"    Using tool: {tool.name}")
        
        output = tool.run(step_input)
        output.output_key = step.output_key or f"{step.id}_result"
        
        return output
    
    def _execute_with_codegen(
        self,
        step: PlanStep,
        step_input: StepInput,
    ) -> StepOutput:
        """Execute step using CodeExecutionEngine."""
        logger.debug(f"    Using code generation")
        
        # Initialize CodeGen if needed
        self._init_codegen()
        
        # Build code request
        from ..models.code_gen import CodeRequest
        
        # Build execution context from step input
        exec_context = self._build_execution_context(step_input)
        
        # Create task description
        task_description = step.description
        if step.code_hint:
            task_description += f"\n\nHint: {step.code_hint}"
        
        request = CodeRequest(
            task_description=task_description,
            expected_output=step.expected_output_type,
            execution_context=exec_context,
            hints=step.code_hint,
        )
        
        # Execute using CodeExecutionEngine
        runtime_data = step_input.data.copy()
        result = self._code_execution_engine.execute(
            request,
            runtime_data,
            log_prefix=f"[{step.id}] "
        )
        
        if result.success:
            return StepOutput.success(
                step_id=step.id,
                result=result.result,
                result_type=step.expected_output_type,
                output_key=step.output_key or f"{step.id}_result",
                execution_time_ms=result.execution_time_ms,
                execution_mode="code",
                generated_code=result.code,
            )
        
        return StepOutput.error(
            step_id=step.id,
            error=result.error,
            error_type="execution",
            output_key=step.output_key or f"{step.id}_result",
            execution_time_ms=result.execution_time_ms,
            execution_mode="code",
            generated_code=result.code,
        )
    
    def _build_execution_context(self, step_input: StepInput) -> "ExecutionContext":
        """Build ExecutionContext for CodeGenerator."""
        from ..models.context import ExecutionContext, DataSchema
        
        available_variables = {}
        data_schemas = {}
        
        for name, value in step_input.data.items():
            # Check if it's a DataFrame
            if hasattr(value, 'shape') and hasattr(value, 'columns'):
                import pandas as pd
                if isinstance(value, pd.DataFrame):
                    available_variables[name] = f"pandas DataFrame - {value.shape[0]:,} rows × {value.shape[1]} columns"
                    data_schemas[name] = DataSchema(
                        name=name,
                        description="",
                        columns=list(value.columns),
                        dtypes={col: str(value[col].dtype) for col in value.columns},
                        shape=(len(value), len(value.columns)),
                        sample_rows=value.head(2).to_dict(orient="records"),
                    )
            else:
                # Other values
                type_name = type(value).__name__
                available_variables[name] = f"{type_name}"
        
        return ExecutionContext(
            available_variables=available_variables,
            data_schemas=data_schemas,
        )
