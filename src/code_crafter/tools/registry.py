"""Tool registry for managing available tools."""

import asyncio
import inspect
import json
import re
from typing import Any

from ..providers.base import ToolDefinition, ToolCall, ToolResult


# Mapping of common parameter name variations to canonical names
PARAMETER_ALIASES: dict[str, str] = {
    # Camel case to snake_case
    "filePath": "file_path",
    "fileName": "file_name",
    "dirPath": "dir_path",
    "oldString": "old_string",
    "newString": "new_string",
    "startLine": "start_line",
    "endLine": "end_line",
    "maxDepth": "max_depth",
    "includeContents": "include_contents",
    "workingDir": "working_dir",
    "replaceAll": "replace_all",

    # Other common variations
    "path": "file_path",
    "filepath": "file_path",
    "filename": "file_name",
    "directory": "dir_path",
    "old": "old_string",
    "new": "new_string",
    "search": "pattern",
    "query": "pattern",
    "cmd": "command",
}


def _normalize_tool_name(name: str) -> str:
    """Normalize tool name to lowercase with underscores.

    Handles:
    - Capitalized names (Write_file -> write_file)
    - PascalCase (WriteFile -> write_file)
    - Mixed case (WRITE_FILE -> write_file)

    Args:
        name: The tool name to normalize

    Returns:
        Normalized tool name in lowercase with underscores
    """
    # Handle PascalCase by inserting underscores before uppercase letters
    # e.g., WriteFile -> Write_File -> write_file
    normalized = re.sub(r'(?<!^)(?<!_)([A-Z])', r'_\1', name)

    # Lowercase everything
    normalized = normalized.lower()

    # Remove any double underscores that might have been created
    normalized = re.sub(r'_+', '_', normalized)

    # Remove leading/trailing underscores
    normalized = normalized.strip('_')

    return normalized


def _normalize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Normalize argument names to canonical snake_case.

    Handles common variations like camelCase, different naming conventions, etc.

    Args:
        arguments: The original arguments dict

    Returns:
        New dict with normalized parameter names
    """
    normalized: dict[str, Any] = {}

    for key, value in arguments.items():
        # First, check if this exact key has an alias
        canonical_key = PARAMETER_ALIASES.get(key)

        if canonical_key is None:
            # Try lowercase version
            canonical_key = PARAMETER_ALIASES.get(key.lower())

        if canonical_key is None:
            # No alias found, use the original key (lowercased and snake_cased)
            # Convert camelCase to snake_case
            canonical_key = re.sub(r'(?<!^)(?<!_)([A-Z])', r'_\1', key).lower()

        normalized[canonical_key] = value

    return normalized


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
        Normalizes tool names and argument names for compatibility with
        models that may use different naming conventions (camelCase, PascalCase, etc.).

        Args:
            tool_call: The tool call to execute

        Returns:
            ToolResult with the execution output
        """
        # Normalize tool name to handle variations like WriteFile, Write_File, etc.
        normalized_name = _normalize_tool_name(tool_call.name)
        tool = self._tools.get(normalized_name)

        # If not found with normalized name, try the original name as fallback
        if tool is None:
            tool = self._tools.get(tool_call.name)

        if tool is None:
            # Provide helpful error with available tools
            available = ", ".join(sorted(self._tools.keys()))
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=json.dumps({
                    "error": f"Unknown tool: '{tool_call.name}' (normalized: '{normalized_name}'). Available tools: {available}"
                }),
                is_error=True,
            )

        try:
            # Normalize argument names to handle camelCase variations
            normalized_args = _normalize_arguments(tool_call.arguments)

            result = tool.handler(**normalized_args)

            # If the handler is async, await it
            if asyncio.iscoroutine(result):
                result = await result

            return self._process_result(tool_call, result)

        except TypeError as e:
            # Handle missing/extra arguments more gracefully
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=json.dumps({
                    "error": f"Invalid arguments for '{tool_call.name}': {e}",
                    "provided_arguments": list(tool_call.arguments.keys()),
                    "hint": "Check parameter names - use snake_case (e.g., file_path, old_string)"
                }),
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                content=json.dumps({"error": f"Tool execution failed: {e}"}),
                is_error=True,
            )
