"""Interactive REPL interface for auto-coder."""

import asyncio
import json
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .agent import Agent
from .providers.base import ToolCall
from .tools.safety import set_confirmation_callback


# Custom style for the prompt
PROMPT_STYLE = Style.from_dict({
    "prompt": "#00aa00 bold",
})


def create_key_bindings() -> KeyBindings:
    """Create custom key bindings for the REPL.

    - Enter: Submit the input
    - Alt+Enter: Insert newline for multiline input
    """
    kb = KeyBindings()

    @kb.add("escape", "enter")
    def _(event):
        """Insert a newline on Alt+Enter."""
        event.current_buffer.insert_text("\n")

    return kb


class ThinkingIndicator:
    """Animated 'Thinking...' indicator using Rich Live display."""

    def __init__(self, console: Console):
        self.console = console
        self._task: asyncio.Task | None = None
        self._running = False
        self._live: Live | None = None

    async def _animate(self) -> None:
        """Run the animation loop."""
        dots = [".", "..", "..."]
        idx = 0
        try:
            while self._running:
                self._live.update(Text(f"Thinking{dots[idx]}", style="cyan"))
                self._live.refresh()
                idx = (idx + 1) % len(dots)
                await asyncio.sleep(0.4)
        except asyncio.CancelledError:
            pass

    def start(self) -> None:
        """Start the thinking animation."""
        if self._running:
            return  # Already running
        self._running = True
        self._live = Live(Text("Thinking.", style="cyan"), console=self.console, refresh_per_second=10, auto_refresh=False, transient=True)
        self._live.start()
        self._task = asyncio.create_task(self._animate())

    async def stop(self) -> None:
        """Stop the thinking animation."""
        if not self._running:
            return  # Not running
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._live:
            self._live.stop()
            self._live = None


class REPL:
    """Interactive REPL for the auto-coder agent."""

    def __init__(
        self,
        agent: Agent,
        history_file: str | None = None,
    ):
        self.agent = agent
        self.console = Console()
        self.history_file = history_file
        self._cancel_requested = False
        self._current_task: asyncio.Task | None = None

        # Set up confirmation callback for dangerous commands
        set_confirmation_callback(self._confirm_dangerous_command)

    def _confirm_dangerous_command(self, prompt: str) -> bool:
        """Ask user to confirm a dangerous command.

        Args:
            prompt: The confirmation prompt to display

        Returns:
            True if user confirms, False otherwise
        """
        # Stop the thinking indicator if it's running
        if hasattr(self, '_thinking') and self._thinking:
            # We need to stop it synchronously, so we run the coroutine
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Create a new task to stop it
                    asyncio.ensure_future(self._thinking.stop())
                    # Give it a moment to stop
                    import time
                    time.sleep(0.1)
                else:
                    loop.run_until_complete(self._thinking.stop())
            except Exception:
                pass

        self.console.print()
        self.console.print(Panel(
            prompt,
            title="[bold red]Confirmation Required[/]",
            border_style="red",
        ))

        while True:
            try:
                response = input("[y/N] > ").strip().lower()
                if response in ("y", "yes"):
                    self.console.print("[yellow]Command approved by user.[/]")
                    return True
                elif response in ("n", "no", ""):
                    self.console.print("[green]Command denied by user.[/]")
                    return False
                else:
                    self.console.print("[dim]Please enter 'y' or 'n'[/]")
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[green]Command denied.[/]")
                return False

    def _format_tool_call(self, tool_call: ToolCall) -> Panel:
        """Format a tool call for display."""
        args_str = json.dumps(tool_call.arguments, indent=2)

        # Truncate long arguments
        if len(args_str) > 500:
            args_str = args_str[:500] + "\n..."

        content = Text()
        content.append(f"{tool_call.name}", style="bold cyan")
        content.append("\n")
        content.append(args_str, style="dim")

        return Panel(
            content,
            title="[bold yellow]Tool Call[/]",
            border_style="yellow",
            padding=(0, 1),
        )

    def _format_tool_result(self, name: str, result: str) -> Panel:
        """Format a tool result for display."""
        max_len = 2000
        border_style = "green"

        # Try to parse as JSON for better formatting
        try:
            parsed = json.loads(result)

            # Special handling for command results - show stdout/stderr
            if name == "run_command" and isinstance(parsed, dict):
                parts = []

                if parsed.get("status") == "FAILED":
                    border_style = "red"
                    if parsed.get("error"):
                        parts.append(f"[red]{parsed['error']}[/]")

                if parsed.get("stdout"):
                    stdout = parsed["stdout"]
                    if len(stdout) > max_len:
                        stdout = stdout[:max_len] + "..."
                    parts.append(f"[dim]stdout:[/]\n{stdout}")

                if parsed.get("stderr"):
                    stderr = parsed["stderr"]
                    if len(stderr) > max_len:
                        stderr = stderr[:max_len] + "..."
                    parts.append(f"[dim]stderr:[/]\n{stderr}")

                result_text = Text.from_markup("\n\n".join(parts)) if parts else Text("(no output)")

            # Special handling for list_directory - clean up tree characters for display
            elif name == "list_directory" and isinstance(parsed, dict) and "tree" in parsed:
                tree_output = parsed["tree"]
                # Clean up the tree characters for nicer display
                clean_lines = []
                for line in tree_output.split("\n"):
                    # Replace box-drawing characters with cleaner ASCII
                    line = line.replace("├── ", "  +- ")
                    line = line.replace("└── ", "  \\- ")
                    line = line.replace("│   ", "  |  ")
                    clean_lines.append(line)
                clean_tree = "\n".join(clean_lines)
                if len(clean_tree) > max_len:
                    clean_tree = clean_tree[:max_len] + "\n..."
                result_text = Text(clean_tree)

            elif "error" in parsed:
                border_style = "red"
                result_text = Text(parsed["error"], style="red")
            else:
                display = result[:max_len] + ("..." if len(result) > max_len else "")
                result_text = Text(display)

        except json.JSONDecodeError:
            display = result[:max_len] + ("..." if len(result) > max_len else "")
            result_text = Text(display)

        return Panel(
            result_text,
            title=f"[bold]{name} result[/]",
            border_style=border_style,
            padding=(0, 1),
        )

    def _on_tool_start(self, tool_call: ToolCall) -> None:
        """Called when a tool execution starts."""
        # Stop live display before printing tool panel
        if self._live_display:
            self._live_display.stop()
            self._live_display = None
        # Print any accumulated response before tool panel
        if self._current_response.strip():
            self.console.print(Markdown(self._current_response))
            self._current_response = ""
        self.console.print(self._format_tool_call(tool_call))

    def _on_tool_end(self, name: str, result: str) -> None:
        """Called when a tool execution ends."""
        self.console.print(self._format_tool_result(name, result))
        # Start thinking indicator for next LLM call
        self._thinking.start()

    async def _process_input(self, user_input: str) -> None:
        """Process user input and display response."""
        # Handle special commands
        if user_input.lower() in ("/quit", "/exit", "/q"):
            raise KeyboardInterrupt

        if user_input.lower() in ("/clear", "/reset"):
            new_correlation_id = self.agent.reset()
            self.console.print(
                f"[dim]Conversation cleared. New correlation ID: {new_correlation_id}[/]"
            )
            return

        if user_input.lower() == "/id":
            correlation_id = self.agent.get_correlation_id()
            self.console.print(f"[dim]Correlation ID: {correlation_id}[/]")
            return

        if user_input.lower() == "/help":
            self._show_help()
            return

        if not user_input.strip():
            return

        # Set up tool callbacks
        self.agent.on_tool_start = self._on_tool_start
        self.agent.on_tool_end = self._on_tool_end

        # Initialize instance variables for streaming state
        self._current_response = ""
        self._live_display = None
        self._thinking = ThinkingIndicator(self.console)

        self.console.print()  # Blank line before response

        # Start thinking indicator
        self._thinking.start()
        self._cancel_requested = False

        try:
            async for chunk in self.agent.run(user_input):
                # Check if cancellation was requested
                if self._cancel_requested:
                    raise asyncio.CancelledError()

                # Stop thinking indicator on first chunk of each LLM response
                await self._thinking.stop()

                # Start live display if not already running
                if not self._live_display:
                    self._live_display = Live(Text(""), console=self.console, refresh_per_second=10, auto_refresh=False)
                    self._live_display.start()

                self._current_response += chunk

                # Render as markdown for nice formatting
                try:
                    self._live_display.update(Markdown(self._current_response))
                    self._live_display.refresh()
                except Exception:
                    # Fall back to plain text if markdown fails
                    self._live_display.update(Text(self._current_response))
                    self._live_display.refresh()

        except asyncio.CancelledError:
            self.console.print("\n[yellow]Request cancelled.[/]")

        finally:
            # Ensure thinking indicator is stopped
            await self._thinking.stop()
            # Stop live display if it was started
            if self._live_display:
                self._live_display.stop()
                self._live_display = None
            self._cancel_requested = False

        self.console.print()  # Blank line after response

    def _show_help(self) -> None:
        """Display help information."""
        help_text = """
# Auto-Coder Commands

- **/help** - Show this help message
- **/clear** or **/reset** - Clear conversation history and reset correlation ID
- **/id** - Show current correlation ID
- **/quit** or **/exit** - Exit the REPL

# Keyboard Shortcuts

- **Enter** - Submit your input
- **Alt+Enter** - Insert a new line (for multiline input)
- **ESC** - Cancel the current LLM request (during processing)

# Available Tools

The assistant can use these tools:
- **search_files** - Search file names AND contents by regex (e.g., "def main", "TODO")
- **read_file** - Read file contents with line numbers
- **write_file** - Write content to a file (creates or overwrites)
- **edit_file** - Edit a file by replacing exact text matches or line ranges
- **delete_file** - Delete a file (use with caution)
- **list_directory** - Show directory tree with file sizes and dates (like ls -la)
- **run_command** - Execute shell commands

Just describe what you want to do and the assistant will use the appropriate tools.

# Correlation ID

Each conversation session has a unique correlation ID (x-correlation-id) that is
sent with all API requests. This helps track related operations on the API platform.
The correlation ID resets when you use /clear or /reset.
"""
        self.console.print(Markdown(help_text))

    def _listen_for_escape(self) -> None:
        """Listen for ESC key press to cancel the current request.

        This runs in a separate thread during LLM requests.
        """
        try:
            if sys.platform == "win32":
                import msvcrt
                while self._current_task and not self._current_task.done():
                    if msvcrt.kbhit():
                        key = msvcrt.getch()
                        if key == b'\x1b':  # ESC key
                            self._cancel_requested = True
                            return
                    import time
                    time.sleep(0.05)
            else:
                import select
                import termios
                import tty

                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setcbreak(fd)
                    while self._current_task and not self._current_task.done():
                        if select.select([sys.stdin], [], [], 0.05)[0]:
                            key = sys.stdin.read(1)
                            if key == '\x1b':  # ESC key
                                self._cancel_requested = True
                                return
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass  # Ignore errors in key listening

    async def run(self) -> None:
        """Run the interactive REPL."""
        # Set up prompt with history and custom key bindings
        history = FileHistory(self.history_file) if self.history_file else None
        kb = create_key_bindings()
        session: PromptSession = PromptSession(
            history=history,
            style=PROMPT_STYLE,
            key_bindings=kb,
        )

        # Print welcome message with correlation ID
        correlation_id = self.agent.get_correlation_id()
        has_project_context = self.agent.conversation.project_context is not None

        project_status = "[green]PROJECT.md loaded[/]" if has_project_context else "[dim]No PROJECT.md[/]"

        self.console.print(
            Panel(
                "[bold]Welcome to Auto-Coder![/]\n\n"
                "Type your requests and I'll help you with coding tasks.\n"
                "Type [cyan]/help[/] for available commands.\n\n"
                "[dim]Enter to submit, Alt+Enter for new line[/]\n"
                "[dim]Press ESC during a request to cancel[/]\n\n"
                f"{project_status}\n"
                f"[dim]Correlation ID: {correlation_id}[/]",
                border_style="blue",
            )
        )

        try:
            while True:
                try:
                    # Get user input
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: session.prompt(
                            [("class:prompt", ">>> ")],
                        ),
                    )

                    # Create task for processing and start ESC listener
                    self._current_task = asyncio.create_task(self._process_input(user_input))

                    # Run ESC listener in background thread
                    loop = asyncio.get_event_loop()
                    listener_future = loop.run_in_executor(None, self._listen_for_escape)

                    try:
                        await self._current_task
                    finally:
                        self._current_task = None
                        # Cancel the listener
                        listener_future.cancel()

                except KeyboardInterrupt:
                    self.console.print("\n[dim]Goodbye![/]")
                    break
                except EOFError:
                    self.console.print("\n[dim]Goodbye![/]")
                    break
                except Exception as e:
                    self.console.print(f"[red]Error: {e}[/]")

        finally:
            await self.agent.close()
