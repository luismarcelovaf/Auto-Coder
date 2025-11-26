"""File system tools for reading, writing, and editing files."""

import os
from pathlib import Path
from typing import Any

from ..providers.base import ToolDefinition


def _validate_path(path: str, root_dir: str | None = None) -> Path:
    """Validate and resolve a file path.

    Args:
        path: The path to validate
        root_dir: Optional root directory to restrict access to

    Returns:
        Resolved Path object

    Raises:
        PermissionError: If path is outside root_dir
        FileNotFoundError: If path doesn't exist (for read operations)
    """
    resolved = Path(path).resolve()

    if root_dir:
        root = Path(root_dir).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise PermissionError(f"Access denied: {path} is outside allowed directory")

    return resolved


def read_file(file_path: str, root_dir: str | None = None) -> dict[str, Any]:
    """Read the contents of a file.

    Args:
        file_path: Absolute or relative path to the file
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'content' or 'error' key
    """
    try:
        path = _validate_path(file_path, root_dir)

        if not path.exists():
            return {"error": f"File not found: {file_path}"}

        if not path.is_file():
            return {"error": f"Not a file: {file_path}"}

        content = path.read_text(encoding="utf-8")

        # Add line numbers for better context
        # Preserve exact whitespace - tabs and spaces are kept as-is
        lines = content.split("\n")
        numbered_lines = [f"{i+1:4d} | {line}" for i, line in enumerate(lines)]

        return {
            "content": "\n".join(numbered_lines),
            "raw_content": content,  # Include raw content for exact matching
            "path": str(path),
            "lines": len(lines),
        }
    except PermissionError as e:
        return {"error": str(e)}
    except UnicodeDecodeError:
        return {"error": f"Cannot read binary file: {file_path}"}
    except Exception as e:
        return {"error": f"Error reading file: {e}"}


def write_file(
    file_path: str, content: str, root_dir: str | None = None
) -> dict[str, Any]:
    """Write content to a file, creating it if necessary.

    Args:
        file_path: Path to the file
        content: Content to write
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'success' or 'error' key
    """
    try:
        path = _validate_path(file_path, root_dir)

        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "path": str(path),
            "bytes_written": len(content.encode("utf-8")),
        }
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Error writing file: {e}"}


def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    root_dir: str | None = None,
) -> dict[str, Any]:
    """Edit a file by replacing an exact string match.

    Args:
        file_path: Path to the file
        old_string: Exact string to find and replace (including whitespace)
        new_string: Replacement string
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'success' or 'error' key
    """
    try:
        path = _validate_path(file_path, root_dir)

        if not path.exists():
            return {"error": f"File not found: {file_path}"}

        content = path.read_text(encoding="utf-8")

        # Check that old_string exists and is unique
        count = content.count(old_string)
        if count == 0:
            # Provide helpful debugging info
            old_repr = repr(old_string[:200]) if len(old_string) > 200 else repr(old_string)
            return {
                "error": f"String not found in file. Make sure whitespace (tabs, spaces, newlines) matches exactly. Searched for: {old_repr}"
            }
        if count > 1:
            return {
                "error": f"String appears {count} times in file. Provide more context to make it unique."
            }

        new_content = content.replace(old_string, new_string, 1)
        path.write_text(new_content, encoding="utf-8")

        return {
            "success": True,
            "path": str(path),
            "old_length": len(old_string),
            "new_length": len(new_string),
        }
    except PermissionError as e:
        return {"error": str(e)}
    except UnicodeDecodeError:
        return {"error": f"Cannot edit binary file: {file_path}"}
    except Exception as e:
        return {"error": f"Error editing file: {e}"}


def list_directory(
    dir_path: str = ".", root_dir: str | None = None
) -> dict[str, Any]:
    """List contents of a directory.

    Args:
        dir_path: Path to the directory
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'entries' or 'error' key
    """
    try:
        path = _validate_path(dir_path, root_dir)

        if not path.exists():
            return {"error": f"Directory not found: {dir_path}"}

        if not path.is_dir():
            return {"error": f"Not a directory: {dir_path}"}

        entries = []
        for entry in sorted(path.iterdir()):
            entry_type = "dir" if entry.is_dir() else "file"
            size = entry.stat().st_size if entry.is_file() else None
            entries.append({
                "name": entry.name,
                "type": entry_type,
                "size": size,
            })

        return {
            "path": str(path),
            "entries": entries,
            "count": len(entries),
        }
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Error listing directory: {e}"}


def tree_directory(
    dir_path: str = ".",
    max_depth: int = 10,
    root_dir: str | None = None,
) -> dict[str, Any]:
    """Show directory structure as a tree.

    Args:
        dir_path: Path to the directory
        max_depth: Maximum depth to traverse (default 5)
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'tree' string or 'error' key
    """
    # Directories to skip
    skip_dirs = {
        ".git", ".svn", ".hg", ".bzr",
        "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        "venv", ".venv", "env", ".env", "virtualenv",
        "dist", "build", "target", "out", "bin", "obj",
        ".idea", ".vscode", ".vs",
        "coverage", ".coverage", "htmlcov", ".nyc_output",
        ".tox", ".nox",
        ".next", ".nuxt", ".output",
        ".cache", ".parcel-cache",
    }

    try:
        path = _validate_path(dir_path, root_dir)

        if not path.exists():
            return {"error": f"Directory not found: {dir_path}"}

        if not path.is_dir():
            return {"error": f"Not a directory: {dir_path}"}

        lines = [f"{path.name}/"]

        def add_entries(current_path: Path, prefix: str = "", depth: int = 0):
            if depth >= max_depth:
                return

            try:
                items = sorted(current_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            except PermissionError:
                return

            # Filter out skipped directories
            filtered_items = []
            for item in items:
                if item.is_dir() and item.name.lower() in skip_dirs:
                    continue
                if item.name.startswith(".") and item.is_dir():
                    continue
                filtered_items.append(item)

            for i, item in enumerate(filtered_items):
                is_last = i == len(filtered_items) - 1
                connector = "└── " if is_last else "├── "

                if item.is_dir():
                    lines.append(f"{prefix}{connector}{item.name}/")
                    extension = "    " if is_last else "│   "
                    add_entries(item, prefix + extension, depth + 1)
                else:
                    lines.append(f"{prefix}{connector}{item.name}")

        add_entries(path)

        return {
            "path": str(path),
            "tree": "\n".join(lines),
            "depth": max_depth,
        }
    except PermissionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Error creating directory tree: {e}"}


def _make_read_file_handler(root_dir: str | None):
    """Create a handler for read_file that ignores extra kwargs."""
    def handler(file_path: str, **kwargs) -> dict[str, Any]:
        return read_file(file_path, root_dir)
    return handler


def _make_write_file_handler(root_dir: str | None):
    """Create a handler for write_file that ignores extra kwargs."""
    def handler(file_path: str, content: str, **kwargs) -> dict[str, Any]:
        return write_file(file_path, content, root_dir)
    return handler


def _make_edit_file_handler(root_dir: str | None):
    """Create a handler for edit_file that ignores extra kwargs."""
    def handler(file_path: str, old_string: str, new_string: str, **kwargs) -> dict[str, Any]:
        return edit_file(file_path, old_string, new_string, root_dir)
    return handler


def _make_list_directory_handler(root_dir: str | None):
    """Create a handler for list_directory that ignores extra kwargs."""
    def handler(dir_path: str = ".", **kwargs) -> dict[str, Any]:
        return list_directory(dir_path, root_dir)
    return handler


def _make_tree_directory_handler(root_dir: str | None):
    """Create a handler for tree_directory that ignores extra kwargs."""
    def handler(dir_path: str = ".", max_depth: int = 10, **kwargs) -> dict[str, Any]:
        return tree_directory(dir_path, max_depth, root_dir)
    return handler


def get_file_tools(root_dir: str | None = None) -> list[ToolDefinition]:
    """Get file system tool definitions.

    Args:
        root_dir: Optional root directory to restrict file access

    Returns:
        List of ToolDefinition objects
    """
    return [
        ToolDefinition(
            name="read_file",
            description=(
                "Read the contents of a file. Returns the file content with line numbers. "
                "The content preserves exact whitespace (tabs, spaces) for accurate editing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to read",
                    },
                },
                "required": ["file_path"],
            },
            handler=_make_read_file_handler(root_dir),
        ),
        ToolDefinition(
            name="write_file",
            description=(
                "Write content to a file. Creates the file if it doesn't exist, or overwrites if it does. "
                "Use exact whitespace (tabs/spaces) as needed for proper indentation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to write",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file (preserve exact indentation)",
                    },
                },
                "required": ["file_path", "content"],
            },
            handler=_make_write_file_handler(root_dir),
        ),
        ToolDefinition(
            name="edit_file",
            description=(
                "Edit a file by replacing an exact string match. The old_string must appear exactly once in the file. "
                "IMPORTANT: old_string must match EXACTLY including all whitespace (tabs, spaces, newlines). "
                "Copy the exact text from read_file output, preserving all indentation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to edit",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The exact string to find and replace, including all whitespace (tabs, spaces, newlines)",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The string to replace it with, with proper indentation",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
            handler=_make_edit_file_handler(root_dir),
        ),
        ToolDefinition(
            name="list_directory",
            description="List the immediate contents of a directory, showing files and subdirectories (non-recursive).",
            parameters={
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "The path to the directory to list (defaults to current directory)",
                        "default": ".",
                    },
                },
                "required": [],
            },
            handler=_make_list_directory_handler(root_dir),
        ),
        ToolDefinition(
            name="tree_directory",
            description=(
                "Show the directory structure as a tree, recursively displaying files and folders. "
                "Useful for understanding project layout. Automatically skips common non-essential "
                "directories like node_modules, __pycache__, .git, venv, etc."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "The path to the directory to show as tree (defaults to current directory)",
                        "default": ".",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum depth to traverse (default 10)",
                        "default": 10,
                    },
                },
                "required": [],
            },
            handler=_make_tree_directory_handler(root_dir),
        ),
    ]
