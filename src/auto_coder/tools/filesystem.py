"""File system tools for reading, writing, and editing files."""

import os
from pathlib import Path
from typing import Any

from ..providers.base import ToolDefinition
from .safety import (
    check_path_safety,
    confirm_dangerous_operation,
)


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
    old_string: str | None = None,
    new_string: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    insert_line: int | None = None,
    delete_lines: bool = False,
    root_dir: str | None = None,
) -> dict[str, Any]:
    """Edit a file by replacing text, replacing/deleting lines, or inserting new lines.

    Four modes of operation:
    1. String replacement: Provide old_string and new_string to replace exact text
    2. Line replacement: Provide start_line, end_line, old_string (for verification), and new_string to replace lines
    3. Line deletion: Provide start_line, end_line, old_string (for verification), and delete_lines=True to remove lines
    4. Insert mode: Provide insert_line and new_string to insert new lines after that line

    IMPORTANT: For line-based operations (modes 2 and 3), old_string is REQUIRED to verify
    that the content at those lines hasn't changed since the file was read. This prevents
    accidental modifications when line numbers shift due to earlier edits.

    Args:
        file_path: Path to the file
        old_string: For string mode: exact string to find and replace.
                    For line modes: expected content at lines (for verification before edit)
        new_string: Replacement/insert string (use empty string "" to delete in string mode)
        start_line: Starting line number for line-based operations (1-based, inclusive)
        end_line: Ending line number for line-based operations (1-based, inclusive)
        insert_line: Line number after which to insert new content (0 = insert at beginning)
        delete_lines: If True with start_line/end_line, delete those lines entirely
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

        # Determine mode: insert, line-based, or string-based
        if insert_line is not None:
            # Insert mode - add new lines after specified line
            if new_string is None:
                return {
                    "status": "FAILED",
                    "error": "new_string is required for insert mode"
                }

            lines = content.split("\n")
            total_lines = len(lines)

            if insert_line < 0:
                return {
                    "status": "FAILED",
                    "error": f"insert_line must be >= 0, got {insert_line}"
                }

            # insert_line=0 means insert at beginning, otherwise insert after that line
            insert_idx = min(insert_line, total_lines)

            new_lines = new_string.split("\n")
            lines[insert_idx:insert_idx] = new_lines

            new_content = "\n".join(lines)
            path.write_text(new_content, encoding="utf-8")

            if insert_line == 0:
                position = "at the beginning"
            else:
                position = f"after line {insert_line}"

            return {
                "status": "SUCCESS",
                "success": True,
                "message": f"Inserted {len(new_lines)} lines {position}",
                "path": str(path),
                "lines_inserted": len(new_lines),
            }

        elif start_line is not None and end_line is not None:
            # Line-based replacement or deletion mode
            lines = content.split("\n")
            total_lines = len(lines)

            # Validate line numbers
            if start_line < 1:
                return {
                    "status": "FAILED",
                    "error": f"start_line must be >= 1, got {start_line}"
                }
            if end_line < start_line:
                return {
                    "status": "FAILED",
                    "error": f"end_line ({end_line}) must be >= start_line ({start_line})"
                }
            if start_line > total_lines:
                return {
                    "status": "FAILED",
                    "error": f"start_line {start_line} is beyond file length ({total_lines} lines)"
                }

            # REQUIRE old_string for verification to prevent edits when lines have shifted
            if old_string is None:
                return {
                    "status": "FAILED",
                    "error": "old_string is required for line-based operations to verify content hasn't changed. "
                             "Provide the expected content at lines {}-{} to ensure safe editing.".format(start_line, end_line)
                }

            # Adjust end_line if beyond file
            end_line = min(end_line, total_lines)

            # Convert to 0-based indexing
            start_idx = start_line - 1
            end_idx = end_line

            # Get the old content for reporting
            old_lines = lines[start_idx:end_idx]
            lines_removed = len(old_lines)

            # Verify that the content at these lines matches old_string
            actual_content = "\n".join(old_lines)
            if actual_content != old_string:
                # Provide helpful error message showing what's actually there
                actual_preview = actual_content[:200] + "..." if len(actual_content) > 200 else actual_content
                expected_preview = old_string[:200] + "..." if len(old_string) > 200 else old_string
                return {
                    "status": "FAILED",
                    "error": f"Content at lines {start_line}-{end_line} doesn't match expected content. "
                             f"The file may have changed since you read it. "
                             f"Please re-read the file to get current line numbers.\n"
                             f"Expected:\n{repr(expected_preview)}\n"
                             f"Actual:\n{repr(actual_preview)}"
                }

            if delete_lines:
                # Delete mode - remove lines entirely
                del lines[start_idx:end_idx]
                new_content = "\n".join(lines)
                path.write_text(new_content, encoding="utf-8")

                return {
                    "status": "SUCCESS",
                    "success": True,
                    "message": f"Deleted lines {start_line}-{end_line} ({lines_removed} lines removed)",
                    "path": str(path),
                    "lines_deleted": lines_removed,
                }
            else:
                # Replacement mode - need new_string
                if new_string is None:
                    return {
                        "status": "FAILED",
                        "error": "new_string is required when using line-based replacement (use delete_lines=True to delete)"
                    }

                # Replace the lines
                new_lines = new_string.split("\n")
                lines[start_idx:end_idx] = new_lines

                new_content = "\n".join(lines)
                path.write_text(new_content, encoding="utf-8")

                return {
                    "status": "SUCCESS",
                    "success": True,
                    "message": f"Replaced lines {start_line}-{end_line} ({lines_removed} lines) with {len(new_lines)} new lines",
                    "path": str(path),
                    "lines_replaced": lines_removed,
                    "new_lines_count": len(new_lines),
                }

        elif old_string is not None:
            # String-based replacement mode
            if new_string is None:
                return {
                    "status": "FAILED",
                    "error": "new_string is required when using string-based replacement"
                }

            # Check that old_string exists and is unique
            count = content.count(old_string)
            if count == 0:
                # Provide helpful debugging info
                old_repr = repr(old_string[:200]) if len(old_string) > 200 else repr(old_string)
                return {
                    "status": "FAILED",
                    "error": f"String not found in file. Make sure whitespace (tabs, spaces, newlines) matches exactly. Searched for: {old_repr}"
                }
            if count > 1:
                return {
                    "status": "FAILED",
                    "error": f"String appears {count} times in file. Provide more context to make it unique."
                }

            new_content = content.replace(old_string, new_string, 1)
            path.write_text(new_content, encoding="utf-8")

            # Count lines changed
            old_line_count = old_string.count("\n") + 1
            new_line_count = new_string.count("\n") + 1

            return {
                "status": "SUCCESS",
                "success": True,
                "message": f"Successfully replaced {len(old_string)} chars ({old_line_count} lines) with {len(new_string)} chars ({new_line_count} lines)",
                "path": str(path),
                "old_length": len(old_string),
                "new_length": len(new_string),
            }

        else:
            return {
                "status": "FAILED",
                "error": "Must provide either old_string (for string replacement) or start_line+end_line (for line replacement)"
            }

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
        old_string: str | None = None,
        new_string: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        insert_line: int | None = None,
        delete_lines: bool = False,
        **kwargs
    ) -> dict[str, Any]:
        return edit_file(file_path, old_string, new_string, start_line, end_line, insert_line, delete_lines, root_dir)
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
            description=(
                "Read the contents of a file. Returns the file content with line numbers. "
                "The content preserves exact whitespace (tabs, spaces) for accurate editing. "
                "Optionally specify a line range to read only part of the file."
            ),
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
                "Edit a file using one of four modes: "
                "(1) STRING MODE: Provide old_string and new_string to replace exact text. "
                "(2) LINE REPLACE: Provide start_line, end_line, old_string (content verification), and new_string. "
                "(3) LINE DELETE: Provide start_line, end_line, old_string (content verification), and delete_lines=true. "
                "(4) INSERT MODE: Provide insert_line and new_string to insert new lines (0 = beginning). "
                "IMPORTANT: For LINE modes, old_string MUST contain the exact content at those lines for verification."
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
                        "description": "For STRING MODE: exact string to find/replace. For LINE modes: REQUIRED expected content at the lines (for verification that file hasn't changed)",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The replacement/insert content (not needed for LINE DELETE mode)",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "For LINE modes: Starting line number (1-based, inclusive)",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "For LINE modes: Ending line number (1-based, inclusive)",
                    },
                    "delete_lines": {
                        "type": "boolean",
                        "description": "For LINE DELETE: Set to true to delete lines entirely (removes the lines, not just their content)",
                        "default": False,
                    },
                    "insert_line": {
                        "type": "integer",
                        "description": "For INSERT MODE: Line number after which to insert (0 = insert at beginning)",
                    },
                },
                "required": ["file_path"],
            },
            handler=_make_edit_file_handler(root_dir),
        ),
        ToolDefinition(
            name="list_directory",
            description=(
                "Show the directory structure as a tree with file sizes and dates (like ls -la). "
                "Recursively displays files and folders. Useful for understanding project layout. "
                "Automatically skips common non-essential directories like node_modules, __pycache__, .git, venv, etc."
            ),
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
            description=(
                "Delete a file. Use with caution - this action cannot be undone. "
                "Only works on files, not directories."
            ),
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
            description=(
                "Search for files by name OR content matching a regex pattern. "
                "Searches both file names and file contents by default. "
                r"Examples: 'def my_function' to find where a function is defined, "
                r"'\.py$' for Python files, 'TODO' to find TODO comments."
            ),
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
