"""Shell command execution tools."""

import asyncio
import os
import subprocess
import sys
from typing import Any

from ..providers.base import ToolDefinition


async def run_command(
    command: str,
    working_dir: str | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Execute a shell command.

    Args:
        command: The command to execute
        working_dir: Working directory for the command
        timeout: Maximum execution time in seconds

    Returns:
        Dict with stdout, stderr, and return_code
    """
    try:
        cwd = working_dir or os.getcwd()

        # Determine shell based on platform
        if sys.platform == "win32":
            shell_cmd = ["cmd", "/c", command]
        else:
            shell_cmd = ["bash", "-c", command]

        process = await asyncio.create_subprocess_exec(
            *shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return {
                "error": f"Command timed out after {timeout} seconds",
                "return_code": -1,
            }

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        # Truncate very long outputs
        max_length = 50000
        if len(stdout_str) > max_length:
            stdout_str = stdout_str[:max_length] + f"\n... (truncated, {len(stdout_str)} total bytes)"
        if len(stderr_str) > max_length:
            stderr_str = stderr_str[:max_length] + f"\n... (truncated, {len(stderr_str)} total bytes)"

        return {
            "stdout": stdout_str,
            "stderr": stderr_str,
            "return_code": process.returncode,
            "command": command,
            "cwd": cwd,
        }

    except FileNotFoundError:
        return {"error": f"Shell not found", "return_code": -1}
    except Exception as e:
        return {"error": f"Error executing command: {e}", "return_code": -1}


def run_command_sync(
    command: str,
    working_dir: str | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Synchronous wrapper for run_command."""
    return asyncio.run(run_command(command, working_dir, timeout))


def get_shell_tools(working_dir: str | None = None) -> list[ToolDefinition]:
    """Get shell command tool definitions.

    Args:
        working_dir: Default working directory for commands

    Returns:
        List of ToolDefinition objects
    """
    return [
        ToolDefinition(
            name="run_command",
            description=(
                "Execute a shell command and return its output. "
                "Use this for running build commands, tests, git operations, etc. "
                "The command runs in a shell (bash on Unix, cmd on Windows)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory for the command (optional)",
                    },
                },
                "required": ["command"],
            },
            handler=lambda command, working_dir=working_dir: asyncio.run(
                run_command(command, working_dir)
            ),
        ),
    ]
