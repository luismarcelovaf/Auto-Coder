"""File system tools for reading, writing, and editing files."""

import os
from pathlib import Path
from typing import Any

from ..providers.base import ToolDefinition
from .safety import (
    check_path_safety,
    confirm_dangerous_operation,
)
from .edit_strategies import apply_edit


class OutsideWorkingDirectoryError(Exception):
    """Raised when an operation targets a path outside the working directory and is denied."""
    pass


def _validate_path(path: str, root_dir: str | None = None, operation: str = "access") -> Path:
    """Validate and resolve a file path, with confirmation for paths outside working directory.

    Args:
        path: The path to validate
        root_dir: Optional root directory to check access against
        operation: Description of the operation (e.g., "read", "write", "delete")

    Returns:
        Resolved Path object

    Raises:
        OutsideWorkingDirectoryError: If path is outside root_dir and user denies access
        PermissionError: If path access is denied for other reasons
    """
    resolved = Path(path).resolve()

    if root_dir:
        # Check if path is outside the working directory
        is_dangerous, description = check_path_safety(path, root_dir, operation)

        if is_dangerous:
            # Ask for confirmation
            prompt = (
                f"⚠️  OUTSIDE WORKING DIRECTORY ⚠️\n\n"
                f"Operation: {operation}\n"
                f"Path: {path}\n"
                f"Resolved: {resolved}\n"
                f"Working directory: {root_dir}\n\n"
                f"Allow this operation?"
            )
            confirmed, error = confirm_dangerous_operation(prompt, auto_deny=True)

            if not confirmed:
                raise OutsideWorkingDirectoryError(
                    f"Access denied: {path} is outside working directory. {error or ''}"
                )

    return resolved


def read_file(
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    root_dir: str | None = None,
) -> dict[str, Any]:
    """Read the contents of a file, optionally a specific line range.

    Args:
        file_path: Absolute or relative path to the file
        start_line: Starting line number (1-based, inclusive). If None, starts from beginning.
        end_line: Ending line number (1-based, inclusive). If None, reads to end.
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'content' or 'error' key
    """
    try:
        path = _validate_path(file_path, root_dir, operation="read")

        if not path.exists():
            return {"status": "FAILED", "error": f"File not found: {file_path}"}

        if not path.is_file():
            return {"status": "FAILED", "error": f"Not a file: {file_path}"}

        content = path.read_text(encoding="utf-8")
        all_lines = content.split("\n")
        total_lines = len(all_lines)

        # Determine line range (convert to 0-based indexing)
        start_idx = 0 if start_line is None else max(0, start_line - 1)
        end_idx = total_lines if end_line is None else min(total_lines, end_line)

        # Validate range
        if start_idx >= total_lines:
            return {"status": "FAILED", "error": f"Start line {start_line} is beyond file length ({total_lines} lines)"}

        # Extract the requested lines
        selected_lines = all_lines[start_idx:end_idx]

        # Add line numbers for better context
        # Preserve exact whitespace - tabs and spaces are kept as-is
        numbered_lines = [f"{start_idx + i + 1:4d} | {line}" for i, line in enumerate(selected_lines)]

        # Build raw content for the selected range
        raw_content = "\n".join(selected_lines)

        result = {
            "status": "SUCCESS",
            "content": "\n".join(numbered_lines),
            "raw_content": raw_content,
            "path": str(path),
            "total_lines": total_lines,
        }

        # Add range info if a range was specified
        if start_line is not None or end_line is not None:
            result["showing_lines"] = f"{start_idx + 1}-{end_idx}"
            result["lines_shown"] = len(selected_lines)
        else:
            result["lines"] = total_lines

        return result
    except OutsideWorkingDirectoryError as e:
        return {"status": "DENIED", "error": str(e)}
    except PermissionError as e:
        return {"status": "FAILED", "error": str(e)}
    except UnicodeDecodeError:
        return {"status": "FAILED", "error": f"Cannot read binary file: {file_path}"}
    except Exception as e:
        return {"status": "FAILED", "error": f"Error reading file: {e}"}


def write_file(
    file_path: str, content: str, root_dir: str | None = None
) -> dict[str, Any]:
    """Write content to a file, creating it if necessary.

    Args:
        file_path: Path to the file
        content: Content to write
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'status', 'success'/'error', and details
    """
    try:
        path = _validate_path(file_path, root_dir, operation="write")

        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(content, encoding="utf-8")
        line_count = content.count("\n") + 1

        return {
            "status": "SUCCESS",
            "success": True,
            "message": f"Successfully wrote {len(content.encode('utf-8'))} bytes ({line_count} lines) to {path.name}",
            "path": str(path),
            "bytes_written": len(content.encode("utf-8")),
            "lines_written": line_count,
        }
    except OutsideWorkingDirectoryError as e:
        return {"status": "DENIED", "error": str(e)}
    except PermissionError as e:
        return {"status": "FAILED", "error": str(e)}
    except Exception as e:
        return {"status": "FAILED", "error": f"Error writing file: {e}"}


def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    root_dir: str | None = None,
) -> dict[str, Any]:
    """Edit a file by replacing a unique string with new content.

    The old_string must be unique in the file (appear exactly once). If it appears
    multiple times, provide more surrounding context to make it unique.

    To DELETE text, provide an empty string "" as new_string.

    Uses multiple fallback matching strategies to handle minor whitespace differences
    between the model's output and the actual file content.

    Args:
        file_path: Path to the file
        old_string: Exact string to find and replace (must be unique in file)
        new_string: Replacement string (use "" to delete the old_string)
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'success' and 'message' or 'error' and 'status' keys
    """
    try:
        path = _validate_path(file_path, root_dir, operation="edit")

        if not path.exists():
            return {
                "status": "FAILED",
                "error": f"File not found: {file_path}"
            }

        content = path.read_text(encoding="utf-8")

        # Use fallback strategies for matching
        success, new_content, strategy_used = apply_edit(content, old_string, new_string)

        if not success:
            # Provide helpful debugging info
            old_repr = repr(old_string[:200]) if len(old_string) > 200 else repr(old_string)

            if strategy_used.startswith("exact_multiple_"):
                count = int(strategy_used.split("_")[-1])
                return {
                    "status": "FAILED",
                    "error": f"String appears {count} times in file. Include more surrounding context to make it unique."
                }
            else:
                return {
                    "status": "FAILED",
                    "error": f"String not found in file (tried multiple matching strategies). Ensure whitespace matches exactly. Searched for: {old_repr}"
                }

        # Handle deletion: if new_string is empty, try to clean up entire lines
        if new_string == "" and strategy_used == "exact":
            # Find the position of old_string in content
            pos = content.find(old_string)
            if pos != -1:
                # Find the start of the line (after previous newline or start of file)
                line_start = content.rfind("\n", 0, pos) + 1
                # Check if everything between line_start and pos is whitespace
                before_match = content[line_start:pos]
                if before_match == "" or before_match.isspace():
                    # Find the end of the line (next newline or end of file)
                    line_end = content.find("\n", pos + len(old_string))
                    if line_end == -1:
                        line_end = len(content)
                    else:
                        line_end += 1  # Include the newline in deletion
                    # Check if everything after old_string to end of line is whitespace
                    after_match = content[pos + len(old_string):line_end].rstrip("\n")
                    if after_match == "" or after_match.isspace():
                        # Delete the entire line(s)
                        new_content = content[:line_start] + content[line_end:]

        path.write_text(new_content, encoding="utf-8")

        # Count lines changed
        old_line_count = old_string.count("\n") + 1
        new_line_count = new_string.count("\n") + 1 if new_string else 0

        result = {
            "status": "SUCCESS",
            "success": True,
            "path": str(path),
        }

        if new_string == "":
            result["message"] = f"Successfully deleted {len(old_string)} chars ({old_line_count} lines)"
            result["old_length"] = len(old_string)
        else:
            result["message"] = f"Successfully replaced {len(old_string)} chars ({old_line_count} lines) with {len(new_string)} chars ({new_line_count} lines)"
            result["old_length"] = len(old_string)
            result["new_length"] = len(new_string)

        # Note which strategy was used (helpful for debugging)
        if strategy_used != "exact":
            result["matching_strategy"] = strategy_used
            result["note"] = f"Used fallback matching strategy: {strategy_used}"

        return result

    except OutsideWorkingDirectoryError as e:
        return {"status": "DENIED", "error": str(e)}
    except PermissionError as e:
        return {"status": "FAILED", "error": str(e)}
    except UnicodeDecodeError:
        return {"status": "FAILED", "error": f"Cannot edit binary file: {file_path}"}
    except Exception as e:
        return {"status": "FAILED", "error": f"Error editing file: {e}"}


def search_files(
    pattern: str,
    dir_path: str = ".",
    include_contents: bool = True,
    root_dir: str | None = None,
) -> dict[str, Any]:
    """Search for files by name or content matching a regex pattern.

    Args:
        pattern: Regex pattern to match against file names and/or contents
        dir_path: Directory to search in (defaults to current directory)
        include_contents: Whether to also search file contents (default True)
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'matches' list or 'error' key
    """
    import re

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

    # Binary file extensions to skip for content search
    binary_extensions = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".zip", ".tar", ".gz", ".rar", ".7z",
        ".exe", ".dll", ".so", ".dylib",
        ".pyc", ".pyo", ".class", ".o", ".obj",
        ".woff", ".woff2", ".ttf", ".eot",
        ".mp3", ".mp4", ".avi", ".mov", ".wav",
        ".sqlite", ".db",
    }

    try:
        path = _validate_path(dir_path, root_dir, operation="search")

        if not path.exists():
            return {"status": "FAILED", "error": f"Directory not found: {dir_path}"}

        if not path.is_dir():
            return {"status": "FAILED", "error": f"Not a directory: {dir_path}"}

        # Compile regex
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return {"status": "FAILED", "error": f"Invalid regex pattern: {e}"}

        matches = []
        max_matches = 50  # Limit results to avoid overwhelming output

        def scan_dir(current_path: Path, rel_prefix: str = ""):
            nonlocal matches

            if len(matches) >= max_matches:
                return

            try:
                items = sorted(current_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            except PermissionError:
                return

            for item in items:
                if len(matches) >= max_matches:
                    return

                # Build relative path for matching
                rel_path = f"{rel_prefix}/{item.name}" if rel_prefix else item.name

                if item.is_dir():
                    # Skip hidden and common non-essential directories
                    if item.name.lower() in skip_dirs or item.name.startswith("."):
                        continue
                    scan_dir(item, rel_path)
                else:
                    match_type = None
                    matching_lines = []

                    # Check if file name/path matches regex
                    if regex.search(rel_path) or regex.search(item.name):
                        match_type = "filename"

                    # Check file contents if enabled and not a binary file
                    if include_contents and item.suffix.lower() not in binary_extensions:
                        try:
                            content = item.read_text(encoding="utf-8", errors="ignore")
                            lines = content.split("\n")
                            for i, line in enumerate(lines, 1):
                                if regex.search(line):
                                    matching_lines.append({
                                        "line": i,
                                        "text": line.strip()[:100]  # Truncate long lines
                                    })
                                    if len(matching_lines) >= 5:  # Limit matches per file
                                        break
                            if matching_lines:
                                match_type = "content" if match_type is None else "both"
                        except (PermissionError, OSError):
                            pass

                    if match_type:
                        match_entry = {
                            "path": str(item),
                            "relative_path": rel_path,
                            "name": item.name,
                            "size": _format_size(item.stat().st_size),
                            "match_type": match_type,
                        }
                        if matching_lines:
                            match_entry["matching_lines"] = matching_lines
                        matches.append(match_entry)

        scan_dir(path)

        truncated = len(matches) >= max_matches

        return {
            "status": "SUCCESS",
            "matches": matches,
            "count": len(matches),
            "truncated": truncated,
            "message": f"Found {len(matches)} matches for '{pattern}'" + (" (truncated)" if truncated else ""),
        }

    except OutsideWorkingDirectoryError as e:
        return {"status": "DENIED", "error": str(e)}
    except PermissionError as e:
        return {"status": "FAILED", "error": str(e)}
    except Exception as e:
        return {"status": "FAILED", "error": f"Error searching files: {e}"}


def delete_file(
    file_path: str,
    root_dir: str | None = None,
) -> dict[str, Any]:
    """Delete a file.

    Args:
        file_path: Path to the file to delete
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'status' and 'message' or 'error'
    """
    try:
        path = _validate_path(file_path, root_dir, operation="delete")

        if not path.exists():
            return {"status": "FAILED", "error": f"File not found: {file_path}"}

        if not path.is_file():
            return {"status": "FAILED", "error": f"Not a file (use a different method for directories): {file_path}"}

        # Get file info before deletion for the message
        file_size = path.stat().st_size
        file_name = path.name

        path.unlink()

        return {
            "status": "SUCCESS",
            "success": True,
            "message": f"Successfully deleted file: {file_name} ({_format_size(file_size)})",
            "path": str(path),
        }
    except OutsideWorkingDirectoryError as e:
        return {"status": "DENIED", "error": str(e)}
    except PermissionError as e:
        return {"status": "FAILED", "error": f"Permission denied: {e}"}
    except Exception as e:
        return {"status": "FAILED", "error": f"Error deleting file: {e}"}


def _format_size(size: int) -> str:
    """Format file size in human-readable format."""
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}K"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}M"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f}G"


def list_directory(
    dir_path: str = ".",
    max_depth: int = 10,
    root_dir: str | None = None,
) -> dict[str, Any]:
    """Show directory structure as a tree with file details.

    Args:
        dir_path: Path to the directory
        max_depth: Maximum depth to traverse (default 10)
        root_dir: Optional root directory to restrict access

    Returns:
        Dict with 'tree' string or 'error' key
    """
    import datetime

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
        path = _validate_path(dir_path, root_dir, operation="list")

        if not path.exists():
            return {"status": "FAILED", "error": f"Directory not found: {dir_path}"}

        if not path.is_dir():
            return {"status": "FAILED", "error": f"Not a directory: {dir_path}"}

        lines = []
        total_files = 0
        total_dirs = 0

        def format_entry(item: Path, prefix: str, connector: str) -> str:
            """Format a single entry with ls -la style info."""
            try:
                stat = item.stat()
                size = _format_size(stat.st_size) if item.is_file() else "<DIR>"
                mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
                date_str = mtime.strftime("%Y-%m-%d %H:%M")
                name = f"{item.name}/" if item.is_dir() else item.name
                return f"{prefix}{connector}{size:>8}  {date_str}  {name}"
            except (PermissionError, OSError):
                name = f"{item.name}/" if item.is_dir() else item.name
                return f"{prefix}{connector}{'???':>8}  {'????-??-?? ??:??'}  {name}"

        def add_entries(current_path: Path, prefix: str = "", depth: int = 0):
            nonlocal total_files, total_dirs

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

                lines.append(format_entry(item, prefix, connector))

                if item.is_dir():
                    total_dirs += 1
                    extension = "    " if is_last else "│   "
                    add_entries(item, prefix + extension, depth + 1)
                else:
                    total_files += 1

        # Header
        lines.append(f"{path.name}/")
        lines.append(f"{'=' * 60}")

        add_entries(path)

        # Summary
        lines.append(f"{'=' * 60}")
        lines.append(f"Total: {total_files} files, {total_dirs} directories")

        return {
            "status": "SUCCESS",
            "path": str(path),
            "tree": "\n".join(lines),
            "total_files": total_files,
            "total_dirs": total_dirs,
        }
    except OutsideWorkingDirectoryError as e:
        return {"status": "DENIED", "error": str(e)}
    except PermissionError as e:
        return {"status": "FAILED", "error": str(e)}
    except Exception as e:
        return {"status": "FAILED", "error": f"Error creating directory tree: {e}"}


def _make_read_file_handler(root_dir: str | None):
    """Create a handler for read_file that ignores extra kwargs."""
    def handler(file_path: str, start_line: int | None = None, end_line: int | None = None, **kwargs) -> dict[str, Any]:
        return read_file(file_path, start_line, end_line, root_dir)
    return handler


def _make_write_file_handler(root_dir: str | None):
    """Create a handler for write_file that ignores extra kwargs."""
    def handler(file_path: str, content: str, **kwargs) -> dict[str, Any]:
        return write_file(file_path, content, root_dir)
    return handler


def _make_edit_file_handler(root_dir: str | None):
    """Create a handler for edit_file that ignores extra kwargs."""
    def handler(
        file_path: str,
        old_string: str,
        new_string: str,
        **kwargs
    ) -> dict[str, Any]:
        return edit_file(file_path, old_string, new_string, root_dir)
    return handler


def _make_list_directory_handler(root_dir: str | None):
    """Create a handler for list_directory that ignores extra kwargs."""
    def handler(dir_path: str = ".", max_depth: int = 10, **kwargs) -> dict[str, Any]:
        return list_directory(dir_path, max_depth, root_dir)
    return handler


def _make_delete_file_handler(root_dir: str | None):
    """Create a handler for delete_file that ignores extra kwargs."""
    def handler(file_path: str, **kwargs) -> dict[str, Any]:
        return delete_file(file_path, root_dir)
    return handler


def _make_search_files_handler(root_dir: str | None):
    """Create a handler for search_files that ignores extra kwargs."""
    def handler(pattern: str, dir_path: str = ".", include_contents: bool = True, **kwargs) -> dict[str, Any]:
        return search_files(pattern, dir_path, include_contents, root_dir)
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
            description="""\
Read the contents of a file and return it with line numbers.

WHEN TO USE:
- Before editing a file (ALWAYS read first, then edit)
- When you need to understand file contents
- To check if a file exists and what it contains

PARAMETERS:
- file_path: Path to the file (relative to working directory or absolute)
- start_line: Optional starting line (1-based). Use for large files.
- end_line: Optional ending line (1-based). Use for large files.

OUTPUT:
- Returns file content with line numbers (e.g., "  42 | def foo():")
- Preserves exact whitespace (tabs, spaces) for accurate editing
- Shows total line count

FAILURE MODES:
- File not found: Check the path, use search_files to locate it
- Binary file: Cannot read binary files (images, compiled code, etc.)
- Permission denied: File may be protected

EXAMPLE:
read_file(file_path="src/main.py")
read_file(file_path="src/main.py", start_line=100, end_line=150)
""",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to read",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Starting line number (1-based, inclusive). Omit to start from beginning.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Ending line number (1-based, inclusive). Omit to read to end.",
                    },
                },
                "required": ["file_path"],
            },
            handler=_make_read_file_handler(root_dir),
        ),
        ToolDefinition(
            name="write_file",
            description="""\
Create a new file or completely overwrite an existing file with new content.

WHEN TO USE:
- Creating a brand new file that doesn't exist
- Completely replacing all content in a file
- NOT for partial edits (use edit_file instead)

PARAMETERS:
- file_path: Path where the file should be created/overwritten
- content: The complete content to write

BEHAVIOR:
- Creates parent directories if they don't exist
- Overwrites existing file completely (all previous content is lost)
- Uses UTF-8 encoding

FAILURE MODES:
- Permission denied: Check directory permissions
- Invalid path: Ensure path is valid for your OS

WARNING: This OVERWRITES the entire file. For partial changes, use edit_file.

EXAMPLE:
write_file(file_path="src/new_module.py", content="def hello():\\n    print('Hello')")
""",
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
            description="""\
Edit a file by finding and replacing a unique string. This is the preferred way to modify existing files.

IMPORTANT: ALWAYS read_file BEFORE edit_file to ensure you have the current content.

PARAMETERS:
- file_path: Path to the file to edit
- old_string: The EXACT string to find (must appear exactly once in the file)
- new_string: The replacement string (use "" to delete the old_string)

REQUIREMENTS:
1. old_string must match EXACTLY including whitespace, indentation, and newlines
2. old_string must be UNIQUE in the file (appear only once)
3. Include surrounding context lines if the target string appears multiple times

FAILURE MODES:
- "String not found": Your old_string doesn't match exactly. Check:
  - Whitespace (tabs vs spaces)
  - Line endings
  - Hidden characters
  - Read the file again to get the exact content
- "String appears N times": Include more surrounding lines to make it unique

EXAMPLES:
# Change a function name
edit_file(
    file_path="src/utils.py",
    old_string="def old_name(",
    new_string="def new_name("
)

# Delete a line (include the newline)
edit_file(
    file_path="src/utils.py",
    old_string="    # TODO: remove this\\n",
    new_string=""
)

# Add a new import (include context to make unique)
edit_file(
    file_path="src/main.py",
    old_string="import os\\nimport sys",
    new_string="import os\\nimport sys\\nimport json"
)
""",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to edit",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The exact string to find and replace (must appear exactly once in the file)",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The replacement string (use empty string '' to delete old_string)",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
            handler=_make_edit_file_handler(root_dir),
        ),
        ToolDefinition(
            name="list_directory",
            description="""\
Show the directory structure as a tree with file sizes and modification dates.

WHEN TO USE:
- Understanding the project layout
- Finding files when you don't know the exact path
- Exploring a new codebase

PARAMETERS:
- dir_path: Directory to list (default: current directory)
- max_depth: How deep to traverse (default: 10)

OUTPUT:
- Tree structure with file sizes and dates
- Total file and directory count
- Automatically skips: node_modules, __pycache__, .git, venv, dist, build, etc.

EXAMPLE:
list_directory()
list_directory(dir_path="src", max_depth=3)
""",
            parameters={
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "The path to the directory to list (defaults to current directory)",
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
            handler=_make_list_directory_handler(root_dir),
        ),
        ToolDefinition(
            name="delete_file",
            description="""\
Delete a file permanently.

WHEN TO USE:
- Removing files that are no longer needed
- Cleaning up temporary files

PARAMETERS:
- file_path: Path to the file to delete

WARNING: This action cannot be undone. The file is permanently deleted.

LIMITATIONS:
- Only works on files, not directories
- Cannot delete files outside the working directory without confirmation

EXAMPLE:
delete_file(file_path="src/old_module.py")
""",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to delete",
                    },
                },
                "required": ["file_path"],
            },
            handler=_make_delete_file_handler(root_dir),
        ),
        ToolDefinition(
            name="search_files",
            description="""\
Search for files by name or content using regex patterns.

WHEN TO USE:
- Finding where a function/class/variable is defined
- Locating files by name pattern
- Finding all occurrences of a string across the codebase

PARAMETERS:
- pattern: Regex pattern (case-insensitive)
- dir_path: Directory to search in (default: current directory)
- include_contents: Search file contents too, not just names (default: true)

OUTPUT:
- List of matching files with paths
- For content matches: line numbers and text of matching lines
- Limited to 50 results

COMMON PATTERNS:
- "def my_function" - Find function definition
- "class MyClass" - Find class definition
- "\\.py$" - Find Python files by name
- "TODO|FIXME" - Find all TODOs and FIXMEs
- "import json" - Find files importing json

SKIPPED DIRECTORIES: node_modules, __pycache__, .git, venv, dist, build, etc.

EXAMPLE:
search_files(pattern="def calculate_total")
search_files(pattern="\\.test\\.py$", include_contents=False)
""",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to match against file names and contents (case-insensitive)",
                    },
                    "dir_path": {
                        "type": "string",
                        "description": "Directory to search in (defaults to current directory)",
                        "default": ".",
                    },
                    "include_contents": {
                        "type": "boolean",
                        "description": "Search file contents too, not just names (default true)",
                        "default": True,
                    },
                },
                "required": ["pattern"],
            },
            handler=_make_search_files_handler(root_dir),
        ),
    ]
