# AnalysisAgent/src/tools/registry.py
"""
Tool Registry

Central registry for managing analysis tools.
Tools can be registered and looked up by name or tags.
"""

import logging
from typing import Dict, List, Optional, Type

from .base import BaseTool, ToolMetadata
from ..context.schema import ToolInfo

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central registry for analysis tools.
    
    Usage:
        registry = ToolRegistry()
        
        # Register a tool
        registry.register(MeanTool())
        
        # Get tool by name
        tool = registry.get("compute_mean")
        
        # Get tools by tag
        stats_tools = registry.get_by_tag("statistics")
        
        # Get all tool metadata (for Planner)
        tool_infos = registry.get_tool_infos()
    """
    
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
    
    def register(self, tool: BaseTool) -> None:
        """
        Register a tool.
        
        Args:
            tool: Tool instance to register
        
        Raises:
            ValueError: If tool with same name already exists
        """
        name = tool.name
        if name in self._tools:
            logger.warning(f"Tool '{name}' already registered, overwriting")
        
        self._tools[name] = tool
        logger.debug(f"Registered tool: {name}")
    
    def unregister(self, name: str) -> bool:
        """
        Unregister a tool.
        
        Args:
            name: Tool name
        
        Returns:
            True if tool was removed, False if not found
        """
        if name in self._tools:
            del self._tools[name]
            logger.debug(f"Unregistered tool: {name}")
            return True
        return False
    
    def get(self, name: str) -> Optional[BaseTool]:
        """
        Get tool by name.
        
        Args:
            name: Tool name
        
        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(name)
    
    def has(self, name: str) -> bool:
        """Check if tool exists."""
        return name in self._tools
    
    def get_by_tag(self, tag: str) -> List[BaseTool]:
        """
        Get all tools with a specific tag.
        
        Args:
            tag: Tag to filter by
        
        Returns:
            List of matching tools
        """
        return [
            tool for tool in self._tools.values()
            if tag in tool.tags
        ]
    
    def get_by_tags(self, tags: List[str], match_all: bool = False) -> List[BaseTool]:
        """
        Get tools matching tags.
        
        Args:
            tags: Tags to filter by
            match_all: If True, tool must have all tags; if False, any tag
        
        Returns:
            List of matching tools
        """
        if match_all:
            return [
                tool for tool in self._tools.values()
                if all(tag in tool.tags for tag in tags)
            ]
        else:
            return [
                tool for tool in self._tools.values()
                if any(tag in tool.tags for tag in tags)
            ]
    
    def list_all(self) -> List[BaseTool]:
        """Get all registered tools."""
        return list(self._tools.values())
    
    def list_names(self) -> List[str]:
        """Get all registered tool names."""
        return list(self._tools.keys())
    
    def get_metadata(self, name: str) -> Optional[ToolMetadata]:
        """Get metadata for a specific tool."""
        tool = self.get(name)
        return tool.metadata if tool else None
    
    def get_all_metadata(self) -> List[ToolMetadata]:
        """Get metadata for all tools."""
        return [tool.metadata for tool in self._tools.values()]
    
    def get_tool_infos(self) -> List[ToolInfo]:
        """
        Get ToolInfo list for AnalysisContext.
        
        Returns:
            List of ToolInfo objects for Planner
        """
        return [
            ToolInfo(
                name=tool.metadata.name,
                description=tool.metadata.description,
                input_schema=tool.metadata.input_schema,
                output_type=tool.metadata.output_type,
                tags=tool.metadata.tags,
            )
            for tool in self._tools.values()
        ]
    
    def find_tool_for_action(self, action: str) -> Optional[BaseTool]:
        """
        Find a tool that matches an action name.
        
        Tries exact match first, then partial match.
        
        Args:
            action: Action name from PlanStep
        
        Returns:
            Matching tool or None
        """
        # Exact match
        if action in self._tools:
            return self._tools[action]
        
        # Partial match (action contains tool name or vice versa)
        action_lower = action.lower()
        for name, tool in self._tools.items():
            if name.lower() in action_lower or action_lower in name.lower():
                return tool
        
        return None
    
    def clear(self) -> None:
        """Remove all registered tools."""
        self._tools.clear()
        logger.debug("Cleared all tools from registry")
    
    def __len__(self) -> int:
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools


# Global registry instance
_global_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """
    Get the global tool registry.
    
    Creates one if it doesn't exist.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def register_tool(tool: BaseTool) -> None:
    """Register a tool in the global registry."""
    get_tool_registry().register(tool)


def get_tool(name: str) -> Optional[BaseTool]:
    """Get a tool from the global registry."""
    return get_tool_registry().get(name)
