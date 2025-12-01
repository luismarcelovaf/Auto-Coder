"""Project context management for code-crafter."""

import os
from pathlib import Path
from typing import AsyncIterator, Callable

# Approximate characters per token (conservative estimate)
CHARS_PER_TOKEN = 4
MAX_TOKENS_PER_CHUNK = 100_000
MAX_CHARS_PER_CHUNK = MAX_TOKENS_PER_CHUNK * CHARS_PER_TOKEN  # ~400k chars

# File extensions to analyze when investigating a project
ANALYZABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".rb",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".php", ".swift", ".kt", ".scala",
    ".html", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".cfg", ".conf",
    ".md", ".txt", ".rst", ".adoc",
    ".sql", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".dockerfile", ".makefile", ".cmake",
    ".env.example", ".gitignore", ".dockerignore",
    ".graphql", ".proto", ".thrift",
    ".tf", ".tfvars",  # Terraform
    ".gradle", ".sbt",  # Build files
    ".r", ".rmd",  # R
    ".jl",  # Julia
    ".ex", ".exs",  # Elixir
    ".clj", ".cljs",  # Clojure
    ".hs",  # Haskell
    ".ml", ".mli",  # OCaml
    ".fs", ".fsx",  # F#
    ".lua",
    ".vim",
    ".el",  # Emacs Lisp
}

# Files to always include in project analysis (by name, case-insensitive)
IMPORTANT_FILES = {
    "readme.md", "readme.rst", "readme.txt", "readme",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pipfile", "poetry.lock",
    "package.json", "package-lock.json", "yarn.lock", "tsconfig.json", "jsconfig.json",
    "cargo.toml", "cargo.lock",
    "go.mod", "go.sum",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "makefile", "cmakelists.txt", "meson.build",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "jenkinsfile", ".gitlab-ci.yml", ".github/workflows",
    ".env.example", ".env.sample",
    "license", "license.md", "license.txt",
    "contributing.md", "changelog.md", "history.md",
    "manifest.json", "app.json",
    "webpack.config.js", "vite.config.js", "rollup.config.js",
    "babel.config.js", ".babelrc",
    "jest.config.js", "vitest.config.js", "pytest.ini", "tox.ini",
    ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".prettierrc",
    "nginx.conf", "apache.conf",
}

# Directories to skip
SKIP_DIRS = {
    ".git", ".svn", ".hg", ".bzr",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "venv", ".venv", "env", ".env", "virtualenv",
    "dist", "build", "target", "out", "bin", "obj",
    ".idea", ".vscode", ".vs",
    "coverage", ".coverage", "htmlcov", ".nyc_output",
    ".tox", ".nox",
    "vendor", "third_party", "external",
    ".terraform",
    ".next", ".nuxt", ".output",
    "eggs", "*.egg-info",
    ".cache", ".parcel-cache",
    "logs", "log",
    "tmp", "temp",
}

# Files to skip (by pattern)
SKIP_FILES = {
    ".ds_store", "thumbs.db", "desktop.ini",
    ".gitkeep", ".keep",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",  # Large lock files
    "poetry.lock", "cargo.lock", "composer.lock", "gemfile.lock",
}

PROJECT_FILE = "PROJECT.md"


def get_project_file_path(working_dir: str) -> Path:
    """Get the path to the PROJECT.md file."""
    return Path(working_dir) / PROJECT_FILE


def has_project_file(working_dir: str) -> bool:
    """Check if PROJECT.md exists in the working directory."""
    return get_project_file_path(working_dir).exists()


def load_project_context(working_dir: str) -> str | None:
    """Load the PROJECT.md content if it exists.

    Args:
        working_dir: The working directory to check

    Returns:
        The content of PROJECT.md or None if it doesn't exist
    """
    project_file = get_project_file_path(working_dir)
    if project_file.exists():
        try:
            return project_file.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def save_project_context(working_dir: str, content: str) -> bool:
    """Save content to PROJECT.md.

    Args:
        working_dir: The working directory
        content: The content to save

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        project_file = get_project_file_path(working_dir)
        project_file.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def _should_skip_dir(dir_name: str) -> bool:
    """Check if a directory should be skipped."""
    dir_lower = dir_name.lower()
    return dir_lower in SKIP_DIRS or dir_lower.startswith(".")


def _should_skip_file(file_name: str) -> bool:
    """Check if a file should be skipped."""
    file_lower = file_name.lower()
    return file_lower in SKIP_FILES


def _is_analyzable_file(file_path: Path) -> bool:
    """Check if a file should be analyzed."""
    name_lower = file_path.name.lower()

    # Check if it's an important file
    if name_lower in IMPORTANT_FILES:
        return True

    # Check extension
    suffix_lower = file_path.suffix.lower()
    if suffix_lower in ANALYZABLE_EXTENSIONS:
        return True

    # Check for extensionless important files
    if file_path.suffix == "" and name_lower in {"makefile", "dockerfile", "jenkinsfile", "vagrantfile", "procfile"}:
        return True

    return False


def _estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text."""
    return len(text) // CHARS_PER_TOKEN


def get_full_directory_structure(working_dir: str) -> str:
    """Get the complete directory structure as a tree.

    Args:
        working_dir: The working directory

    Returns:
        A string representation of the complete directory structure
    """
    lines = []
    root = Path(working_dir)

    def add_dir(path: Path, prefix: str = ""):
        try:
            items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return

        # Separate dirs and files
        dirs = []
        files = []

        for item in items:
            name = item.name
            # Skip hidden and ignored items
            if _should_skip_dir(name) if item.is_dir() else _should_skip_file(name):
                continue
            if item.is_dir():
                dirs.append(item)
            elif _is_analyzable_file(item):
                files.append(item)

        all_items = files + dirs
        for i, item in enumerate(all_items):
            is_last = i == len(all_items) - 1
            connector = "└── " if is_last else "├── "

            if item.is_dir():
                lines.append(f"{prefix}{connector}{item.name}/")
                extension = "    " if is_last else "│   "
                add_dir(item, prefix + extension)
            else:
                lines.append(f"{prefix}{connector}{item.name}")

    lines.append(f"{root.name}/")
    add_dir(root)

    return "\n".join(lines)


def gather_all_project_files(working_dir: str) -> list[tuple[str, str]]:
    """Gather ALL relevant project files for analysis.

    Args:
        working_dir: The working directory to analyze

    Returns:
        List of tuples (relative_path, content)
    """
    files: list[tuple[str, str]] = []
    root = Path(working_dir)

    def scan_dir(path: Path):
        try:
            items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return

        for item in items:
            if item.is_dir():
                if not _should_skip_dir(item.name):
                    scan_dir(item)
            elif item.is_file():
                if _should_skip_file(item.name):
                    continue
                if _is_analyzable_file(item):
                    try:
                        content = item.read_text(encoding="utf-8", errors="ignore")
                        rel_path = str(item.relative_to(root))
                        files.append((rel_path, content))
                    except Exception:
                        pass

    scan_dir(root)
    return files


def create_file_content_block(file_path: str, content: str) -> str:
    """Create a formatted block for a file's content."""
    return f"### {file_path}\n```\n{content}\n```\n\n"


def chunk_files_by_tokens(
    files: list[tuple[str, str]],
    max_tokens: int = MAX_TOKENS_PER_CHUNK,
) -> list[list[tuple[str, str]]]:
    """Split files into chunks that fit within token limits.

    Args:
        files: List of (path, content) tuples
        max_tokens: Maximum tokens per chunk

    Returns:
        List of chunks, each chunk is a list of (path, content) tuples
    """
    chunks: list[list[tuple[str, str]]] = []
    current_chunk: list[tuple[str, str]] = []
    current_tokens = 0

    for file_path, content in files:
        # Estimate tokens for this file (including formatting)
        file_block = create_file_content_block(file_path, content)
        file_tokens = _estimate_tokens(file_block)

        # If single file exceeds limit, truncate it
        if file_tokens > max_tokens:
            # Truncate content to fit
            max_content_chars = (max_tokens - 500) * CHARS_PER_TOKEN  # Leave room for formatting
            truncated_content = content[:max_content_chars] + f"\n\n... [TRUNCATED - file too large, showing first {max_content_chars} characters]"
            file_tokens = _estimate_tokens(create_file_content_block(file_path, truncated_content))
            content = truncated_content

        # If adding this file exceeds the limit, start a new chunk
        if current_tokens + file_tokens > max_tokens and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_tokens = 0

        current_chunk.append((file_path, content))
        current_tokens += file_tokens

    # Don't forget the last chunk
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def create_chunk_summary_prompt(
    chunk_files: list[tuple[str, str]],
    chunk_index: int,
    total_chunks: int,
) -> str:
    """Create a prompt to summarize a chunk of files.

    Args:
        chunk_files: List of (path, content) tuples
        chunk_index: Current chunk index (0-based)
        total_chunks: Total number of chunks

    Returns:
        Prompt string for summarization
    """
    prompt_parts = [
        f"You are analyzing a codebase. This is chunk {chunk_index + 1} of {total_chunks}.",
        "",
        "Please provide a detailed summary of these files, including:",
        "- Purpose of each file/module",
        "- Key classes, functions, and their responsibilities",
        "- Important patterns or architecture decisions",
        "- Dependencies and integrations",
        "- Any notable configurations",
        "",
        "Be thorough but concise. Focus on information that would help a developer understand this part of the codebase.",
        "",
        "---",
        "",
        "## Files in this chunk:",
        "",
    ]

    for file_path, content in chunk_files:
        prompt_parts.append(create_file_content_block(file_path, content))

    return "\n".join(prompt_parts)


def create_final_summary_prompt(
    chunk_summaries: list[str],
    directory_structure: str,
) -> str:
    """Create a prompt to generate the final PROJECT.md from chunk summaries.

    Args:
        chunk_summaries: List of summaries from each chunk
        directory_structure: The full directory structure

    Returns:
        Prompt string for final PROJECT.md generation
    """
    prompt_parts = [
        "Based on the following summaries of different parts of a codebase, create a comprehensive PROJECT.md file.",
        "",
        "## Directory Structure",
        "```",
        directory_structure,
        "```",
        "",
        "## Codebase Summaries",
        "",
    ]

    for i, summary in enumerate(chunk_summaries, 1):
        prompt_parts.append(f"### Part {i}")
        prompt_parts.append(summary)
        prompt_parts.append("")

    prompt_parts.extend([
        "---",
        "",
        "Now create a comprehensive PROJECT.md file that includes:",
        "",
        "1. **Project Overview**: What this project does and its purpose",
        "2. **Tech Stack**: Languages, frameworks, and key dependencies",
        "3. **Project Structure**: Explanation of the directory layout and organization",
        "4. **Key Components**: Main modules/classes and their responsibilities",
        "5. **Architecture**: How components interact, data flow, design patterns used",
        "6. **Getting Started**: How to set up and run the project",
        "7. **Configuration**: Important configuration options and environment variables",
        "8. **API/Interfaces**: Key APIs, endpoints, or interfaces (if applicable)",
        "9. **Testing**: How to run tests, testing strategy",
        "10. **Development Notes**: Any other relevant information for developers",
        "",
        "Format the response as a complete markdown document that can be saved directly as PROJECT.md.",
        "Start the file with a level-1 heading with the project name.",
        "Be comprehensive but well-organized.",
    ])

    return "\n".join(prompt_parts)


class ProjectInvestigator:
    """Handles the chunked investigation of a project."""

    def __init__(
        self,
        working_dir: str,
        on_status: Callable[[str], None] | None = None,
    ):
        self.working_dir = working_dir
        self.on_status = on_status or (lambda x: None)

    def _status(self, message: str) -> None:
        """Report status update."""
        self.on_status(message)

    async def investigate(
        self,
        run_prompt: Callable[[str], AsyncIterator[str]],
    ) -> str:
        """Investigate the project and generate PROJECT.md content.

        Args:
            run_prompt: Async function that takes a prompt and yields response chunks

        Returns:
            The generated PROJECT.md content
        """
        # Step 1: Get directory structure
        self._status("Scanning directory structure...")
        dir_structure = get_full_directory_structure(self.working_dir)

        # Step 2: Gather all files
        self._status("Gathering project files...")
        all_files = gather_all_project_files(self.working_dir)
        self._status(f"Found {len(all_files)} files to analyze")

        if not all_files:
            # No files found, create a minimal PROJECT.md
            return f"# Project\n\nEmpty project directory.\n\n## Structure\n```\n{dir_structure}\n```\n"

        # Step 3: Chunk files
        self._status("Organizing files into chunks...")
        chunks = chunk_files_by_tokens(all_files)
        self._status(f"Split into {len(chunks)} chunks for analysis")

        # Step 4: Summarize each chunk
        chunk_summaries: list[str] = []

        for i, chunk_files in enumerate(chunks):
            self._status(f"Analyzing chunk {i + 1}/{len(chunks)} ({len(chunk_files)} files)...")

            prompt = create_chunk_summary_prompt(chunk_files, i, len(chunks))

            # Collect the response
            response = ""
            async for chunk in run_prompt(prompt):
                response += chunk

            chunk_summaries.append(response.strip())

        # Step 5: Generate final PROJECT.md
        self._status("Generating final PROJECT.md...")

        final_prompt = create_final_summary_prompt(chunk_summaries, dir_structure)

        final_response = ""
        async for chunk in run_prompt(final_prompt):
            final_response += chunk

        return final_response.strip()
