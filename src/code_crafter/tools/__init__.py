"""Tool implementations for code-crafter."""

from .filesystem import (
    read_file,
    write_file,
    edit_file,
    list_directory,
    get_file_tools,
)
from .shell import (
    run_command,
    get_shell_tools,
    check_dangerous_command,
)
from .safety import (
    set_confirmation_callback,
    get_confirmation_callback,
    check_path_safety,
    is_path_inside_directory,
    confirm_dangerous_operation,
)
from .registry import ToolRegistry

__all__ = [
    "read_file",
    "write_file",
    "edit_file",
    "list_directory",
    "run_command",
    "get_file_tools",
    "get_shell_tools",
    "set_confirmation_callback",
    "get_confirmation_callback",
    "check_path_safety",
    "is_path_inside_directory",
    "confirm_dangerous_operation",
    "check_dangerous_command",
    "ToolRegistry",
]
