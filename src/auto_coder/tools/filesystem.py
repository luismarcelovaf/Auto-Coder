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
        lines = content.split("\n")
        numbered_lines = [f"{i+1:4d} | {line}" for i, line in enumerate(lines)]

        return {
            "content": "\n".join(numbered_lines),
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
        old_string: Exact string to find and replace
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
            return {"error": f"String not found in file: {repr(old_string[:100])}"}
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
            description="Read the contents of a file. Returns the file content with line numbers.",
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
            handler=lambda file_path: read_file(file_path, root_dir),
        ),
        ToolDefinition(
            name="write_file",
            description="Write content to a file. Creates the file if it doesn't exist, or overwrites if it does.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to write",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file",
                    },
                },
                "required": ["file_path", "content"],
            },
            handler=lambda file_path, content: write_file(file_path, content, root_dir),
        ),
        ToolDefinition(
            name="edit_file",
            description="Edit a file by replacing an exact string match. The old_string must appear exactly once in the file.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to edit",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The exact string to find and replace (must be unique in the file)",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The string to replace it with",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
            handler=lambda file_path, old_string, new_string: edit_file(
                file_path, old_string, new_string, root_dir
            ),
        ),
        ToolDefinition(
            name="list_directory",
            description="List the contents of a directory, showing files and subdirectories.",
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
            handler=lambda dir_path=".": list_directory(dir_path, root_dir),
        ),
    ]
