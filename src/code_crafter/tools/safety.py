"""Safety utilities for checking dangerous operations."""

import os
from typing import Callable

# Global confirmation callback - set by REPL or other UI
_confirm_callback: Callable[[str], bool] | None = None


def set_confirmation_callback(callback: Callable[[str], bool] | None) -> None:
    """Set the callback function for confirming dangerous operations.

    Args:
        callback: Function that takes a prompt string and returns True/False,
                  or None to disable confirmation (auto-deny dangerous operations)
    """
    global _confirm_callback
    _confirm_callback = callback


def get_confirmation_callback() -> Callable[[str], bool] | None:
    """Get the current confirmation callback."""
    return _confirm_callback


def is_path_inside_directory(path: str, working_dir: str) -> bool:
    """Check if a path resolves to inside the working directory.

    Args:
        path: The path to check (can be absolute or relative)
        working_dir: The working directory to check against

    Returns:
        True if the path is inside working_dir, False otherwise
    """
    try:
        # Expand ~ to home directory
        if path.startswith("~"):
            path = os.path.expanduser(path)

        # Resolve to absolute path
        if os.path.isabs(path):
            resolved = os.path.normpath(path)
        else:
            resolved = os.path.normpath(os.path.join(working_dir, path))

        # Normalize the working directory
        working_dir_resolved = os.path.normpath(os.path.abspath(working_dir))

        # Check if resolved path starts with working directory
        # Add separator to avoid /home/user matching /home/username
        return resolved.startswith(working_dir_resolved + os.sep) or resolved == working_dir_resolved
    except Exception:
        # If we can't resolve, assume it's outside for safety
        return False


def check_path_safety(
    path: str,
    working_dir: str | None = None,
    operation: str = "access",
) -> tuple[bool, str | None]:
    """Check if a file path operation is safe (inside working directory).

    Args:
        path: The path to check
        working_dir: The working directory to check against (defaults to cwd)
        operation: Description of the operation (e.g., "read", "write", "delete")

    Returns:
        Tuple of (is_dangerous, description) where description explains the issue
    """
    if working_dir is None:
        working_dir = os.getcwd()

    if not is_path_inside_directory(path, working_dir):
        return True, f"attempts to {operation} path outside working directory: {path}"

    return False, None


def confirm_dangerous_operation(
    prompt: str,
    auto_deny: bool = True,
) -> tuple[bool, str | None]:
    """Request user confirmation for a dangerous operation.

    Args:
        prompt: The confirmation prompt to display
        auto_deny: If True and no callback is set, deny the operation.
                   If False and no callback is set, allow it.

    Returns:
        Tuple of (confirmed, error_message)
        - If confirmed: (True, None)
        - If denied: (False, reason string)
    """
    callback = get_confirmation_callback()

    if callback is None:
        if auto_deny:
            return False, "No confirmation callback available"
        else:
            return True, None

    try:
        confirmed = callback(prompt)
        if confirmed:
            return True, None
        else:
            return False, "Denied by user"
    except Exception as e:
        return False, f"Confirmation failed: {e}"
