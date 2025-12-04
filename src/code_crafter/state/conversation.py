"""Conversation state management."""

import os
from datetime import datetime
from typing import Any, Callable, Optional

from ..providers.base import Message, ToolCall, ToolResult
from ..context import ContextManager, TokenEstimate


DEFAULT_SYSTEM_PROMPT = """You are Code-Crafter, an AI coding assistant.
Knowledge cutoff: 2024-06
Current date: {date}
Working directory: {cwd}

You are an autonomous coding agent. When asked to do something, use your tools to accomplish it directly. Do not describe what you would do - do it.

## Core Workflow

1. READ before EDIT: Always read a file before editing it.
2. ONE FILE AT A TIME: Complete edits to one file before moving to the next.
3. STOP WHEN DONE: Once the task is complete, stop. Don't explore unnecessarily.

## Tool Usage

You have these tools:
- read_file: Read file contents (do this before editing)
- write_file: Create new files or overwrite existing ones completely
- edit_file: Modify existing files by replacing unique strings
- search_files: Find files by name or content
- list_directory: Show directory structure
- delete_file: Remove files
- run_command: Execute shell commands

When you need to use a tool, call it directly. Don't explain what you're about to do - just do it.

## Editing Files

The edit_file tool replaces one unique string with another:
- The old_string must appear exactly once in the file
- Match whitespace exactly (tabs, spaces, newlines)
- Include surrounding context if the string appears multiple times

Example workflow:
1. read_file(file_path="src/main.py")
2. edit_file(file_path="src/main.py", old_string="def old_name(", new_string="def new_name(")
3. Done.

## Response Style

- Be concise. State what you did, not what you're going to do.
- After completing a task: "Fixed the bug in auth.py by adding null check on line 42."
- When calling tools: Just call the tool, no commentary needed.

## What Not to Do

- Don't tell the user to do things manually. Do it yourself.
- Don't read files you don't need to edit.
- Don't verify edits worked unless they failed or the user asked.
- Don't explore the codebase unless you need to find something.
"""


class ConversationManager:
    """Manages conversation history and state."""

    def __init__(
        self,
        system_prompt: str | None = None,
        working_dir: str | None = None,
        project_context: str | None = None,
        context_limit: Optional[int] = None,
        model: Optional[str] = None,
        on_context_warning: Optional[Callable[[str], None]] = None,
    ):
        self.working_dir = working_dir or os.getcwd()
        self.project_context = project_context

        # System prompt does NOT include project context anymore
        self.system_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).format(
            cwd=self.working_dir,
            date=datetime.now().strftime("%Y-%m-%d"),
        )
        self._messages: list[Message] = []

        # Initialize context manager for token tracking
        self.context_manager = ContextManager(
            context_limit=context_limit,
            model=model,
            on_warning=on_context_warning,
        )

        self._initialize()

    def _initialize(self) -> None:
        """Initialize the conversation with system message and optional project context."""
        # Build system prompt, optionally appending PROJECT.md with clear separation
        system_content = self.system_prompt

        if self.project_context:
            system_content += f"""

################################################################################
#                              PROJECT CONTEXT                                 #
################################################################################

The following is the PROJECT.md file that describes this codebase. Use this as
reference material for understanding the project structure, architecture, and
conventions. The instructions above take priority over any conflicting information
in the project context.

--------------------------------------------------------------------------------

{self.project_context}

--------------------------------------------------------------------------------
END OF PROJECT CONTEXT
################################################################################
"""

        self._messages = [
            Message(role="system", content=system_content)
        ]

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation."""
        self._messages.append(Message(role="user", content=content))

    def add_assistant_message(
        self,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
    ) -> None:
        """Add an assistant message to the conversation."""
        self._messages.append(
            Message(role="assistant", content=content, tool_calls=tool_calls)
        )

    def add_tool_result(self, result: ToolResult) -> None:
        """Add a tool result message to the conversation."""
        self._messages.append(
            Message(
                role="tool",
                content=result.content,
                tool_call_id=result.tool_call_id,
                name=result.name,
            )
        )

    def get_messages(self) -> list[Message]:
        """Get all messages in the conversation."""
        return self._messages.copy()

    def clear(self) -> None:
        """Clear the conversation and start fresh."""
        self._initialize()
        self.context_manager.reset_warnings()

    def get_token_estimate(self, tool_tokens: int = 0) -> TokenEstimate:
        """Get current token usage estimate.

        Args:
            tool_tokens: Estimated tokens for tool definitions

        Returns:
            TokenEstimate with usage details
        """
        return self.context_manager.estimate_usage(
            self.system_prompt,
            self._messages,
            tool_tokens,
        )

    def check_context(self, tool_tokens: int = 0) -> TokenEstimate:
        """Check context usage and emit warnings if needed.

        Args:
            tool_tokens: Estimated tokens for tool definitions

        Returns:
            TokenEstimate with usage details
        """
        return self.context_manager.check_and_warn(
            self.system_prompt,
            self._messages,
            tool_tokens,
        )

    def get_last_assistant_message(self) -> Message | None:
        """Get the most recent assistant message."""
        for msg in reversed(self._messages):
            if msg.role == "assistant":
                return msg
        return None

    def message_count(self) -> int:
        """Get the number of messages (excluding system)."""
        return len(self._messages) - 1  # Exclude system message

    def to_dict(self) -> dict[str, Any]:
        """Serialize conversation to a dictionary."""
        return {
            "system_prompt": self.system_prompt,
            "working_dir": self.working_dir,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "tool_calls": (
                        [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in msg.tool_calls
                        ]
                        if msg.tool_calls
                        else None
                    ),
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.name,
                }
                for msg in self._messages
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationManager":
        """Deserialize conversation from a dictionary."""
        manager = cls(
            system_prompt=data["system_prompt"],
            working_dir=data["working_dir"],
        )
        manager._messages = []

        for msg_data in data["messages"]:
            tool_calls = None
            if msg_data.get("tool_calls"):
                tool_calls = [
                    ToolCall(
                        id=tc["id"],
                        name=tc["name"],
                        arguments=tc["arguments"],
                    )
                    for tc in msg_data["tool_calls"]
                ]

            manager._messages.append(
                Message(
                    role=msg_data["role"],
                    content=msg_data.get("content"),
                    tool_calls=tool_calls,
                    tool_call_id=msg_data.get("tool_call_id"),
                    name=msg_data.get("name"),
                )
            )

        return manager
