"""Tool registry for managing available tools."""

import asyncio
import inspect
import json
from typing import Any

from ..providers.base import ToolDefinition, ToolCall, ToolResult


class ToolRegistry:
    """Registry for managing and executing tools."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def register_all(self, tools: list[ToolDefinition]) -> None:
        """Register multiple tools."""
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> ToolDefinition | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """Get all registered tools."""
        return list(self._tools.values())

    def _process_result(self, tool_call: ToolCall, result: Any) -> ToolResult:
        """Process a tool result into a ToolResult object."""
        # Ensure result is JSON-serializable
        if isinstance(result, dict):
            content = json.dumps(result, indent=2)
            is_error = "error" in result
        else:
            content = str(result)
            is_error = False

        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            content=content,
            is_error=is_error,
        )

    def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call synchronously.

        Note: For async handlers, use execute_async() instead.
        This method will raise an error if the handler is async.

        Args:
            tool_call: The tool call to execute

        Returns:
            ToolResult with the execution output
        """
        tool = self._tools.get(tool_call.name)

        if tool is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=json.dumps({"error": f"Unknown tool: {tool_call.name}"}),
                is_error=True,
            )

        try:
            result = tool.handler(**tool_call.arguments)

            # Check if result is a coroutine (async handler)
            if asyncio.iscoroutine(result):
                # Close the coroutine to avoid warnings
                result.close()
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=json.dumps({"error": f"Tool '{tool_call.name}' is async. Use execute_async() instead."}),
                    is_error=True,
                )

            return self._process_result(tool_call, result)

        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=json.dumps({"error": f"Tool execution failed: {e}"}),
                is_error=True,
            )

    async def execute_async(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call asynchronously.

        Supports both sync and async tool handlers.

        Args:
            tool_call: The tool call to execute

        Returns:
            ToolResult with the execution output
        """
        tool = self._tools.get(tool_call.name)

        if tool is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=json.dumps({"error": f"Unknown tool: {tool_call.name}"}),
                is_error=True,
            )

        try:
            result = tool.handler(**tool_call.arguments)

            # If the handler is async, await it
            if asyncio.iscoroutine(result):
                result = await result

            return self._process_result(tool_call, result)

        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=json.dumps({"error": f"Tool execution failed: {e}"}),
                is_error=True,
            )
