# AnalysisAgent/src/executor/router.py
"""
Execution Router

Decides whether to use a Tool or CodeGen for each step.
"""

import logging
from typing import Optional, Literal

from ..models.plan import PlanStep
from ..tools.registry import ToolRegistry, get_tool_registry
from ..tools.base import BaseTool

logger = logging.getLogger(__name__)


class ExecutionRouter:
    """
    Routes execution to Tool or CodeGen based on step configuration.
    
    Decision logic:
    1. If step.execution_mode == "tool" and tool exists → use Tool
    2. If step.tool_name is specified and tool exists → use Tool
    3. Otherwise → use CodeGen
    """
    
    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        """
        Args:
            tool_registry: Tool registry to use. If None, uses global registry.
        """
        self._registry = tool_registry or get_tool_registry()
    
    def route(self, step: PlanStep) -> tuple[Literal["tool", "code"], Optional[BaseTool]]:
        """
        Determine execution method for a step.
        
        Args:
            step: Plan step to route
        
        Returns:
            Tuple of (execution_mode, tool or None)
        """
        # If step explicitly specifies tool execution
        if step.execution_mode == "tool":
            tool = self._find_tool(step)
            if tool:
                logger.debug(f"Step {step.id}: Routing to tool '{tool.name}'")
                return ("tool", tool)
            else:
                logger.warning(f"Step {step.id}: Tool mode requested but no tool found, falling back to code")
                return ("code", None)
        
        # If step has a tool_name hint
        if step.tool_name:
            tool = self._registry.get(step.tool_name)
            if tool:
                logger.debug(f"Step {step.id}: Tool '{step.tool_name}' specified and found")
                return ("tool", tool)
            else:
                logger.debug(f"Step {step.id}: Tool '{step.tool_name}' not found, using code")
        
        # Default: code generation
        logger.debug(f"Step {step.id}: Routing to code generation")
        return ("code", None)
    
    def _find_tool(self, step: PlanStep) -> Optional[BaseTool]:
        """Find a tool for the step."""
        # First try explicit tool name
        if step.tool_name:
            tool = self._registry.get(step.tool_name)
            if tool:
                return tool
        
        # Try to match by action name
        tool = self._registry.find_tool_for_action(step.action)
        if tool:
            return tool
        
        return None
    
    def can_use_tool(self, step: PlanStep) -> bool:
        """Check if a tool can be used for this step."""
        return self._find_tool(step) is not None
    
    def get_recommended_mode(self, step: PlanStep) -> Literal["tool", "code"]:
        """
        Get recommended execution mode.
        
        Prefers Tool if available, otherwise Code.
        """
        if self.can_use_tool(step):
            return "tool"
        return "code"
    
    def explain_routing(self, step: PlanStep) -> str:
        """Get explanation for routing decision."""
        mode, tool = self.route(step)
        
        if mode == "tool":
            return f"Using tool '{tool.name}': {tool.description}"
        else:
            if step.code_hint:
                return f"Using code generation with hint: {step.code_hint[:50]}..."
            else:
                return "Using code generation (no tool available)"
