# AnalysisAgent/src/agent.py
"""
Analysis Agent

Main entry point for the AnalysisAgent.
Orchestrates context building, planning, execution, and result management.
"""

import logging
import time
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from .config import AnalysisAgentConfig
from .context.builder import ContextBuilder
from .context.schema import AnalysisContext
from .planner.planner import AnalysisPlanner
from .executor.executor import StepExecutor
from .tools.registry import ToolRegistry, get_tool_registry
from .results.store import ResultStore, get_result_store
from .models.plan import AnalysisPlan, PlanningResult
from .models.result import AnalysisResult
from .models.io import ExecutionState

if TYPE_CHECKING:
    from shared.llm.client import LLMClient
    from shared.data.context import DataContext
    import pandas as pd

logger = logging.getLogger(__name__)


class AnalysisAgent:
    """
    Main analysis agent that orchestrates the entire analysis pipeline.
    
    Pipeline:
    1. Context Building: Create AnalysisContext from data
    2. Planning: Generate execution plan (LLM or rule-based)
    3. Execution: Execute plan steps (Tool or CodeGen)
    4. Result Assembly: Store and return results
    
    Usage:
        agent = AnalysisAgent()
        
        # Analyze with DataContext
        result = agent.analyze("Calculate mean of HR", data_context)
        
        # Analyze with DataFrame directly
        result = agent.analyze_dataframes(
            "Calculate mean of HR",
            {"df": signal_df, "cohort": cohort_df}
        )
    """
    
    def __init__(
        self,
        llm_client: Optional["LLMClient"] = None,
        tool_registry: Optional[ToolRegistry] = None,
        result_store: Optional[ResultStore] = None,
        config: Optional[AnalysisAgentConfig] = None,
    ):
        """
        Initialize AnalysisAgent.
        
        Args:
            llm_client: LLM client for planning and code generation
            tool_registry: Registry for analysis tools
            result_store: Store for caching results
            config: Agent configuration
        """
        self.config = config or AnalysisAgentConfig()
        
        # Components (lazy init for LLM)
        self._llm_client = llm_client
        self._tool_registry = tool_registry or get_tool_registry()
        self._result_store = result_store or get_result_store(
            cache_ttl_minutes=self.config.cache_ttl_minutes,
            enable_cache=self.config.use_cache,
        )
        
        # Builders
        self._context_builder = ContextBuilder()
        self._planner: Optional[AnalysisPlanner] = None
        self._executor: Optional[StepExecutor] = None
        
        logger.info("AnalysisAgent initialized")
    
    def _get_llm_client(self) -> "LLMClient":
        """Get or create LLM client."""
        if self._llm_client is None:
            from shared.llm import get_llm_client
            self._llm_client = get_llm_client()
        return self._llm_client
    
    def _get_planner(self) -> AnalysisPlanner:
        """Get or create planner."""
        if self._planner is None:
            self._planner = AnalysisPlanner(
                llm_client=self._get_llm_client(),
                max_tokens=self.config.planning_max_tokens,
            )
        return self._planner
    
    def _get_executor(self) -> StepExecutor:
        """Get or create executor."""
        if self._executor is None:
            self._executor = StepExecutor(
                tool_registry=self._tool_registry,
                max_retries=self.config.code_gen_max_retries,
                timeout_seconds=self.config.code_gen_timeout,
            )
        return self._executor
    
    def analyze(
        self,
        query: str,
        data_context: "DataContext",
        additional_hints: Optional[str] = None,
    ) -> AnalysisResult:
        """
        Analyze data using DataContext.
        
        Args:
            query: Natural language analysis query
            data_context: DataContext with loaded data
            additional_hints: Additional hints for the LLM
        
        Returns:
            AnalysisResult with final result and metadata
        """
        logger.info(f"🔍 Analyzing: '{query}'")
        start_time = time.time()
        
        # Phase 1: Build AnalysisContext
        logger.debug("Phase 1: Building AnalysisContext...")
        previous_results = self._result_store.get_history_for_context(limit=3)
        analysis_context = self._context_builder.build_from_data_context(
            data_context=data_context,
            additional_hints=additional_hints,
            previous_results=previous_results,
        )
        
        # Get data for execution
        runtime_data = self._extract_runtime_data(data_context)
        
        # Build input summary for caching
        input_summary = self._build_input_summary(analysis_context)
        
        # Check cache
        if self.config.use_cache:
            cached = self._result_store.get_cached(query, input_summary)
            if cached:
                logger.info("📦 Returning cached result")
                return AnalysisResult.create_cached(cached)
        
        # Execute analysis
        result = self._execute_analysis(
            query=query,
            analysis_context=analysis_context,
            runtime_data=runtime_data,
            input_summary=input_summary,
            start_time=start_time,
        )
        
        # Save result
        self._result_store.save(result)
        
        return result
    
    def analyze_dataframes(
        self,
        query: str,
        dataframes: Dict[str, "pd.DataFrame"],
        descriptions: Optional[Dict[str, str]] = None,
        additional_hints: Optional[str] = None,
    ) -> AnalysisResult:
        """
        Analyze data using raw DataFrames.
        
        Args:
            query: Natural language analysis query
            dataframes: Dict of DataFrames (e.g., {"df": signal_df, "cohort": cohort_df})
            descriptions: Descriptions for each DataFrame
            additional_hints: Additional hints for the LLM
        
        Returns:
            AnalysisResult with final result and metadata
        """
        logger.info(f"🔍 Analyzing: '{query}'")
        start_time = time.time()
        
        # Phase 1: Build AnalysisContext
        logger.debug("Phase 1: Building AnalysisContext from DataFrames...")
        previous_results = self._result_store.get_history_for_context(limit=3)
        analysis_context = self._context_builder.build_from_dataframes(
            dataframes=dataframes,
            descriptions=descriptions or {},
            additional_hints=additional_hints,
            previous_results=previous_results,
        )
        
        # Build input summary for caching
        input_summary = self._build_input_summary(analysis_context)
        
        # Check cache
        if self.config.use_cache:
            cached = self._result_store.get_cached(query, input_summary)
            if cached:
                logger.info("📦 Returning cached result")
                return AnalysisResult.create_cached(cached)
        
        # Execute analysis
        result = self._execute_analysis(
            query=query,
            analysis_context=analysis_context,
            runtime_data=dataframes,
            input_summary=input_summary,
            start_time=start_time,
        )
        
        # Save result
        self._result_store.save(result)
        
        return result
    
    def _execute_analysis(
        self,
        query: str,
        analysis_context: AnalysisContext,
        runtime_data: Dict[str, Any],
        input_summary: Dict[str, Any],
        start_time: float,
    ) -> AnalysisResult:
        """Execute the full analysis pipeline."""
        
        # Phase 2: Planning
        logger.debug("Phase 2: Planning...")
        plan_result = self._create_plan(query, analysis_context)
        
        if not plan_result.success:
            return AnalysisResult.create_error(
                query=query,
                error=f"Planning failed: {plan_result.error}",
                input_summary=input_summary,
                execution_time_ms=(time.time() - start_time) * 1000,
            )
        
        plan = plan_result.plan
        logger.info(f"📋 Plan: {plan.step_count} steps, type={plan.analysis_type}")
        
        # Validate plan
        validation_errors = plan.validate()
        if validation_errors:
            return AnalysisResult.create_error(
                query=query,
                error=f"Plan validation failed: {validation_errors}",
                plan=plan.to_dict(),
                input_summary=input_summary,
                execution_time_ms=(time.time() - start_time) * 1000,
            )
        
        # Phase 3: Execution
        logger.debug("Phase 3: Executing...")
        executor = self._get_executor()
        state = executor.execute_plan(plan, runtime_data)
        
        # Phase 4: Result Assembly
        logger.debug("Phase 4: Assembling result...")
        execution_time = (time.time() - start_time) * 1000
        
        if state.has_errors():
            return AnalysisResult.create_error(
                query=query,
                error="; ".join(state.get_errors()),
                plan=plan.to_dict(),
                step_results=[o.to_dict() for o in state.step_outputs],
                input_summary=input_summary,
                execution_time_ms=execution_time,
            )
        
        # Get final result
        final_result = state.get_final_result()
        final_output = state.step_outputs[-1] if state.step_outputs else None
        
        # Collect generated code
        generated_codes = [
            o.generated_code for o in state.step_outputs
            if o.generated_code
        ]
        
        return AnalysisResult.create_success(
            query=query,
            final_result=final_result,
            final_result_type=final_output.result_type if final_output else "any",
            plan=plan.to_dict(),
            step_results=[o.to_dict() for o in state.step_outputs],
            input_summary=input_summary,
            generated_code="\n\n".join(generated_codes) if generated_codes else None,
            execution_time_ms=execution_time,
            metadata={
                "planning_mode": "llm" if self.config.use_llm_planning else "rule",
                "step_count": plan.step_count,
                "analysis_type": plan.analysis_type,
            }
        )
    
    def _create_plan(
        self,
        query: str,
        context: AnalysisContext,
    ) -> PlanningResult:
        """Create execution plan."""
        planner = self._get_planner()
        
        if self.config.use_llm_planning:
            return planner.plan(query, context)
        else:
            return planner.plan_simple(query, context)
    
    def _extract_runtime_data(self, data_context: "DataContext") -> Dict[str, Any]:
        """Extract runtime data from DataContext."""
        data = {}
        
        # Get cohort
        cohort = data_context.get_cohort()
        if cohort is not None and not cohort.empty:
            data["cohort"] = cohort
        
        # Get merged signal data
        try:
            merged = data_context.get_merged_data()
            if merged is not None and not merged.empty:
                data["df"] = merged
        except Exception as e:
            logger.warning(f"Could not get merged data: {e}")
        
        return data
    
    def _build_input_summary(self, context: AnalysisContext) -> Dict[str, Any]:
        """Build input summary for caching."""
        return {
            "dataframes": {
                name: {
                    "shape": list(schema.shape),
                    "columns": [c.name for c in schema.columns],
                }
                for name, schema in context.data_schemas.items()
            },
            "join_keys": context.join_keys,
        }
    
    # ==========================================================================
    # Convenience Methods
    # ==========================================================================
    
    def get_recent_results(self, limit: int = 10) -> List[AnalysisResult]:
        """Get recent analysis results."""
        return self._result_store.get_recent(limit)
    
    def clear_cache(self) -> int:
        """Clear result cache."""
        return self._result_store.clear_cache()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        return {
            "result_store": self._result_store.stats(),
            "tool_count": len(self._tool_registry),
            "config": {
                "use_llm_planning": self.config.use_llm_planning,
                "use_cache": self.config.use_cache,
                "max_retries": self.config.code_gen_max_retries,
            }
        }
