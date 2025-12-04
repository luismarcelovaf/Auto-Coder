"""Shell command execution tools."""

import asyncio
import os
import re
import subprocess
import sys
from typing import Any

from ..providers.base import ToolDefinition
from .safety import (
    is_path_inside_directory,
    get_confirmation_callback,
    set_confirmation_callback,
    confirm_dangerous_operation,
)


# Patterns for dangerous commands that require user confirmation
# Each tuple contains (compiled regex, description of the danger)
DANGEROUS_COMMAND_PATTERNS: list[tuple[re.Pattern, str]] = [
    # File/directory deletion
    (re.compile(r'\brm\s+', re.IGNORECASE), "removes files/directories"),
    (re.compile(r'\brm\b.*-.*r', re.IGNORECASE), "recursively removes files/directories"),
    (re.compile(r'\brmdir\s+', re.IGNORECASE), "removes directories"),
    (re.compile(r'\bdel\s+', re.IGNORECASE), "deletes files (Windows)"),
    (re.compile(r'\brd\s+', re.IGNORECASE), "removes directories (Windows)"),
    (re.compile(r'\brd\b.*\/s', re.IGNORECASE), "recursively removes directories (Windows)"),

    # Disk/partition operations
    (re.compile(r'\bmkfs\b', re.IGNORECASE), "formats filesystem"),
    (re.compile(r'\bfdisk\b', re.IGNORECASE), "modifies disk partitions"),
    (re.compile(r'\bdd\s+', re.IGNORECASE), "low-level disk copy (can overwrite data)"),
    (re.compile(r'\bformat\s+', re.IGNORECASE), "formats drive (Windows)"),

    # Permission/ownership changes
    (re.compile(r'\bchmod\s+.*777', re.IGNORECASE), "sets world-writable permissions"),
    (re.compile(r'\bchown\s+', re.IGNORECASE), "changes file ownership"),

    # System modification
    (re.compile(r'\bsudo\s+', re.IGNORECASE), "runs with elevated privileges"),
    (re.compile(r'\bsu\s+', re.IGNORECASE), "switches user"),
    (re.compile(r'>\s*/dev/sd[a-z]', re.IGNORECASE), "writes directly to disk device"),
    (re.compile(r'\bmv\s+.*\s+/dev/null', re.IGNORECASE), "moves files to /dev/null"),

    # Network operations that could be dangerous
    (re.compile(r'\bcurl\b.*\|\s*(ba)?sh', re.IGNORECASE), "pipes remote content to shell"),
    (re.compile(r'\bwget\b.*\|\s*(ba)?sh', re.IGNORECASE), "pipes remote content to shell"),

    # Git destructive operations
    (re.compile(r'\bgit\s+push\b.*--force', re.IGNORECASE), "force pushes (can overwrite history)"),
    (re.compile(r'\bgit\s+push\b.*-f\b', re.IGNORECASE), "force pushes (can overwrite history)"),
    (re.compile(r'\bgit\s+reset\b.*--hard', re.IGNORECASE), "hard reset (discards changes)"),
    (re.compile(r'\bgit\s+clean\b.*-fd', re.IGNORECASE), "removes untracked files and directories"),

    # Database operations
    (re.compile(r'\bDROP\s+(DATABASE|TABLE|SCHEMA)\b', re.IGNORECASE), "drops database objects"),
    (re.compile(r'\bTRUNCATE\s+', re.IGNORECASE), "truncates table data"),
    (re.compile(r'\bDELETE\s+FROM\b(?!.*WHERE)', re.IGNORECASE), "deletes all rows (no WHERE clause)"),

    # Kill operations
    (re.compile(r'\bkill\s+-9\s+', re.IGNORECASE), "force kills process"),
    (re.compile(r'\bkillall\s+', re.IGNORECASE), "kills processes by name"),
    (re.compile(r'\bpkill\s+', re.IGNORECASE), "kills processes by pattern"),
    (re.compile(r'\btaskkill\s+', re.IGNORECASE), "kills processes (Windows)"),

    # Shutdown/reboot
    (re.compile(r'\bshutdown\b', re.IGNORECASE), "shuts down system"),
    (re.compile(r'\breboot\b', re.IGNORECASE), "reboots system"),
    (re.compile(r'\binit\s+[06]\b', re.IGNORECASE), "changes runlevel (shutdown/reboot)"),
]

# Regex patterns to extract potential file paths from commands
PATH_EXTRACTION_PATTERNS: list[re.Pattern] = [
    # Absolute Unix paths (starting with /)
    re.compile(r'(?:^|\s|["\'])(/[a-zA-Z0-9_\-./\\]+)'),

    # Home directory paths (starting with ~)
    re.compile(r'(?:^|\s|["\'])(~[a-zA-Z0-9_\-./\\]*)'),

    # Parent directory traversal (../ or ..\)
    re.compile(r'(?:^|\s|["\'])(\.\.[/\\][a-zA-Z0-9_\-./\\]*)'),

    # Absolute Windows paths (e.g., C:\, D:\, etc.)
    re.compile(r'(?:^|\s|["\'])([A-Za-z]:[/\\][a-zA-Z0-9_\-./\\]*)'),

    # UNC paths (\\server\share)
    re.compile(r'(?:^|\s|["\'])(\\\\[a-zA-Z0-9_\-./\\]+)'),
]

# Commands that are safe even with outside paths (read-only or special)
SAFE_OUTSIDE_PATH_COMMANDS: list[re.Pattern] = [
    re.compile(r'^\s*cd\s+', re.IGNORECASE),  # cd is handled by shell, doesn't affect our cwd
    re.compile(r'^\s*echo\s+', re.IGNORECASE),  # echo just prints
    re.compile(r'^\s*which\s+', re.IGNORECASE),  # which finds executables
    re.compile(r'^\s*where\s+', re.IGNORECASE),  # where (Windows equivalent)
    re.compile(r'^\s*type\s+', re.IGNORECASE),  # type shows command type
    re.compile(r'^\s*git\s+clone\s+', re.IGNORECASE),  # git clone needs external URLs
    re.compile(r'^\s*git\s+remote\s+', re.IGNORECASE),  # git remote operations
    re.compile(r'^\s*git\s+fetch\s+', re.IGNORECASE),  # git fetch
    re.compile(r'^\s*git\s+pull\s+', re.IGNORECASE),  # git pull
    re.compile(r'^\s*git\s+push\s+', re.IGNORECASE),  # git push (without --force, which is caught separately)
    re.compile(r'^\s*pip\s+install\s+', re.IGNORECASE),  # pip install
    re.compile(r'^\s*npm\s+install\s+', re.IGNORECASE),  # npm install
    re.compile(r'^\s*yarn\s+add\s+', re.IGNORECASE),  # yarn add
    re.compile(r'^\s*cargo\s+', re.IGNORECASE),  # cargo commands
]


def _is_safe_outside_path_command(command: str) -> bool:
    """Check if a command is safe to use with outside paths."""
    for pattern in SAFE_OUTSIDE_PATH_COMMANDS:
        if pattern.match(command):
            return True
    return False


def _check_outside_directory(command: str, working_dir: str | None = None) -> tuple[bool, str | None]:
    """Check if a command references paths outside the current directory.

    Args:
        command: The command to check
        working_dir: The working directory to check against (defaults to cwd)

    Returns:
        Tuple of (is_outside, description) where description explains the path found
    """
    # Skip check for safe commands
    if _is_safe_outside_path_command(command):
        return False, None

    if working_dir is None:
        working_dir = os.getcwd()

    # Extract all potential paths and check each one
    for pattern in PATH_EXTRACTION_PATTERNS:
        for match in pattern.finditer(command):
            path_found = match.group(1)

            # Check if this path is inside the working directory (use shared function)
            if not is_path_inside_directory(path_found, working_dir):
                return True, f"accesses path outside working directory: {path_found}"

    return False, None


def check_dangerous_command(command: str, working_dir: str | None = None) -> tuple[bool, str | None]:
    """Check if a command matches any dangerous patterns.

    Args:
        command: The command to check
        working_dir: The working directory to check path access against (defaults to cwd)

    Returns:
        Tuple of (is_dangerous, description) where description explains the danger
    """
    # First check for explicitly dangerous commands
    for pattern, description in DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(command):
            return True, description

    # Then check for paths outside current directory
    is_outside, outside_description = _check_outside_directory(command, working_dir)
    if is_outside:
        return True, outside_description

    return False, None


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

        # Check for dangerous commands (pass working dir for path checks)
        is_dangerous, danger_description = check_dangerous_command(command, cwd)
        if is_dangerous:
            # Ask for confirmation using shared utility
            prompt = f"⚠️  DANGEROUS COMMAND DETECTED ⚠️\n\nCommand: {command}\nReason: {danger_description}\n\nExecute this command?"
            confirmed, error = confirm_dangerous_operation(prompt, auto_deny=True)

            if not confirmed:
                return {
                    "status": "DENIED",
                    "error": f"Command blocked: {danger_description}. {error or ''}".strip(),
                    "command": command,
                    "return_code": -1,
                }

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
                "status": "FAILED",
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

        # Determine success/failure based on return code
        if process.returncode == 0:
            return {
                "status": "SUCCESS",
                "stdout": stdout_str,
                "stderr": stderr_str,
                "return_code": process.returncode,
                "command": command,
                "cwd": cwd,
            }
        else:
            return {
                "status": "FAILED",
                "error": f"Command exited with code {process.returncode}",
                "stdout": stdout_str,
                "stderr": stderr_str,
                "return_code": process.returncode,
                "command": command,
                "cwd": cwd,
            }

    except FileNotFoundError:
        return {"status": "FAILED", "error": "Shell not found", "return_code": -1}
    except Exception as e:
        return {"status": "FAILED", "error": f"Error executing command: {e}", "return_code": -1}


def _make_run_command_handler(default_working_dir: str | None):
    """Create an async handler for run_command."""
    async def handler(command: str, working_dir: str | None = None, **kwargs) -> dict[str, Any]:
        # Use provided working_dir or fall back to default
        effective_dir = working_dir or default_working_dir
        return await run_command(command, effective_dir)
    return handler


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
            description="""\
Execute a shell command and return its output.

WHEN TO USE:
- Running build commands (npm build, cargo build, make)
- Running tests (pytest, npm test, cargo test)
- Git operations (git status, git add, git commit)
- Installing dependencies (npm install, pip install)
- Any shell/terminal operation

PARAMETERS:
- command: The shell command to execute
- working_dir: Optional working directory (default: project root)

OUTPUT:
- stdout: Standard output from the command
- stderr: Standard error from the command
- return_code: Exit code (0 = success)

BEHAVIOR:
- Uses bash on Unix, cmd on Windows
- Times out after 120 seconds
- Truncates very long output (>50000 chars)

DANGEROUS COMMANDS (require user confirmation):
- rm, del (deletion)
- sudo, su (elevated privileges)
- git push --force (destructive git ops)
- Commands accessing paths outside working directory

EXAMPLES:
run_command(command="git status")
run_command(command="npm install")
run_command(command="python -m pytest tests/")
run_command(command="ls -la", working_dir="src")
""",
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
            handler=_make_run_command_handler(working_dir),
        ),
    ]
