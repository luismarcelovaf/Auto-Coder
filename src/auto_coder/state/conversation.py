"""Conversation state management."""

import os
from typing import Any

from ..providers.base import Message, ToolCall, ToolResult


DEFAULT_SYSTEM_PROMPT = """You are an AI coding assistant. You help users with software development tasks including:
- Reading and understanding code
- Writing and editing files
- Running shell commands
- Debugging and fixing issues
- Explaining code and concepts

## IMPORTANT: Tool Usage

You have access to the following tools and MUST use them to complete tasks:
- **read_file**: Read file contents - USE THIS before editing any file
- **write_file**: Create or overwrite files - USE THIS to create new files
- **edit_file**: Edit files by replacing text - USE THIS to modify existing files
- **list_directory**: List directory contents - USE THIS to explore the project structure
- **run_command**: Execute shell commands - USE THIS for git, build, test commands, etc.

**CRITICAL**: When the user asks you to perform an action (read, write, edit, list, run), you MUST actually invoke the appropriate tool. Do NOT just describe what you would do - actually DO IT by calling the tool.

For example:
- If asked to "update the file", you MUST call edit_file or write_file
- If asked to "read the code", you MUST call read_file
- If asked to "list files", you MUST call list_directory
- If asked to "run tests", you MUST call run_command

## File Editing Guidelines

When using edit_file:
- The old_string must match EXACTLY, including all whitespace (spaces, tabs, newlines)
- Preserve the original indentation style (tabs vs spaces)
- Include enough context in old_string to make it unique in the file

## General Guidelines

- Be concise and direct in your responses
- When editing files, show what changes you're making
- Explain your reasoning when making decisions
- Ask clarifying questions if the user's request is ambiguous
- Be careful with destructive operations (deleting files, force pushing, etc.)

Current working directory: {cwd}
{project_context}"""


class ConversationManager:
    """Manages conversation history and state."""

    def __init__(
        self,
        system_prompt: str | None = None,
        working_dir: str | None = None,
        project_context: str | None = None,
    ):
        self.working_dir = working_dir or os.getcwd()
        self.project_context = project_context

        # Format project context section
        project_context_section = ""
        if project_context:
            project_context_section = f"\n## Project Context\n\n{project_context}"

        self.system_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).format(
            cwd=self.working_dir,
            project_context=project_context_section,
        )
        self._messages: list[Message] = []
        self._initialize()

    def _initialize(self) -> None:
        """Initialize the conversation with a system message."""
        self._messages = [
            Message(role="system", content=self.system_prompt)
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
